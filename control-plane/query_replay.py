"""Production query replay engine for pg-stress.

Imports queries from pg_stat_statements exports or SQL files,
then replays them against the test database at configurable
concurrency and frequency.

Tracks per-query timing, errors, and row counts for comparison
across test runs.
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("query-replay")

DB_PATH = Path("/data/queries.db")

PG_HOST = os.environ.get("PG_HOST", "postgres")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "postgres")
PG_DATABASE = os.environ.get("PG_DATABASE", "testdb")


# ── SQLite store for imported queries ────────────────────────────────────


def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS query_sets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source TEXT,
            imported_at TEXT NOT NULL,
            query_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_set_id TEXT NOT NULL,
            query TEXT NOT NULL,
            name TEXT,
            source_calls INTEGER DEFAULT 0,
            source_mean_ms REAL DEFAULT 0,
            source_rows INTEGER DEFAULT 0,
            weight INTEGER DEFAULT 1,
            FOREIGN KEY (query_set_id) REFERENCES query_sets(id)
        );

        CREATE TABLE IF NOT EXISTS replay_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_run_id TEXT,
            query_id INTEGER,
            query_text TEXT,
            query_name TEXT,
            executions INTEGER DEFAULT 0,
            total_ms REAL DEFAULT 0,
            avg_ms REAL DEFAULT 0,
            min_ms REAL DEFAULT 0,
            max_ms REAL DEFAULT 0,
            total_rows INTEGER DEFAULT 0,
            errors INTEGER DEFAULT 0,
            recorded_at TEXT,
            FOREIGN KEY (query_id) REFERENCES queries(id)
        );
    """)
    conn.commit()
    return conn


_conn = _init_db()
_lock = threading.Lock()


# ── Query import ─────────────────────────────────────────────────────────


def import_pg_stat_statements(name: str, data: list[dict]) -> dict:
    """Import queries from a pg_stat_statements JSON export.

    Expected format: [{"query": "SELECT ...", "calls": 1000, "mean_exec_time": 12.5, "rows": 5000}, ...]
    """
    set_id = str(uuid.uuid4())[:8]
    count = 0

    with _lock:
        _conn.execute(
            "INSERT INTO query_sets (id, name, source, imported_at, query_count) VALUES (?,?,?,?,?)",
            (set_id, name, "pg_stat_statements", datetime.now(timezone.utc).isoformat(), 0),
        )

        for row in data:
            q = row.get("query", "").strip()
            if not q or q.startswith("--"):
                continue
            # Skip utility statements.
            upper = q.upper()
            if any(upper.startswith(kw) for kw in ["SET ", "RESET ", "BEGIN", "COMMIT", "ROLLBACK", "COPY ", "VACUUM", "ANALYZE"]):
                continue

            # Replace $1, $2 placeholders with NULLs for replay.
            replay_q = re.sub(r'\$\d+', 'NULL', q)

            _conn.execute(
                "INSERT INTO queries (query_set_id, query, name, source_calls, source_mean_ms, source_rows, weight) VALUES (?,?,?,?,?,?,?)",
                (set_id, replay_q,
                 row.get("name", f"query_{count + 1}"),
                 row.get("calls", 0),
                 row.get("mean_exec_time", row.get("mean_time", 0)),
                 row.get("rows", 0),
                 max(1, int(row.get("calls", 1) / max(1, sum(r.get("calls", 1) for r in data)) * 100))),
            )
            count += 1

        _conn.execute("UPDATE query_sets SET query_count = ? WHERE id = ?", (count, set_id))
        _conn.commit()

    log.info("Imported %d queries as set '%s' (id=%s)", count, name, set_id)
    return {"id": set_id, "name": name, "query_count": count}


