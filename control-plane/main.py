"""pg-stress Control Plane — orchestration API for stress test operations.

Separate service that manages generators, WHAT IF scenarios, and AI analysis.
Talks to Docker API (via socket) and PostgreSQL directly.

Endpoints:
  GET  /status                    — Full stack status
  POST /generators/{name}/start   — Start a generator (orm, pgbench)
  POST /generators/{name}/stop    — Stop a generator
  POST /inject                    — Inject rows into a table
  POST /bulk-update               — Bulk update rows
  POST /connections               — Run connection pressure test
  POST /ladder                    — Run growth ladder (find breaking point)
  POST /analyze                   — Run AI analyzer
  GET  /analyze/latest            — Get latest analysis report
  GET  /reports                   — List all reports
  GET  /reports/{id}              — Get a specific report
"""

import asyncio
import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import docker
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("control-plane")

app = FastAPI(title="pg-stress Control Plane", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Configuration ────────────────────────────────────────────────────────

PG_HOST = os.environ.get("PG_HOST", "postgres")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_EXTERNAL_PORT = int(os.environ.get("PG_EXTERNAL_PORT", os.environ.get("PG_PORT", "5434")))
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "postgres")
PG_DATABASE = os.environ.get("PG_DATABASE", "testdb")
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT", "pg-stress")
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/app/reports"))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Docker client ────────────────────────────────────────────────────────

docker_client = docker.from_env()

# ── Job tracking ─────────────────────────────────────────────────────────

jobs: dict[str, dict] = {}


def new_job(job_type: str, meta: dict = None) -> str:
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "type": job_type,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "elapsed_s": 0,
        "progress": 0,
        "progress_msg": "Starting...",
        "before": meta.get("before") if meta else None,
        "after": None,
        "result": None,
        "error": None,
    }
    return job_id


def update_job(job_id: str, progress: int = None, msg: str = None):
    if job_id in jobs:
        started = datetime.fromisoformat(jobs[job_id]["started_at"])
        jobs[job_id]["elapsed_s"] = int((datetime.now(timezone.utc) - started).total_seconds())
        if progress is not None:
            jobs[job_id]["progress"] = min(progress, 100)
        if msg:
            jobs[job_id]["progress_msg"] = msg


def complete_job(job_id: str, result: dict = None, error: str = None):
    if job_id in jobs:
        started = datetime.fromisoformat(jobs[job_id]["started_at"])
        jobs[job_id]["status"] = "failed" if error else "completed"
        jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        jobs[job_id]["elapsed_s"] = int((datetime.now(timezone.utc) - started).total_seconds())
        jobs[job_id]["progress"] = 100 if not error else jobs[job_id]["progress"]
        jobs[job_id]["progress_msg"] = f"Failed: {error}" if error else "Completed"
        jobs[job_id]["after"] = result.get("after") if result else None
        jobs[job_id]["result"] = result
        jobs[job_id]["error"] = error


# ── Database helpers ─────────────────────────────────────────────────────


def get_conn():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, dbname=PG_DATABASE,
    )


def query(sql: str, params=None) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            return []
    finally:
        conn.close()


def execute(sql: str, params=None) -> int:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


# ── Container helpers ────────────────────────────────────────────────────


def find_container(service_name: str):
    """Find a container by compose service name."""
    try:
        containers = docker_client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.service={service_name}"}
        )
        if containers:
            return containers[0]
    except Exception:
        pass
    return None


def container_status(service_name: str) -> dict:
    c = find_container(service_name)
    if not c:
        return {"name": service_name, "status": "not_found"}
    return {
        "name": service_name,
        "status": c.status,
        "health": c.attrs.get("State", {}).get("Health", {}).get("Status", "unknown"),
        "started_at": c.attrs.get("State", {}).get("StartedAt", ""),
    }


# ── Models ───────────────────────────────────────────────────────────────


class InjectRequest(BaseModel):
    table: str
    rows: int
    template: Optional[str] = None


class BulkUpdateRequest(BaseModel):
    table: str
    set_clause: str
    where_clause: Optional[str] = None
    batch_size: int = 100000


class ConnectionsRequest(BaseModel):
    connections: int = 100
    duration: int = 300
    mode: str = "mixed"  # mixed, readonly, tpcb


class LadderRequest(BaseModel):
    steps: list[int] = [10, 25, 50, 100, 200]
    phase_duration: int = 180
    mode: str = "mixed"


