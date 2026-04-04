from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import asyncpg

from app.config import Settings
from app.metrics_store import MetricsStore
from app.models import MetricsSample

log = logging.getLogger("pg_poller")

# Tables to monitor sizes for.
MONITORED_TABLES = [
    "search_log", "audit_log", "price_history", "cart_items", "reviews",
    "orders", "order_items", "payments", "shipments", "sessions",
    "customers", "products", "product_variants", "inventory",
]


class PGPoller:
    """Polls pg_stat_* views and stores samples in the metrics store."""

    def __init__(self, pool: asyncpg.Pool, store: MetricsStore, settings: Settings):
        self.pool = pool
        self.store = store
        self.settings = settings
        self._prev: MetricsSample | None = None

    async def poll_once(self) -> MetricsSample:
        now = datetime.now(timezone.utc)
        sample = MetricsSample(timestamp=now)

        async with self.pool.acquire() as conn:
            # 1. Database-level stats.
            row = await conn.fetchrow(
                """SELECT xact_commit, xact_rollback,
                          tup_inserted, tup_updated, tup_deleted,
                          tup_returned, tup_fetched,
                          blks_read, blks_hit,
                          temp_files, temp_bytes, deadlocks
                   FROM pg_stat_database
                   WHERE datname = current_database()"""
            )
            if row:
                sample.xact_commit = row["xact_commit"] or 0
                sample.xact_rollback = row["xact_rollback"] or 0
                sample.tup_inserted = row["tup_inserted"] or 0
                sample.tup_updated = row["tup_updated"] or 0
                sample.tup_deleted = row["tup_deleted"] or 0
                sample.tup_returned = row["tup_returned"] or 0
                sample.tup_fetched = row["tup_fetched"] or 0
                sample.blks_read = row["blks_read"] or 0
                sample.blks_hit = row["blks_hit"] or 0
                sample.temp_files = row["temp_files"] or 0
                sample.temp_bytes = row["temp_bytes"] or 0
                sample.deadlocks = row["deadlocks"] or 0

            # 2. Connections by state.
            rows = await conn.fetch(
                """SELECT state, count(*) AS cnt
                   FROM pg_stat_activity
                   WHERE datname = current_database()
                   GROUP BY state"""
            )
            for r in rows:
                state = r["state"] or "unknown"
                cnt = r["cnt"]
                sample.total_connections += cnt
                if state == "active":
                    sample.active_connections = cnt
                elif state == "idle":
                    sample.idle_connections = cnt
                elif state == "idle in transaction":
                    sample.idle_in_transaction = cnt

            # 3. Database size.
            size = await conn.fetchval("SELECT pg_database_size(current_database())")
            sample.database_size_bytes = size or 0

            # 4. Locks.
            lock_row = await conn.fetchrow(
                """SELECT count(*) AS total,
                          count(*) FILTER (WHERE NOT granted) AS waiting
                   FROM pg_locks
                   WHERE database = (SELECT oid FROM pg_database WHERE datname = current_database())"""
            )
            if lock_row:
                sample.lock_count = lock_row["total"]
                sample.lock_waiting = lock_row["waiting"]

            # 5. Table sizes.
            table_rows = await conn.fetch(
                """SELECT relname,
                          n_live_tup::bigint AS live,
                          n_dead_tup::bigint AS dead,
                          pg_total_relation_size(relid) AS size_bytes
                   FROM pg_stat_user_tables
                   WHERE relname = ANY($1)""",
                MONITORED_TABLES,
            )
            for r in table_rows:
                name = r["relname"]
                sample.table_rows[name] = r["live"]
                sample.table_dead_tuples[name] = r["dead"]
                sample.table_size_bytes[name] = r["size_bytes"]

        # Compute rates from previous sample.
        if self._prev:
            elapsed = (now - self._prev.timestamp).total_seconds()
            if elapsed > 0:
                sample.txn_per_sec = (
                    (sample.xact_commit - self._prev.xact_commit)
                    + (sample.xact_rollback - self._prev.xact_rollback)
                ) / elapsed
                sample.tup_inserted_per_sec = (sample.tup_inserted - self._prev.tup_inserted) / elapsed
                sample.tup_updated_per_sec = (sample.tup_updated - self._prev.tup_updated) / elapsed
                sample.tup_deleted_per_sec = (sample.tup_deleted - self._prev.tup_deleted) / elapsed
                sample.blks_read_per_sec = (sample.blks_read - self._prev.blks_read) / elapsed
                sample.blks_hit_per_sec = (sample.blks_hit - self._prev.blks_hit) / elapsed

                total_blks = sample.blks_read + sample.blks_hit
                prev_total = self._prev.blks_read + self._prev.blks_hit
                delta_total = total_blks - prev_total
                delta_hit = sample.blks_hit - self._prev.blks_hit
                if delta_total > 0:
                    sample.cache_hit_ratio = delta_hit / delta_total
                elif total_blks > 0:
                    sample.cache_hit_ratio = sample.blks_hit / total_blks
                else:
                    sample.cache_hit_ratio = 1.0

        self._prev = sample
        self.store.add(sample)
        return sample

    async def run(self) -> None:
        log.info("pg_poller started (interval=%ds)", self.settings.poll_interval_seconds)
        while True:
            try:
                await self.poll_once()
            except Exception as e:
                log.error("poll error: %s", e)
            await asyncio.sleep(self.settings.poll_interval_seconds)