def import_sql_files(name: str, sql_dir: str) -> dict:
    """Import queries from .sql files in a directory."""
    set_id = str(uuid.uuid4())[:8]
    count = 0
    path = Path(sql_dir)

    with _lock:
        _conn.execute(
            "INSERT INTO query_sets (id, name, source, imported_at, query_count) VALUES (?,?,?,?,?)",
            (set_id, name, f"sql_files:{sql_dir}", datetime.now(timezone.utc).isoformat(), 0),
        )

        for f in sorted(path.glob("*.sql")):
            content = f.read_text().strip()
            # Split on semicolons for multi-statement files.
            for stmt in content.split(";"):
                # Strip comment lines, then check if anything remains.
                lines = [l for l in stmt.strip().splitlines() if not l.strip().startswith("--")]
                stmt = "\n".join(lines).strip()
                if not stmt:
                    continue
                _conn.execute(
                    "INSERT INTO queries (query_set_id, query, name, weight) VALUES (?,?,?,?)",
                    (set_id, stmt, f.stem, 1),
                )
                count += 1

        _conn.execute("UPDATE query_sets SET query_count = ? WHERE id = ?", (count, set_id))
        _conn.commit()

    log.info("Imported %d queries from %s as set '%s'", count, sql_dir, set_id)
    return {"id": set_id, "name": name, "query_count": count}


def import_sql_text(name: str, queries: list[dict]) -> dict:
    """Import queries from a list of {name, query, weight} dicts."""
    set_id = str(uuid.uuid4())[:8]
    count = 0

    with _lock:
        _conn.execute(
            "INSERT INTO query_sets (id, name, source, imported_at, query_count) VALUES (?,?,?,?,?)",
            (set_id, name, "manual", datetime.now(timezone.utc).isoformat(), 0),
        )

        for q in queries:
            text = q.get("query", "").strip()
            if not text:
                continue
            _conn.execute(
                "INSERT INTO queries (query_set_id, query, name, weight) VALUES (?,?,?,?)",
                (set_id, text, q.get("name", f"query_{count + 1}"), q.get("weight", 1)),
            )
            count += 1

        _conn.execute("UPDATE query_sets SET query_count = ? WHERE id = ?", (count, set_id))
        _conn.commit()

    return {"id": set_id, "name": name, "query_count": count}


# ── Query listing ────────────────────────────────────────────────────────


def list_query_sets() -> list[dict]:
    with _lock:
        rows = _conn.execute("SELECT id, name, source, imported_at, query_count FROM query_sets ORDER BY imported_at DESC").fetchall()
    return [{"id": r[0], "name": r[1], "source": r[2], "imported_at": r[3], "query_count": r[4]} for r in rows]


def get_queries(set_id: str) -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT id, query, name, source_calls, source_mean_ms, source_rows, weight FROM queries WHERE query_set_id = ? ORDER BY source_calls DESC",
            (set_id,),
        ).fetchall()
    return [{"id": r[0], "query": r[1], "name": r[2], "source_calls": r[3],
             "source_mean_ms": r[4], "source_rows": r[5], "weight": r[6]} for r in rows]


def delete_query_set(set_id: str):
    with _lock:
        _conn.execute("DELETE FROM queries WHERE query_set_id = ?", (set_id,))
        _conn.execute("DELETE FROM query_sets WHERE id = ?", (set_id,))
        _conn.commit()


# ── Replay engine ────────────────────────────────────────────────────────