class AnalyzeRequest(BaseModel):
    focus: Optional[str] = None  # tuning, queries, capacity, or None for full
    model: str = "claude-sonnet-4-20250514"


# ── Status endpoint ──────────────────────────────────────────────────────


@app.get("/status")
def get_status():
    services = {}
    for svc in ["postgres", "load-generator", "dashboard",
                 "load-generator-orm", "pgbench-runner", "collector", "truth-service", "analyzer"]:
        services[svc] = container_status(svc)

    # Database stats.
    db_stats = {}
    try:
        rows = query("""
            SELECT pg_size_pretty(pg_database_size(%s)) AS db_size,
                   pg_database_size(%s) AS db_size_bytes,
                   (SELECT count(*) FROM pg_stat_activity WHERE datname = %s) AS connections
        """, (PG_DATABASE, PG_DATABASE, PG_DATABASE))
        if rows:
            db_stats = rows[0]
    except Exception as e:
        db_stats = {"error": str(e)}

    # Table summary.
    tables = {}
    try:
        rows = query("""
            SELECT relname, n_live_tup, n_dead_tup,
                   pg_size_pretty(pg_total_relation_size(relid)) AS size
            FROM pg_stat_user_tables ORDER BY n_live_tup DESC
        """)
        tables = {r["relname"]: r for r in rows}
    except Exception:
        pass

    return {
        "services": services,
        "database": db_stats,
        "tables": tables,
        "jobs": {k: v for k, v in jobs.items() if v["status"] == "running"},
        "reports": len(list(REPORTS_DIR.glob("*.json"))),
    }


# ── Generator control ───────────────────────────────────────────────────


GENERATOR_PROFILES = {
    "orm": "orm",
    "pgbench": "pgbench",
}


@app.post("/generators/{name}/start")
def start_generator(name: str):
    if name not in GENERATOR_PROFILES:
        raise HTTPException(404, f"Unknown generator: {name}. Options: {list(GENERATOR_PROFILES.keys())}")

    profile = GENERATOR_PROFILES[name]
    service = "load-generator-orm" if name == "orm" else "pgbench-runner"

    c = find_container(service)
    if c and c.status == "running":
        return {"status": "already_running", "service": service}

    try:
        result = subprocess.run(
            ["docker", "compose", "--profile", profile, "up", "-d", "--build", service],
            cwd="/app/project",
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise HTTPException(500, f"Failed to start {name}: {result.stderr}")
        return {"status": "started", "service": service}
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"Timeout starting {name}")


@app.post("/generators/{name}/stop")
def stop_generator(name: str):
    if name not in GENERATOR_PROFILES:
        raise HTTPException(404, f"Unknown generator: {name}")

    service = "load-generator-orm" if name == "orm" else "pgbench-runner"
    c = find_container(service)
    if not c:
        return {"status": "not_found", "service": service}
    if c.status != "running":
        return {"status": "not_running", "service": service}

    c.stop(timeout=10)
    return {"status": "stopped", "service": service}


# ── Inject rows ──────────────────────────────────────────────────────────


