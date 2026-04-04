from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MetricsSample:
    timestamp: datetime

    # pg_stat_database counters (cumulative).
    xact_commit: int = 0
    xact_rollback: int = 0
    tup_inserted: int = 0
    tup_updated: int = 0
    tup_deleted: int = 0
    tup_returned: int = 0
    tup_fetched: int = 0
    blks_read: int = 0
    blks_hit: int = 0
    temp_files: int = 0
    temp_bytes: int = 0
    deadlocks: int = 0

    # Computed rates (per second, derived from deltas).
    txn_per_sec: float = 0.0
    tup_inserted_per_sec: float = 0.0
    tup_updated_per_sec: float = 0.0
    tup_deleted_per_sec: float = 0.0
    blks_read_per_sec: float = 0.0
    blks_hit_per_sec: float = 0.0
    cache_hit_ratio: float = 0.0

    # pg_stat_activity.
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    idle_in_transaction: int = 0

    # Database size.
    database_size_bytes: int = 0

    # Lock counts.
    lock_count: int = 0
    lock_waiting: int = 0

    # Table sizes (rows).
    table_rows: dict = field(default_factory=dict)
    table_dead_tuples: dict = field(default_factory=dict)
    table_size_bytes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "txn_per_sec": round(self.txn_per_sec, 1),
            "tup_inserted_per_sec": round(self.tup_inserted_per_sec, 1),
            "tup_updated_per_sec": round(self.tup_updated_per_sec, 1),
            "tup_deleted_per_sec": round(self.tup_deleted_per_sec, 1),
            "blks_read_per_sec": round(self.blks_read_per_sec, 1),
            "blks_hit_per_sec": round(self.blks_hit_per_sec, 1),
            "cache_hit_ratio": round(self.cache_hit_ratio, 4),
            "total_connections": self.total_connections,
            "active_connections": self.active_connections,
            "idle_connections": self.idle_connections,
            "idle_in_transaction": self.idle_in_transaction,
            "database_size_bytes": self.database_size_bytes,
            "lock_count": self.lock_count,
            "lock_waiting": self.lock_waiting,
            "deadlocks": self.deadlocks,
            "temp_files": self.temp_files,
            "table_rows": self.table_rows,
            "table_dead_tuples": self.table_dead_tuples,
            "table_size_bytes": self.table_size_bytes,
        }


@dataclass
class SafetyEvent:
    timestamp: datetime
    table: str
    action: str  # "prune" or "warning"
    rows_before: int
    rows_after: int
    limit: int
    detail: str = ""
