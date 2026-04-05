"""Persistent metrics store backed by SQLite.

Stores time-series samples and safety events in a SQLite database
so metrics survive container restarts. Falls back gracefully if
the database is unavailable.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models import MetricsSample, SafetyEvent

log = logging.getLogger("metrics-store")

DB_PATH = Path("/data/metrics.db")


class MetricsStore:
    """SQLite-backed time-series store for dashboard metrics."""

    def __init__(self, max_samples: int = 8640):
        self.max_samples = max_samples
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_tables()
        log.info("metrics store: sqlite at %s", DB_PATH)

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(timestamp);

            CREATE TABLE IF NOT EXISTS safety_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON safety_events(timestamp);
        """)
        self._conn.commit()

    def add(self, sample: MetricsSample) -> None:
        self._conn.execute(
            "INSERT INTO samples (timestamp, data) VALUES (?, ?)",
            (sample.timestamp.isoformat(), json.dumps(sample.to_dict())),
        )
        self._conn.commit()
        # Prune old samples.
        count = self._conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        if count > self.max_samples:
            self._conn.execute(
                "DELETE FROM samples WHERE id IN (SELECT id FROM samples ORDER BY id ASC LIMIT ?)",
                (count - self.max_samples,),
            )
            self._conn.commit()

    def add_safety_event(self, event: SafetyEvent) -> None:
        data = {
            "timestamp": event.timestamp.isoformat(),
            "table": event.table,
            "action": event.action,
            "rows_before": event.rows_before,
            "rows_after": event.rows_after,
            "limit": event.limit,
            "detail": event.detail,
        }
        self._conn.execute(
            "INSERT INTO safety_events (timestamp, data) VALUES (?, ?)",
            (event.timestamp.isoformat(), json.dumps(data)),
        )
        self._conn.commit()

    @property
    def samples(self):
        """Compatibility: return list-like object with len() support."""
        return _SamplesProxy(self._conn)

    def query(
        self,
        from_ts: Optional[datetime] = None,
        to_ts: Optional[datetime] = None,
    ) -> list[MetricsSample]:
        sql = "SELECT data FROM samples"
        params = []
        clauses = []
        if from_ts:
            clauses.append("timestamp >= ?")
            params.append(from_ts.isoformat())
        if to_ts:
            clauses.append("timestamp <= ?")
            params.append(to_ts.isoformat())
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp ASC"

        rows = self._conn.execute(sql, params).fetchall()
        result = []
        for (data_json,) in rows:
            d = json.loads(data_json)
            s = MetricsSample()
            s.timestamp = datetime.fromisoformat(d["timestamp"])
            for k, v in d.items():
                if k != "timestamp" and hasattr(s, k):
                    setattr(s, k, v)
            result.append(s)
        return result

    def latest(self) -> Optional[MetricsSample]:
        row = self._conn.execute(
            "SELECT data FROM samples ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        d = json.loads(row[0])
        s = MetricsSample(timestamp=datetime.fromisoformat(d["timestamp"]))
        for k, v in d.items():
            if k != "timestamp" and hasattr(s, k):
                setattr(s, k, v)
        return s

    def recent_safety_events(self, limit: int = 50) -> list[SafetyEvent]:
        rows = self._conn.execute(
            "SELECT data FROM safety_events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        events = []
        for (data_json,) in rows:
            d = json.loads(data_json)
            events.append(SafetyEvent(
                timestamp=datetime.fromisoformat(d["timestamp"]),
                table=d.get("table", ""),
                action=d.get("action", ""),
                rows_before=d.get("rows_before", 0),
                rows_after=d.get("rows_after", 0),
                limit=d.get("limit", 0),
                detail=d.get("detail", ""),
            ))
        return events

    def clear(self):
        """Clear all samples (used by /api/reset)."""
        self._conn.execute("DELETE FROM samples")
        self._conn.execute("DELETE FROM safety_events")
        self._conn.commit()


class _SamplesProxy:
    """Proxy that makes store.samples work with len() and clear()."""

    def __init__(self, conn):
        self._conn = conn

    def __len__(self):
        return self._conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]

    def clear(self):
        self._conn.execute("DELETE FROM samples")
        self._conn.execute("DELETE FROM safety_events")
        self._conn.commit()