class ReplayEngine:
    """Replays imported queries against the test database."""

    def __init__(self):
        self.running = False
        self.stop_event = threading.Event()
        self.stats = {}  # query_id → {executions, total_ms, min_ms, max_ms, rows, errors}
        self.total_executions = 0
        self.total_errors = 0
        self.start_time = 0
        self.config = {}
        self._threads = []

    def start(self, query_set_id: str, concurrency: int = 10,
              duration_s: int = 0, test_run_id: str = "") -> dict:
        if self.running:
            return {"error": "Replay already running"}

        queries = get_queries(query_set_id)
        if not queries:
            return {"error": f"No queries in set {query_set_id}"}

        # Build weighted query list.
        weighted = []
        for q in queries:
            weighted.extend([q] * max(1, q["weight"]))

        self.running = True
        self.stop_event.clear()
        self.stats = {q["id"]: {"name": q["name"], "query": q["query"][:100],
                                "executions": 0, "total_ms": 0, "min_ms": 999999,
                                "max_ms": 0, "rows": 0, "errors": 0} for q in queries}
        self.total_executions = 0
        self.total_errors = 0
        self.start_time = time.time()
        self.config = {
            "query_set_id": query_set_id, "concurrency": concurrency,
            "duration_s": duration_s, "test_run_id": test_run_id,
            "query_count": len(queries),
        }

        import random

        def worker(worker_id):
            try:
                conn = psycopg2.connect(
                    host=PG_HOST, port=PG_PORT, user=PG_USER,
                    password=PG_PASSWORD, dbname=PG_DATABASE,
                )
                conn.autocommit = True
            except Exception as e:
                log.error("Worker %d connection failed: %s", worker_id, e)
                return

            while not self.stop_event.is_set():
                if duration_s > 0 and (time.time() - self.start_time) > duration_s:
                    break

                q = random.choice(weighted)
                qid = q["id"]
                try:
                    start = time.time()
                    with conn.cursor() as cur:
                        cur.execute(q["query"])
                        rows = cur.rowcount or 0
                    elapsed_ms = (time.time() - start) * 1000

                    s = self.stats[qid]
                    s["executions"] += 1
                    s["total_ms"] += elapsed_ms
                    s["min_ms"] = min(s["min_ms"], elapsed_ms)
                    s["max_ms"] = max(s["max_ms"], elapsed_ms)
                    s["rows"] += rows
                    self.total_executions += 1
                except Exception:
                    self.stats[qid]["errors"] += 1
                    self.total_errors += 1

                # Small pause to avoid hammering.
                time.sleep(random.uniform(0.01, 0.05))

            try:
                conn.close()
            except Exception:
                pass

        self._threads = []
        for i in range(concurrency):
            t = threading.Thread(target=worker, args=(i,), daemon=True)
            t.start()
            self._threads.append(t)

        log.info("Replay started: %d queries, %d workers, duration=%ds",
                 len(queries), concurrency, duration_s)
        return {"status": "started", "queries": len(queries), "concurrency": concurrency}

    def stop(self) -> dict:
        if not self.running:
            return {"status": "not_running"}

        self.stop_event.set()
        for t in self._threads:
            t.join(timeout=5)
        self.running = False

        elapsed = time.time() - self.start_time

        # Save results to SQLite.
        test_run_id = self.config.get("test_run_id", "")
        with _lock:
            for qid, s in self.stats.items():
                avg_ms = s["total_ms"] / max(1, s["executions"])
                _conn.execute(
                    "INSERT INTO replay_results (test_run_id, query_id, query_text, query_name, executions, total_ms, avg_ms, min_ms, max_ms, total_rows, errors, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (test_run_id, qid, s["query"], s["name"], s["executions"],
                     round(s["total_ms"], 1), round(avg_ms, 2),
                     round(s["min_ms"], 2) if s["min_ms"] < 999999 else 0,
                     round(s["max_ms"], 2), s["rows"], s["errors"],
                     datetime.now(timezone.utc).isoformat()),
                )
            _conn.commit()

        log.info("Replay stopped: %d executions, %d errors, %.0fs elapsed",
                 self.total_executions, self.total_errors, elapsed)
        return {
            "status": "stopped",
            "elapsed_s": int(elapsed),
            "total_executions": self.total_executions,
            "total_errors": self.total_errors,
            "qps": round(self.total_executions / max(1, elapsed), 1),
        }

    def snapshot(self) -> dict:
        elapsed = time.time() - self.start_time if self.running else 0
        results = []
        for qid, s in self.stats.items():
            avg = s["total_ms"] / max(1, s["executions"])
            results.append({
                "query_id": qid, "name": s["name"], "query": s["query"],
                "executions": s["executions"], "avg_ms": round(avg, 2),
                "min_ms": round(s["min_ms"], 2) if s["min_ms"] < 999999 else 0,
                "max_ms": round(s["max_ms"], 2), "rows": s["rows"], "errors": s["errors"],
            })
        return {
            "running": self.running,
            "elapsed_s": int(elapsed),
            "total_executions": self.total_executions,
            "total_errors": self.total_errors,
            "qps": round(self.total_executions / max(1, elapsed), 1) if elapsed > 0 else 0,
            "config": self.config,
            "queries": sorted(results, key=lambda x: x["executions"], reverse=True),
        }


def get_replay_results(test_run_id: str) -> list[dict]:
    """Get saved replay results for a test run."""
    with _lock:
        rows = _conn.execute(
            "SELECT query_name, query_text, executions, avg_ms, min_ms, max_ms, total_rows, errors FROM replay_results WHERE test_run_id = ? ORDER BY executions DESC",
            (test_run_id,),
        ).fetchall()
    return [{"name": r[0], "query": r[1], "executions": r[2], "avg_ms": r[3],
             "min_ms": r[4], "max_ms": r[5], "rows": r[6], "errors": r[7]} for r in rows]


# Singleton engine.
engine = ReplayEngine()
