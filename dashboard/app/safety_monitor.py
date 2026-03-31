from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import asyncpg

from app.config import Settings
from app.metrics_store import MetricsStore
from app.models import SafetyEvent

log = logging.getLogger("safety_monitor")


class SafetyMonitor:
    """Watches append-only table sizes and prunes when limits are exceeded."""

    def __init__(self, pool: asyncpg.Pool, store: MetricsStore, settings: Settings):
        self.pool = pool
        self.store = store
        self.settings = settings

    async def check_and_prune(self) -> None:
        limits = self.settings.table_limits

        async with self.pool.acquire() as conn:
            # Check database size.
            db_size = await conn.fetchval("SELECT pg_database_size(current_database())")
            if db_size and db_size > self.settings.max_database_size_bytes:
                log.warning(
                    "database size %d bytes exceeds limit %d",
                    db_size,
                    self.settings.max_database_size_bytes,
                )
                self.store.add_safety_event(SafetyEvent(
                    timestamp=datetime.now(timezone.utc),
                    table="database",
                    action="warning",
                    rows_before=0,
                    rows_after=0,
                    limit=self.settings.max_database_size_bytes,
                    detail=f"Database size {db_size:,} bytes exceeds limit {self.settings.max_database_size_bytes:,}",
                ))

            # Check each monitored table.
            for table, limit in limits.items():
                row = await conn.fetchrow(
                    "SELECT n_live_tup::bigint AS estimate FROM pg_stat_user_tables WHERE relname = $1",
                    table,
                )
                if not row:
                    continue

                estimate = row["estimate"]
                if estimate <= limit:
                    continue

                log.warning(
                    "table %s has ~%d rows (limit: %d), pruning...",
                    table, estimate, limit,
                )

                target = int(limit * self.settings.prune_to_pct / 100)
                rows_to_delete = estimate - target

                total_deleted = 0
                while rows_to_delete > 0:
                    batch = min(rows_to_delete, self.settings.prune_batch_size)
                    result = await conn.execute(
                        f"DELETE FROM {table} WHERE ctid IN "
                        f"(SELECT ctid FROM {table} ORDER BY created_at ASC LIMIT $1)",
                        batch,
                    )
                    deleted = int(result.split()[-1]) if result else 0
                    total_deleted += deleted
                    rows_to_delete -= batch

                    if deleted == 0:
                        break

                log.info("pruned %d rows from %s (was ~%d, target %d)", total_deleted, table, estimate, target)

                self.store.add_safety_event(SafetyEvent(
                    timestamp=datetime.now(timezone.utc),
                    table=table,
                    action="prune",
                    rows_before=estimate,
                    rows_after=estimate - total_deleted,
                    limit=limit,
                    detail=f"Pruned {total_deleted:,} oldest rows",
                ))

    async def run(self) -> None:
        log.info(
            "safety_monitor started (interval=%ds, tables=%s)",
            self.settings.safety_check_interval_seconds,
            list(self.settings.table_limits.keys()),
        )
        while True:
            try:
                await self.check_and_prune()
            except Exception as e:
                log.error("safety check error: %s", e)
            await asyncio.sleep(self.settings.safety_check_interval_seconds)
