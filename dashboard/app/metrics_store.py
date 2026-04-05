"""Persistent metrics store backed by SQLite.

Stores baselines, test runs, phases, events, and time-series samples
in a SQLite database. DuckDB reads this for analytics.

Schema:
  baselines    — imported production dumps (the known starting state)
  test_runs    — named test executions, each starting from a baseline
  events       — inject, bulk update, intensity change within a test
  samples      — time-series metrics (TPS, cache, connections per 10s)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models import MetricsSample, SafetyEvent

log = logging.getLogger("metrics-store")

DB_PATH = Path("/data/metrics.db")


class MetricsStore:
    """SQLite-backed store for test runs and dashboard metrics."""

    def __init__(self, max_samples: int = 86400):
        self.max_samples = max_samples
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_tables()
        log.info("metrics store: sqlite at %s", DB_PATH)

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS baselines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dump_path TEXT,
                created_at TEXT NOT NULL,
                tables_json TEXT,
                total_rows INTEGER DEFAULT 0,
                db_size TEXT
            );

            CREATE TABLE IF NOT EXISTS test_runs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                baseline_id TEXT,
                intensity TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'running',
                started_at TEXT NOT NULL,
                stopped_at TEXT,
                db_before_json TEXT,
                db_after_json TEXT,
                config_json TEXT,
                FOREIGN KEY (baseline_id) REFERENCES baselines(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                detail TEXT,
                FOREIGN KEY (test_run_id) REFERENCES test_runs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_events_run ON events(test_run_id);

            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_run_id TEXT,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(timestamp);
            CREATE INDEX IF NOT EXISTS idx_samples_run ON samples(test_run_id);

            CREATE TABLE IF NOT EXISTS safety_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ── Active test run ──────────────────────────────────────────────

    def active_test_run(self) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT id, name, baseline_id, intensity, status, started_at, db_before_json FROM test_runs WHERE status='running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "baseline_id": row[2],
            "intensity": row[3], "status": row[4], "started_at": row[5],
            "db_before": json.loads(row[6]) if row[6] else None,
        }

    def active_test_run_id(self) -> Optional[str]:
        run = self.active_test_run()
        return run["id"] if run else None

    # ── Baselines ────────────────────────────────────────────────────

    def save_baseline(self, name: str, dump_path: str, tables: dict, total_rows: int, db_size: str) -> str:
        bid = str(uuid.uuid4())[:8]
        self._conn.execute(
            "INSERT INTO baselines (id, name, dump_path, created_at, tables_json, total_rows, db_size) VALUES (?,?,?,?,?,?,?)",
            (bid, name, dump_path, datetime.now(timezone.utc).isoformat(),
             json.dumps(tables), total_rows, db_size),
        )
        self._conn.commit()
        return bid

    def list_baselines(self) -> list[dict]:
        rows = self._conn.execute("SELECT id, name, dump_path, created_at, total_rows, db_size FROM baselines ORDER BY created_at DESC").fetchall()
        return [{"id": r[0], "name": r[1], "dump_path": r[2], "created_at": r[3], "total_rows": r[4], "db_size": r[5]} for r in rows]

    def get_baseline(self, bid: str) -> Optional[dict]:
        row = self._conn.execute("SELECT id, name, dump_path, created_at, tables_json, total_rows, db_size FROM baselines WHERE id=?", (bid,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "dump_path": row[2], "created_at": row[3],
                "tables": json.loads(row[4]) if row[4] else {}, "total_rows": row[5], "db_size": row[6]}

    # ── Test runs ────────────────────────────────────────────────────

    def start_test_run(self, name: str, baseline_id: str, intensity: str, db_before: dict, config: dict = None) -> str:
        # Stop any running test first.
        self._conn.execute("UPDATE test_runs SET status='stopped', stopped_at=? WHERE status='running'",
                           (datetime.now(timezone.utc).isoformat(),))
        rid = str(uuid.uuid4())[:8]
        self._conn.execute(
            "INSERT INTO test_runs (id, name, baseline_id, intensity, status, started_at, db_before_json, config_json) VALUES (?,?,?,?,?,?,?,?)",
            (rid, name, baseline_id, intensity, "running",
             datetime.now(timezone.utc).isoformat(),
             json.dumps(db_before), json.dumps(config) if config else None),
        )
        self.add_event(rid, "test_started", f"Started '{name}' at {intensity} intensity")
        self._conn.commit()
        return rid

    def stop_test_run(self, run_id: str, db_after: dict) -> None:
        self._conn.execute(
            "UPDATE test_runs SET status='completed', stopped_at=?, db_after_json=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), json.dumps(db_after), run_id),
        )
        self.add_event(run_id, "test_stopped", "Test completed")
        self._conn.commit()

    def list_test_runs(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, baseline_id, intensity, status, started_at, stopped_at, db_before_json, db_after_json FROM test_runs ORDER BY started_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            # Count samples for this run.
            cnt = self._conn.execute("SELECT COUNT(*) FROM samples WHERE test_run_id=?", (r[0],)).fetchone()[0]
            result.append({
                "id": r[0], "name": r[1], "baseline_id": r[2], "intensity": r[3],
                "status": r[4], "started_at": r[5], "stopped_at": r[6],
                "db_before": json.loads(r[7]) if r[7] else None,
                "db_after": json.loads(r[8]) if r[8] else None,
                "sample_count": cnt,
            })
        return result

    def get_test_run(self, run_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT id, name, baseline_id, intensity, status, started_at, stopped_at, db_before_json, db_after_json, config_json FROM test_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        events = self._conn.execute("SELECT timestamp, type, detail FROM events WHERE test_run_id=? ORDER BY timestamp", (run_id,)).fetchall()
        return {
            "id": row[0], "name": row[1], "baseline_id": row[2], "intensity": row[3],
            "status": row[4], "started_at": row[5], "stopped_at": row[6],
            "db_before": json.loads(row[7]) if row[7] else None,
            "db_after": json.loads(row[8]) if row[8] else None,
            "config": json.loads(row[9]) if row[9] else None,
            "events": [{"timestamp": e[0], "type": e[1], "detail": e[2]} for e in events],
        }

    # ── Events ───────────────────────────────────────────────────────

    def add_event(self, test_run_id: str, event_type: str, detail: str) -> None:
        self._conn.execute(
            "INSERT INTO events (test_run_id, timestamp, type, detail) VALUES (?,?,?,?)",
            (test_run_id, datetime.now(timezone.utc).isoformat(), event_type, detail),
        )
        self._conn.commit()

    # ── Samples (metrics time-series) ────────────────────────────────

    def add(self, sample: MetricsSample) -> None:
        run_id = self.active_test_run_id()
        self._conn.execute(
            "INSERT INTO samples (test_run_id, timestamp, data) VALUES (?,?,?)",
            (run_id, sample.timestamp.isoformat(), json.dumps(sample.to_dict())),
        )
        self._conn.commit()

    def add_safety_event(self, event: SafetyEvent) -> None:
        data = {
            "timestamp": event.timestamp.isoformat(), "table": event.table,
            "action": event.action, "rows_before": event.rows_before,
            "rows_after": event.rows_after, "limit": event.limit, "detail": event.detail,
        }
        self._conn.execute(
            "INSERT INTO safety_events (timestamp, data) VALUES (?,?)",
            (event.timestamp.isoformat(), json.dumps(data)),
        )
        self._conn.commit()

    @property
    def samples(self):
        return _SamplesProxy(self._conn)

    def query(self, from_ts=None, to_ts=None, test_run_id=None) -> list[MetricsSample]:
        sql = "SELECT data FROM samples"
        params = []
        clauses = []

        # Default to active test run.
        rid = test_run_id or self.active_test_run_id()
        if rid:
            clauses.append("test_run_id = ?")
            params.append(rid)

        if from_ts:
            clauses.append("timestamp >= ?")
            params.append(from_ts.isoformat() if hasattr(from_ts, 'isoformat') else from_ts)
        if to_ts:
            clauses.append("timestamp <= ?")
            params.append(to_ts.isoformat() if hasattr(to_ts, 'isoformat') else to_ts)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp ASC"

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_sample(r[0]) for r in rows]

    def latest(self) -> Optional[MetricsSample]:
        row = self._conn.execute("SELECT data FROM samples ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return self._row_to_sample(row[0])

    def _row_to_sample(self, data_json: str) -> MetricsSample:
        d = json.loads(data_json)
        s = MetricsSample(timestamp=datetime.fromisoformat(d["timestamp"]))
        for k, v in d.items():
            if k != "timestamp" and hasattr(s, k):
                setattr(s, k, v)
        return s

    def recent_safety_events(self, limit: int = 50) -> list[SafetyEvent]:
        rows = self._conn.execute("SELECT data FROM safety_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        events = []
        for (data_json,) in rows:
            d = json.loads(data_json)
            events.append(SafetyEvent(
                timestamp=datetime.fromisoformat(d["timestamp"]),
                table=d.get("table", ""), action=d.get("action", ""),
                rows_before=d.get("rows_before", 0), rows_after=d.get("rows_after", 0),
                limit=d.get("limit", 0), detail=d.get("detail", ""),
            ))
        return events

    def clear(self):
        self._conn.execute("DELETE FROM samples")
        self._conn.execute("DELETE FROM safety_events")
        self._conn.execute("DELETE FROM events")
        self._conn.commit()


class _SamplesProxy:
    def __init__(self, conn):
        self._conn = conn
    def __len__(self):
        return self._conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    def clear(self):
        self._conn.execute("DELETE FROM samples")
        self._conn.execute("DELETE FROM safety_events")
        self._conn.commit()
