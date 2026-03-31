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


def new_job(job_type: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "type": job_type,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "result": None,
        "error": None,
    }
    return job_id


def complete_job(job_id: str, result: dict = None, error: str = None):
    if job_id in jobs:
        jobs[job_id]["status"] = "failed" if error else "completed"
        jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
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
        batch_size = min(req.rows, 500000)
        remaining = req.rows
        total_inserted = 0

        if req.template:
            template = req.template
        else:
            # Auto-generate INSERT based on table structure.
            cols = query("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = %s AND table_schema = 'public'
                  AND column_default LIKE 'nextval%%'  -- skip serial PKs
                ORDER BY ordinal_position
            """, (req.table,))

            # Use a generic generate_series INSERT.
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
            log.info("inject %s: %d / %d rows", req.table, total_inserted, req.rows)

        # Run ANALYZE after injection.
        execute(f"ANALYZE {req.table}")

        complete_job(job_id, {"table": req.table, "rows_inserted": total_inserted})
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
        where = f"WHERE {req.where_clause}" if req.where_clause else ""
        total_updated = 0

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
            log.info("bulk-update %s: %d rows (total: %d)", req.table, rows, total_updated)
            if rows < req.batch_size:
                break

        execute(f"ANALYZE {req.table}")
        complete_job(job_id, {"table": req.table, "rows_updated": total_updated})
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


# ── Health ───────────────────────────────────────────────────────────────


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

    return {
        "database": {
            "host": PG_HOST,
            "port": PG_PORT,
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
    """Switch intensity preset. Requires stack restart to take effect."""
    if req.level not in INTENSITY_PRESETS:
        raise HTTPException(400, f"Unknown intensity: {req.level}. Options: {list(INTENSITY_PRESETS.keys())}")

    env_file = INTENSITY_DIR / f"{req.level}.env"
    if not env_file.exists():
        raise HTTPException(500, f"Preset file not found: {env_file}")

    # Read the preset and apply to environment.
    applied = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip()
            applied[key.strip()] = val.strip()

    return {
        "status": "applied",
        "intensity": req.level,
        "description": INTENSITY_PRESETS[req.level],
        "vars_set": len(applied),
        "note": "Restart load generators for changes to take effect. Use POST /generators/orm/stop then /start.",
    }


# ── Health ───────────────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    return {"status": "ok", "service": "control-plane"}