def _do_inject(job_id: str, req: InjectRequest):
    try:
        # Snapshot before.
        before_rows = query("SELECT n_live_tup FROM pg_stat_user_tables WHERE relname = %s", (req.table,))
        before_count = before_rows[0]["n_live_tup"] if before_rows else 0
        before_size = query("SELECT pg_size_pretty(pg_total_relation_size(%s::regclass)) AS size", (req.table,))
        jobs[job_id]["before"] = {"rows": before_count, "size": before_size[0]["size"] if before_size else "?"}
        update_job(job_id, progress=0, msg=f"Starting inject into {req.table} ({before_count:,} rows)")

        batch_size = min(req.rows, 500000)
        remaining = req.rows
        total_inserted = 0

        if req.template:
            template = req.template
        else:
            cols = query("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = %s AND table_schema = 'public'
                  AND column_default LIKE 'nextval%%'
                ORDER BY ordinal_position
            """, (req.table,))

            template = f"""
                INSERT INTO {req.table}
                SELECT * FROM {req.table}
                ORDER BY random()
                LIMIT {{batch}}
            """

        while remaining > 0:
            batch = min(remaining, batch_size)
            sql = template.replace("{batch}", str(batch))
            execute(sql)
            remaining -= batch
            total_inserted += batch
            pct = int((total_inserted / req.rows) * 100)
            update_job(job_id, progress=pct, msg=f"Injected {total_inserted:,} / {req.rows:,} rows into {req.table}")
            log.info("inject %s: %d / %d rows", req.table, total_inserted, req.rows)

        update_job(job_id, progress=95, msg=f"Running ANALYZE on {req.table}...")
        execute(f"ANALYZE {req.table}")

        # Snapshot after.
        after_rows = query("SELECT n_live_tup FROM pg_stat_user_tables WHERE relname = %s", (req.table,))
        after_count = after_rows[0]["n_live_tup"] if after_rows else 0
        after_size = query("SELECT pg_size_pretty(pg_total_relation_size(%s::regclass)) AS size", (req.table,))
        after = {"rows": after_count, "size": after_size[0]["size"] if after_size else "?"}

        complete_job(job_id, {"table": req.table, "rows_inserted": total_inserted, "after": after})
    except Exception as e:
        complete_job(job_id, error=str(e))


@app.post("/inject")
def inject_rows(req: InjectRequest, background_tasks: BackgroundTasks):
    job_id = new_job("inject")
    background_tasks.add_task(_do_inject, job_id, req)
    return {"job_id": job_id, "status": "started", "table": req.table, "rows": req.rows}


# ── Bulk update ──────────────────────────────────────────────────────────


def _do_bulk_update(job_id: str, req: BulkUpdateRequest):
    try:
        before_rows = query("SELECT n_live_tup, n_dead_tup FROM pg_stat_user_tables WHERE relname = %s", (req.table,))
        before = {"rows": before_rows[0]["n_live_tup"] if before_rows else 0, "dead": before_rows[0]["n_dead_tup"] if before_rows else 0}
        jobs[job_id]["before"] = before
        update_job(job_id, progress=0, msg=f"Starting bulk update on {req.table}")

        where = f"WHERE {req.where_clause}" if req.where_clause else ""
        total_updated = 0
        batch_num = 0

        while True:
            sql = f"""
                UPDATE {req.table} SET {req.set_clause}
                WHERE ctid IN (
                    SELECT ctid FROM {req.table} {where}
                    LIMIT {req.batch_size}
                )
            """
            rows = execute(sql)
            total_updated += rows
            batch_num += 1
            update_job(job_id, msg=f"Updated {total_updated:,} rows in {req.table} (batch {batch_num})")
            log.info("bulk-update %s: %d rows (total: %d)", req.table, rows, total_updated)
            if rows < req.batch_size:
                break

        update_job(job_id, progress=95, msg=f"Running ANALYZE on {req.table}...")
        execute(f"ANALYZE {req.table}")

        after_rows = query("SELECT n_live_tup, n_dead_tup FROM pg_stat_user_tables WHERE relname = %s", (req.table,))
        after = {"rows": after_rows[0]["n_live_tup"] if after_rows else 0, "dead": after_rows[0]["n_dead_tup"] if after_rows else 0}

        complete_job(job_id, {"table": req.table, "rows_updated": total_updated, "after": after})
    except Exception as e:
        complete_job(job_id, error=str(e))


@app.post("/bulk-update")
def bulk_update(req: BulkUpdateRequest, background_tasks: BackgroundTasks):
    job_id = new_job("bulk_update")
    background_tasks.add_task(_do_bulk_update, job_id, req)
    return {"job_id": job_id, "status": "started", "table": req.table}


# ── Connection pressure ─────────────────────────────────────────────────


def _do_connections(job_id: str, req: ConnectionsRequest):
    try:
        # Snapshot before.
        before = query("""
            SELECT xact_commit, xact_rollback, deadlocks,
                   blks_hit, blks_read, temp_files
            FROM pg_stat_database WHERE datname = %s
        """, (PG_DATABASE,))

        # Run pgbench inline.
        mode_flag = {
            "readonly": "--select-only",
            "tpcb": "",
            "mixed": "",
        }.get(req.mode, "")

        cmd = [
            "pgbench", "-h", PG_HOST, "-p", str(PG_PORT),
            "-U", PG_USER, "-d", PG_DATABASE,
            "-c", str(req.connections), "-j", str(min(req.connections, 16)),
            "-T", str(req.duration), "--no-vacuum",
        ]
        if mode_flag:
            cmd.append(mode_flag)

        env = os.environ.copy()
        env["PGPASSWORD"] = PG_PASSWORD

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=req.duration + 60, env=env)

        # Snapshot after.
        after = query("""
            SELECT xact_commit, xact_rollback, deadlocks,
                   blks_hit, blks_read, temp_files
            FROM pg_stat_database WHERE datname = %s
        """, (PG_DATABASE,))

        # Parse TPS from pgbench output.
        tps = 0
        latency = 0
        for line in result.stdout.splitlines():
            if "tps =" in line and "excluding" in line:
                try:
                    tps = float(line.split("tps =")[1].split("(")[0].strip())
                except (ValueError, IndexError):
                    pass
            if "latency average" in line:
                try:
                    latency = float(line.split("=")[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass

        deltas = {}
        if before and after:
            for key in before[0]:
                deltas[key] = after[0][key] - before[0][key]

        complete_job(job_id, {
            "connections": req.connections,
            "duration": req.duration,
            "mode": req.mode,
            "tps": tps,
            "latency_avg_ms": latency,
            "deltas": deltas,
            "raw_output": result.stdout[-1000:] if result.stdout else "",
        })
    except Exception as e:
        complete_job(job_id, error=str(e))


@app.post("/connections")
def connection_pressure(req: ConnectionsRequest, background_tasks: BackgroundTasks):
    job_id = new_job("connections")
    background_tasks.add_task(_do_connections, job_id, req)
    return {"job_id": job_id, "status": "started", "connections": req.connections, "duration": req.duration}


# ── Growth ladder ────────────────────────────────────────────────────────


def _do_ladder(job_id: str, req: LadderRequest):
    try:
        phases = []
        for step_conns in req.steps:
            log.info("ladder: phase %d connections for %ds", step_conns, req.phase_duration)

            # Snapshot before phase.
            before = query("""
                SELECT xact_commit, xact_rollback, deadlocks,
                       blks_hit, blks_read, temp_files,
                       CASE WHEN blks_hit + blks_read > 0
                            THEN round(blks_hit::numeric / (blks_hit + blks_read), 4)
                            ELSE 1 END AS cache_ratio
                FROM pg_stat_database WHERE datname = %s
            """, (PG_DATABASE,))

            # Run pgbench for this phase.
            mode_flag = "--select-only" if req.mode == "readonly" else ""
            cmd = [
                "pgbench", "-h", PG_HOST, "-p", str(PG_PORT),
                "-U", PG_USER, "-d", PG_DATABASE,
                "-c", str(step_conns), "-j", str(min(step_conns, 16)),
                "-T", str(req.phase_duration), "--no-vacuum",
            ]
            if mode_flag:
                cmd.append(mode_flag)

            env = os.environ.copy()
            env["PGPASSWORD"] = PG_PASSWORD

            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=req.phase_duration + 60, env=env,
            )

            # Snapshot after phase.
            after = query("""
                SELECT xact_commit, xact_rollback, deadlocks,
                       blks_hit, blks_read, temp_files,
                       CASE WHEN blks_hit + blks_read > 0
                            THEN round(blks_hit::numeric / (blks_hit + blks_read), 4)
                            ELSE 1 END AS cache_ratio
                FROM pg_stat_database WHERE datname = %s
            """, (PG_DATABASE,))

            # Parse results.
            tps = 0
            latency = 0
            for line in result.stdout.splitlines():
                if "tps =" in line and "excluding" in line:
                    try:
                        tps = float(line.split("tps =")[1].split("(")[0].strip())
                    except (ValueError, IndexError):
                        pass
                if "latency average" in line:
                    try:
                        latency = float(line.split("=")[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass

            new_deadlocks = 0
            new_temp_files = 0
            cache_ratio = 0
            if before and after:
                new_deadlocks = after[0]["deadlocks"] - before[0]["deadlocks"]
                new_temp_files = after[0]["temp_files"] - before[0]["temp_files"]
                cache_ratio = float(after[0]["cache_ratio"])

            phase = {
                "connections": step_conns,
                "tps": tps,
                "latency_avg_ms": latency,
                "cache_ratio": cache_ratio,
                "deadlocks": new_deadlocks,
                "temp_files": new_temp_files,
            }
            phases.append(phase)
            log.info("ladder phase: %s", json.dumps(phase))

        # Save ladder report.
        report_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        report_path = REPORTS_DIR / f"ladder-{report_id}.json"
        report = {
            "type": "ladder",
            "id": report_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": {"steps": req.steps, "phase_duration": req.phase_duration, "mode": req.mode},
            "phases": phases,
        }
        report_path.write_text(json.dumps(report, indent=2, default=str))

        complete_job(job_id, report)
    except Exception as e:
        complete_job(job_id, error=str(e))


@app.post("/ladder")
def growth_ladder(req: LadderRequest, background_tasks: BackgroundTasks):
    job_id = new_job("ladder")
    background_tasks.add_task(_do_ladder, job_id, req)
    total_time = len(req.steps) * req.phase_duration
    return {
        "job_id": job_id,
        "status": "started",
        "steps": req.steps,
        "estimated_duration_seconds": total_time,
    }


# ── AI Analyzer ──────────────────────────────────────────────────────────


def _do_analyze(job_id: str, req: AnalyzeRequest):
    try:
        # Import the analyzer modules.
        import sys
        sys.path.insert(0, "/app/analyzer")
        from collect import collect_all
        from analyze import run_analysis

        log.info("analyze: collecting data...")
        data = collect_all()

        log.info("analyze: running AI analysis (focus=%s)...", req.focus)
        analysis = run_analysis(data, focus=req.focus, model=req.model)

        # Save report.
        report_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        focus_label = req.focus or "full"
        report_path = REPORTS_DIR / f"analysis-{focus_label}-{report_id}.json"
        report = {
            "type": "analysis",
            "id": report_id,
            "focus": focus_label,
            "model": req.model,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "analysis": analysis,
        }
        report_path.write_text(json.dumps(report, indent=2, default=str))

        # Also save markdown.
        md_path = REPORTS_DIR / f"analysis-{focus_label}-{report_id}.md"
        md_path.write_text(f"# pg-stress Analysis ({focus_label})\n\n{analysis}\n")

        complete_job(job_id, {"report_id": report_id, "focus": focus_label})
    except Exception as e:
        log.error("analyze failed: %s", e)
        complete_job(job_id, error=str(e))


@app.post("/analyze")
def run_analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY not configured")

    job_id = new_job("analyze")
    background_tasks.add_task(_do_analyze, job_id, req)
    return {"job_id": job_id, "status": "started", "focus": req.focus or "full"}


@app.get("/analyze/latest")
def get_latest_analysis():
    reports = sorted(REPORTS_DIR.glob("analysis-*.json"), reverse=True)
    if not reports:
        raise HTTPException(404, "No analysis reports found")
    return json.loads(reports[0].read_text())


# ── Data management (flush) ──────────────────────────────────────────────


class FlushRequest(BaseModel):
    confirmation: str  # Must be "DELETE ALL DATA"
    target: str = "all"  # "all", "metrics", "reports", "jobs"


@app.post("/flush")
def flush_data(req: FlushRequest):
    if req.confirmation != "DELETE ALL DATA":
        raise HTTPException(400, "Confirmation must be exactly: DELETE ALL DATA")

    result = {}

    if req.target in ("all", "metrics"):
        # Clear dashboard metrics by calling its reset endpoint.
        try:
            import httpx
            httpx.post("http://dashboard:8000/api/reset", timeout=5)
            result["metrics"] = "cleared"
        except Exception:
            result["metrics"] = "dashboard not reachable"

    if req.target in ("all", "reports"):
        count = 0
        for f in REPORTS_DIR.glob("*"):
            f.unlink()
            count += 1
        result["reports"] = f"{count} files deleted"

    if req.target in ("all", "jobs"):
        jobs.clear()
        result["jobs"] = "cleared"

    log.warning("FLUSH executed: target=%s result=%s", req.target, result)
    return {"status": "flushed", "target": req.target, "result": result}


# ── Jobs ─────────────────────────────────────────────────────────────────


@app.get("/jobs")
def list_jobs():
    return list(jobs.values())


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


# ── Reports ──────────────────────────────────────────────────────────────


@app.get("/reports")
def list_reports():
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            reports.append({
                "id": data.get("id", f.stem),
                "type": data.get("type", "unknown"),
                "focus": data.get("focus", ""),
                "created_at": data.get("created_at", ""),
                "file": f.name,
            })
        except Exception:
            pass
    return reports


@app.get("/reports/{filename}")
def get_report(filename: str):
    path = REPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Report not found")
    if path.suffix == ".md":
        return FileResponse(path, media_type="text/markdown")
    return json.loads(path.read_text())


# ── Test Runs ────────────────────────────────────────────────────────────


class StartTestRequest(BaseModel):
    name: str
    intensity: str = "medium"  # low, medium, high
    baseline_dump: Optional[str] = None  # path to dump for reset; None = keep current DB


class StopTestRequest(BaseModel):
    pass


def _snapshot_db() -> dict:
    """Snapshot current database state: per-table row counts and sizes."""
    try:
        tables = {}
        rows = query("""
            SELECT relname, n_live_tup, n_dead_tup,
                   pg_size_pretty(pg_total_relation_size(relid)) AS size,
                   pg_total_relation_size(relid) AS size_bytes
            FROM pg_stat_user_tables ORDER BY n_live_tup DESC
        """)
        total_rows = 0
        for r in rows:
            tables[r["relname"]] = {"rows": r["n_live_tup"], "dead": r["n_dead_tup"], "size": r["size"]}
            total_rows += r["n_live_tup"]

        db_size = query("SELECT pg_size_pretty(pg_database_size(%s)) AS size", (PG_DATABASE,))
        return {
            "database": PG_DATABASE,
            "total_rows": total_rows,
            "db_size": db_size[0]["size"] if db_size else "?",
            "tables": tables,
        }
    except Exception as e:
        return {"error": str(e)}


def _reset_db_from_dump(dump_path: str):
    """Restore database from a dump file (hard reset to baseline)."""
    log.info("Resetting database from %s", dump_path)

    # Stop generators.
    for svc in ["load-generator", "load-generator-orm", "pgbench-runner"]:
        c = find_container(svc)
        if c and c.status == "running":
            c.stop(timeout=10)
            log.info("Stopped %s", svc)

    # Restore dump.
    result = subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl",
         "-h", PG_HOST, "-p", str(PG_PORT), "-U", PG_USER, "-d", PG_DATABASE,
         "--jobs=4", dump_path],
        capture_output=True, text=True, timeout=600,
        env={**os.environ, "PGPASSWORD": PG_PASSWORD},
    )
    if result.returncode not in (0, 1):  # pg_restore returns 1 for warnings
        log.warning("pg_restore warnings: %s", result.stderr[:500])

    # Reset stats.
    try:
        execute("SELECT pg_stat_statements_reset()")
    except Exception:
        pass
    try:
        execute("SELECT pg_stat_reset()")
    except Exception:
        pass
    execute("ANALYZE VERBOSE")
    log.info("Database reset and analyzed")


def _notify_dashboard_test_run(action: str, test_run_id: str, name: str, baseline_id: str,
                                intensity: str, db_before: dict):
    """Notify dashboard about test run state changes."""
    try:
        import httpx
        if action == "start":
            httpx.post("http://dashboard:8000/api/test-run/start", json={
                "id": test_run_id, "name": name, "baseline_id": baseline_id,
                "intensity": intensity, "db_before": db_before,
            }, timeout=5)
        elif action == "stop":
            httpx.post("http://dashboard:8000/api/test-run/stop", json={
                "id": test_run_id, "db_after": db_before,  # db_before here is actually db_after
            }, timeout=5)
    except Exception as e:
        log.warning("Failed to notify dashboard: %s", e)


@app.post("/tests/start")
def start_test(req: StartTestRequest, background_tasks: BackgroundTasks):
    """Start a new test run. Optionally reset DB from baseline dump."""

    # Stop any running test.
    # Check dashboard for active run.
    active = None
    try:
        import httpx
        r = httpx.get("http://dashboard:8000/api/test-run", timeout=5)
        active = r.json() if r.status_code == 200 else None
    except Exception:
        pass

    # If there's a running test, stop it first.
    if active and active.get("status") == "running":
        after_snap = _snapshot_db()
        _notify_dashboard_test_run("stop", active["id"], active["name"], "", "", after_snap)

    # Reset DB if dump path provided.
    baseline_id = ""
    if req.baseline_dump:
        _reset_db_from_dump(req.baseline_dump)
        # Save/update baseline.
        snap = _snapshot_db()
        try:
            import httpx
            r = httpx.post("http://dashboard:8000/api/baseline", json={
                "name": os.path.basename(req.baseline_dump),
                "dump_path": req.baseline_dump,
                "tables": snap.get("tables", {}),
                "total_rows": snap.get("total_rows", 0),
                "db_size": snap.get("db_size", "?"),
            }, timeout=5)
            baseline_id = r.json().get("id", "")
        except Exception:
            pass

    # Snapshot before state.
    db_before = _snapshot_db()

    # Generate test run ID.
    test_run_id = str(uuid.uuid4())[:8]

    # Notify dashboard to start tracking.
    _notify_dashboard_test_run("start", test_run_id, req.name, baseline_id, req.intensity, db_before)

    # Set intensity and restart generators.
    try:
        from main import _set_intensity
        _set_intensity(req.intensity)
    except Exception:
        pass

    # Restart generators.
    for svc in ["load-generator", "load-generator-orm"]:
        c = find_container(svc)
        if c:
            try:
                c.restart(timeout=10)
            except Exception:
                pass

    return {
        "test_run_id": test_run_id,
        "name": req.name,
        "intensity": req.intensity,
        "baseline_reset": bool(req.baseline_dump),
        "db_before": db_before,
    }


@app.post("/tests/stop")
def stop_test():
    """Stop the current test run and save final state."""
    active = None
    try:
        import httpx
        r = httpx.get("http://dashboard:8000/api/test-run", timeout=5)
        active = r.json() if r.status_code == 200 else None
    except Exception:
        pass

    if not active or active.get("status") != "running":
        raise HTTPException(400, "No active test run")

    db_after = _snapshot_db()
    _notify_dashboard_test_run("stop", active["id"], active.get("name", ""), "", "", db_after)

    return {
        "test_run_id": active["id"],
        "name": active.get("name"),
        "db_after": db_after,
    }


@app.get("/tests")
def list_tests():
    """List all test runs from dashboard store."""
    try:
        import httpx
        r = httpx.get("http://dashboard:8000/api/test-runs", timeout=5)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


@app.get("/tests/active")
def get_active_test():
    """Get the currently running test."""
    try:
        import httpx
        r = httpx.get("http://dashboard:8000/api/test-run", timeout=5)
        return r.json() if r.status_code == 200 else {"status": "no_active_test"}
    except Exception:
        return {"status": "no_active_test"}


# ── Import (BYOD) ────────────────────────────────────────────────────────


class ImportRequest(BaseModel):
    dump_path: str  # Path to pg_dump file on the server
    database: Optional[str] = None  # Target DB name (default: testdb)
    jobs: int = 4


def _do_import(job_id: str, req: ImportRequest):
    try:
        db = req.database or PG_DATABASE
        dump_path = req.dump_path

        log.info("import: restoring %s into %s...", dump_path, db)

        env = os.environ.copy()
        env["PGPASSWORD"] = PG_PASSWORD

        # Drop and recreate database.
        subprocess.run(
            ["psql", "-h", PG_HOST, "-p", str(PG_PORT), "-U", PG_USER,
             "-c", f"DROP DATABASE IF EXISTS {db}",
             "-c", f"CREATE DATABASE {db}"],
            env=env, capture_output=True, text=True, timeout=30,
        )

        # Restore dump.
        result = subprocess.run(
            ["pg_restore", "-h", PG_HOST, "-p", str(PG_PORT), "-U", PG_USER,
             "-d", db, "--jobs", str(req.jobs), "--no-owner", "--no-acl", dump_path],
            env=env, capture_output=True, text=True, timeout=3600,
        )

        # ANALYZE.
        subprocess.run(
            ["psql", "-h", PG_HOST, "-p", str(PG_PORT), "-U", PG_USER, "-d", db,
             "-c", "ANALYZE VERBOSE"],
            env=env, capture_output=True, text=True, timeout=600,
        )

        # Auto-detect table sizes for BYOD.
        table_counts = query("""
            SELECT relname, n_live_tup
            FROM pg_stat_user_tables
            WHERE n_live_tup > 0
            ORDER BY n_live_tup DESC
        """)

        complete_job(job_id, {
            "database": db,
            "dump_path": dump_path,
            "tables": len(table_counts),
            "table_counts": {r["relname"]: r["n_live_tup"] for r in table_counts[:20]},
            "restore_stderr": result.stderr[-500:] if result.stderr else "",
        })
    except Exception as e:
        complete_job(job_id, error=str(e))


@app.post("/import")
def import_dump(req: ImportRequest, background_tasks: BackgroundTasks):
    if not os.path.exists(req.dump_path):
        raise HTTPException(400, f"Dump file not found: {req.dump_path}")
    job_id = new_job("import")
    background_tasks.add_task(_do_import, job_id, req)
    return {"job_id": job_id, "status": "started", "dump_path": req.dump_path}


# ── Configuration ────────────────────────────────────────────────────────

INTENSITY_DIR = Path("/app/project/configs/intensity")

INTENSITY_PRESETS = {
    "low": "Light load. No chaos. Safe for small databases.",
    "medium": "Standard OLTP. Moderate bursts. Chaos at 25%.",
    "high": "Heavy stress. 80 connections. Chaos at 50%. Finds breaking points.",
}


@app.get("/config")
def get_config():
    """Current database and intensity configuration."""
    # Read current intensity from active env vars.
    chaos = os.environ.get("LOADGEN_CHAOS_PROBABILITY", "25")
    max_conns = os.environ.get("LOADGEN_BURST_HEAVY_CONNS", "50")
    current = "medium"
    if chaos == "0":
        current = "low"
    elif int(max_conns) >= 80:
        current = "high"

    import socket
    display_host = os.environ.get("PG_DISPLAY_HOST", socket.gethostname())

    return {
        "database": {
            "host": display_host,
            "port": PG_EXTERNAL_PORT,
            "user": PG_USER,
            "database": PG_DATABASE,
        },
        "intensity": {
            "current": current,
            "presets": INTENSITY_PRESETS,
        },
        "env_vars": {
            k: v for k, v in os.environ.items()
            if k.startswith(("LOADGEN_", "ORM_", "PGBENCH_", "STRESS_", "PG_"))
        },
    }


class IntensityRequest(BaseModel):
    level: str  # low, medium, high


@app.post("/config/intensity")
def set_intensity(req: IntensityRequest):
    """Switch intensity preset and restart load generators to apply."""
    if req.level not in INTENSITY_PRESETS:
        raise HTTPException(400, f"Unknown intensity: {req.level}. Options: {list(INTENSITY_PRESETS.keys())}")

    env_file = INTENSITY_DIR / f"{req.level}.env"
    if not env_file.exists():
        raise HTTPException(500, f"Preset file not found: {env_file}")

    # Read the preset vars.
    applied = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            applied[key.strip()] = val.strip()
            os.environ[key.strip()] = val.strip()

    # Write a combined .env to the project directory so docker compose picks it up.
    project_env = Path("/app/project/.env")
    existing = {}
    if project_env.exists():
        for line in project_env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    existing.update(applied)

    with open(project_env, "w") as f:
        f.write(f"# pg-stress — intensity: {req.level} (auto-generated)\n")
        for k, v in sorted(existing.items()):
            f.write(f"{k}={v}\n")

    # Recreate load generators with new env vars via Docker SDK.
    # We can't use `docker compose` from inside the container, so we
    # stop the old container, clone its config with updated env, and start a new one.
    restarted = []

    for svc_name in ["load-generator", "load-generator-orm"]:
        c = find_container(svc_name)
        if not c or c.status != "running":
            continue
        try:
            # Read current container config.
            img = c.image.id
            net = list(c.attrs["NetworkSettings"]["Networks"].keys())
            current_env = c.attrs["Config"]["Env"] or []

            # Build new env: keep non-LOADGEN/ORM/PGBENCH/STRESS vars, add preset vars.
            prefix = ("LOADGEN_", "ORM_", "PGBENCH_", "STRESS_LIMIT_", "STRESS_MAX_")
            new_env = [e for e in current_env if not any(e.startswith(p) for p in prefix)]
            for k, v in applied.items():
                new_env.append(f"{k}={v}")

            # Stop and remove old container.
            old_name = c.name
            c.stop(timeout=10)
            c.remove()

            # Start new container with same image, network, and updated env.
            new_c = docker_client.containers.run(
                img,
                name=old_name,
                environment=new_env,
                network=net[0] if net else "pg-stress_stress-net",
                detach=True,
                restart_policy={"Name": "unless-stopped"},
            )
            restarted.append(svc_name)
            log.info("intensity: recreated %s with %s env vars for %s", svc_name, len(new_env), req.level)
        except Exception as e:
            log.error("intensity: failed to recreate %s: %s", svc_name, e)

    return {
        "status": "applied_and_restarted",
        "intensity": req.level,
        "description": INTENSITY_PRESETS[req.level],
        "vars_set": len(applied),
        "restarted": restarted,
    }


# ── Health ───────────────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    return {"status": "ok", "service": "control-plane"}
