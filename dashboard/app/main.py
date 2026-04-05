from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import httpx
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.metrics_store import MetricsStore
from app.pg_poller import PGPoller
from app.safety_monitor import SafetyMonitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard")

settings = Settings()
store = MetricsStore(max_samples=settings.max_samples)
scenario = settings.load_scenario()
start_time = datetime.now(timezone.utc)

pool: asyncpg.Pool | None = None
poller: PGPoller | None = None
monitor: SafetyMonitor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, poller, monitor

    log.info("connecting to %s:%d/%s", settings.pg_host, settings.pg_port, settings.pg_database)
    pool = await asyncpg.create_pool(
        dsn=settings.dsn,
        min_size=1,
        max_size=3,
    )

    poller = PGPoller(pool, store, settings)
    monitor = SafetyMonitor(pool, store, settings)

    poller_task = asyncio.create_task(poller.run())
    monitor_task = asyncio.create_task(monitor.run())

    log.info("dashboard ready at http://%s:%d", settings.host, settings.port)
    yield

    poller_task.cancel()
    monitor_task.cancel()
    await pool.close()


app = FastAPI(title="stress-dashboard", lifespan=lifespan)

static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(static_dir / "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def api_status():
    latest = store.latest()
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

    # Try to get load gen status.
    loadgen_status = None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.loadgen_url}/healthz")
            if resp.status_code == 200:
                loadgen_status = resp.json()
    except Exception:
        pass

    return {
        "status": "running",
        "elapsed_seconds": int(elapsed),
        "start_time": start_time.isoformat(),
        "scenario": scenario.get("name", "default"),
        "samples_collected": len(store.samples),
        "latest_sample": latest.to_dict() if latest else None,
        "loadgen": loadgen_status,
    }


@app.get("/api/metrics")
async def api_metrics(
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
):
    from_dt = None
    to_dt = None

    if from_ts:
        from_dt = datetime.fromisoformat(from_ts)
        if from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=timezone.utc)
    if to_ts:
        to_dt = datetime.fromisoformat(to_ts)
        if to_dt.tzinfo is None:
            to_dt = to_dt.replace(tzinfo=timezone.utc)

    samples = store.query(from_ts=from_dt, to_ts=to_dt)

    return {
        "count": len(samples),
        "samples": [s.to_dict() for s in samples],
    }


@app.get("/api/tables")
async def api_tables():
    latest = store.latest()
    limits = settings.table_limits
    tables = []

    if latest:
        for name, rows in latest.table_rows.items():
            limit = limits.get(name)
            tables.append({
                "name": name,
                "rows": rows,
                "dead_tuples": latest.table_dead_tuples.get(name, 0),
                "size_bytes": latest.table_size_bytes.get(name, 0),
                "limit": limit,
                "pct_of_limit": round(rows / limit * 100, 1) if limit and limit > 0 else None,
            })

    events = store.recent_safety_events(20)
    return {
        "tables": sorted(tables, key=lambda t: t["rows"], reverse=True),
        "safety_events": [
            {
                "timestamp": e.timestamp.isoformat(),
                "table": e.table,
                "action": e.action,
                "rows_before": e.rows_before,
                "rows_after": e.rows_after,
                "limit": e.limit,
                "detail": e.detail,
            }
            for e in events
        ],
    }


@app.post("/api/reset")
async def api_reset():
    """Clear all collected samples and reset the start time."""
    global start_time
    store.samples.clear()
    start_time = datetime.now(timezone.utc)
    log.info("metrics reset — all samples cleared")
    return {"status": "ok", "message": "All samples cleared"}


@app.get("/api/analytics")
async def api_analytics(minutes: int = Query(60)):
    """DuckDB-powered analytics summary over the last N minutes."""
    from app.analytics import summary, tps_by_minute, growth_rate
    return {
        "summary": summary(minutes),
        "tps_by_minute": tps_by_minute(minutes),
        "growth": growth_rate(),
    }


@app.get("/api/config")
async def api_config():
    return {
        "scenario": scenario,
        "settings": {
            "poll_interval_seconds": settings.poll_interval_seconds,
            "safety_check_interval_seconds": settings.safety_check_interval_seconds,
            "max_database_size_bytes": settings.max_database_size_bytes,
            "table_limits": settings.table_limits,
            "prune_to_pct": settings.prune_to_pct,
        },
    }


@app.post("/api/prune/{table}")
async def api_prune(table: str):
    if table not in settings.table_limits:
        return JSONResponse(
            status_code=400,
            content={"error": f"table '{table}' is not in the monitored list"},
        )

    if not monitor:
        return JSONResponse(status_code=503, content={"error": "monitor not initialized"})

    limit = settings.table_limits[table]
    target = int(limit * settings.prune_to_pct / 100)

    async with pool.acquire() as conn:
        count = await conn.fetchval(f"SELECT count(*) FROM {table}")
        if count <= target:
            return {"message": f"{table} has {count:,} rows, below target {target:,}. No prune needed."}

        rows_to_delete = count - target
        batch = min(rows_to_delete, settings.prune_batch_size)
        result = await conn.execute(
            f"DELETE FROM {table} WHERE ctid IN "
            f"(SELECT ctid FROM {table} ORDER BY created_at ASC LIMIT $1)",
            batch,
        )
        deleted = int(result.split()[-1]) if result else 0

    return {"message": f"Pruned {deleted:,} rows from {table} (was {count:,}, target {target:,})"}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
