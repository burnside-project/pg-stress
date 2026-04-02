from datetime import datetime, timezone

import asyncpg

# Exact same query as internal/sampler/database.go lines 11-32
DATABASE_QUERY = """
SELECT
    d.datname,
    d.numbackends,
    d.xact_commit,
    d.xact_rollback,
    d.blks_read,
    d.blks_hit,
    d.tup_returned,
    d.tup_fetched,
    d.tup_inserted,
    d.tup_updated,
    d.tup_deleted,
    d.conflicts,
    d.temp_files,
    d.temp_bytes,
    d.deadlocks,
    d.stats_reset,
    pg_database_size(d.datname) as database_size_bytes
FROM pg_stat_database d
WHERE d.datname = current_database()
"""


class PGClient:
    """Async PostgreSQL client for ground truth queries."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=2)

    async def close(self):
        if self._pool:
            await self._pool.close()

    async def snapshot_database(self) -> dict:
        """Take a snapshot of pg_stat_database for current database."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(DATABASE_QUERY)
            return {
                "timestamp": datetime.now(timezone.utc),
                "datname": row["datname"],
                "numbackends": row["numbackends"],
                "xact_commit": row["xact_commit"],
                "xact_rollback": row["xact_rollback"],
                "blks_read": row["blks_read"],
                "blks_hit": row["blks_hit"],
                "tup_returned": row["tup_returned"],
                "tup_fetched": row["tup_fetched"],
                "tup_inserted": row["tup_inserted"],
                "tup_updated": row["tup_updated"],
                "tup_deleted": row["tup_deleted"],
                "conflicts": row["conflicts"],
                "temp_files": row["temp_files"],
                "temp_bytes": row["temp_bytes"],
                "deadlocks": row["deadlocks"],
                "stats_reset": row["stats_reset"],
                "database_size_bytes": row["database_size_bytes"],
            }