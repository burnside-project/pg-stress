"""Collect PostgreSQL diagnostic data for AI analysis.

Gathers pg_stat_statements, pg_stat_database, table stats, connection info,
lock state, and PostgreSQL configuration into a structured dict that can be
serialized and sent to Claude for analysis.
"""

import json
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras


def env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def connect():
    return psycopg2.connect(
        host=env("PG_HOST", "localhost"),
        port=int(env("PG_PORT", "5434")),
        user=env("PG_USER", "postgres"),
        password=env("PG_PASSWORD", "postgres"),
        dbname=env("PG_DATABASE", "testdb"),
    )


def query(conn, sql: str) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        # Convert to plain dicts with JSON-safe values.
        result = []
        for row in rows:
            d = {}
            for k, v in dict(row).items():
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
                elif hasattr(v, "__float__"):
                    d[k] = float(v)
                else:
                    d[k] = v
            result.append(d)
        return result


def collect_all() -> dict:
    """Collect all diagnostic data from PostgreSQL."""
    conn = connect()
    try:
        data = {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "pg_version": query(conn, "SELECT version()")[0]["version"],
        }

        # ── Top queries by total execution time ──────────────────────
        data["top_queries"] = query(conn, """
            SELECT queryid, calls, total_exec_time::bigint AS total_ms,
                   mean_exec_time::numeric(10,2) AS mean_ms,
                   stddev_exec_time::numeric(10,2) AS stddev_ms,
                   min_exec_time::numeric(10,2) AS min_ms,
                   max_exec_time::numeric(10,2) AS max_ms,
                   rows,
                   shared_blks_hit, shared_blks_read,
                   shared_blks_dirtied, shared_blks_written,
                   temp_blks_read, temp_blks_written,
                   CASE WHEN shared_blks_hit + shared_blks_read > 0
                        THEN round(shared_blks_hit::numeric /
                             (shared_blks_hit + shared_blks_read), 4)
                        ELSE 1 END AS cache_hit_ratio,
                   left(query, 500) AS query_text
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
            ORDER BY total_exec_time DESC
            LIMIT 50
        """)

        # ── Queries with worst cache hit ratio ───────────────────────
        data["cache_misses"] = query(conn, """
            SELECT queryid, calls,
                   mean_exec_time::numeric(10,2) AS mean_ms,
                   shared_blks_hit, shared_blks_read,
                   CASE WHEN shared_blks_hit + shared_blks_read > 0
                        THEN round(shared_blks_hit::numeric /
                             (shared_blks_hit + shared_blks_read), 4)
                        ELSE 1 END AS cache_hit_ratio,
                   left(query, 300) AS query_text
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND shared_blks_read > 100
            ORDER BY cache_hit_ratio ASC
            LIMIT 20
        """)

        # ── Queries with highest temp usage (spilling to disk) ───────
        data["temp_heavy"] = query(conn, """
            SELECT queryid, calls,
                   mean_exec_time::numeric(10,2) AS mean_ms,
                   temp_blks_read, temp_blks_written,
                   left(query, 300) AS query_text
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND (temp_blks_read > 0 OR temp_blks_written > 0)
            ORDER BY (temp_blks_read + temp_blks_written) DESC
            LIMIT 20
        """)

        # ── N+1 detection: high-call-count simple SELECTs ───────────
        data["n_plus_1_candidates"] = query(conn, """
            SELECT queryid, calls,
                   mean_exec_time::numeric(10,4) AS mean_ms,
                   total_exec_time::bigint AS total_ms,
                   rows,
                   left(query, 300) AS query_text
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND calls > 1000
              AND query ~* '^\\s*SELECT'
              AND query ~* 'WHERE.*=\\s*\\$1'
              AND rows / GREATEST(calls, 1) <= 5
            ORDER BY calls DESC
            LIMIT 20
        """)

        # ── Database-level stats ─────────────────────────────────────
        data["database_stats"] = query(conn, """
            SELECT numbackends, xact_commit, xact_rollback,
                   blks_read, blks_hit,
                   CASE WHEN blks_hit + blks_read > 0
                        THEN round(blks_hit::numeric / (blks_hit + blks_read), 4)
                        ELSE 0 END AS cache_hit_ratio,
                   tup_returned, tup_fetched, tup_inserted,
                   tup_updated, tup_deleted,
                   deadlocks, conflicts,
                   temp_files, temp_bytes,
                   pg_size_pretty(pg_database_size(current_database())) AS db_size,
                   pg_database_size(current_database()) AS db_size_bytes,
                   stats_reset
            FROM pg_stat_database
            WHERE datname = current_database()
        """)

        # ── Table stats ──────────────────────────────────────────────
        data["table_stats"] = query(conn, """
            SELECT relname AS table_name,
                   n_live_tup AS live_rows,
                   n_dead_tup AS dead_rows,
                   CASE WHEN n_live_tup > 0
                        THEN round(n_dead_tup::numeric / n_live_tup, 4)
                        ELSE 0 END AS dead_ratio,
                   pg_total_relation_size(relid) AS total_bytes,
                   pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                   seq_scan, seq_tup_read,
                   idx_scan, idx_tup_fetch,
                   CASE WHEN seq_scan + idx_scan > 0
                        THEN round(idx_scan::numeric / (seq_scan + idx_scan), 4)
                        ELSE 0 END AS idx_scan_ratio,
                   n_tup_ins, n_tup_upd, n_tup_del,
                   n_tup_hot_upd,
                   last_vacuum, last_autovacuum,
                   last_analyze, last_autoanalyze,
                   vacuum_count, autovacuum_count
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
        """)

        # ── Index stats ──────────────────────────────────────────────
        data["index_stats"] = query(conn, """
            SELECT schemaname, relname AS table_name,
                   indexrelname AS index_name,
                   idx_scan,
                   idx_tup_read, idx_tup_fetch,
                   pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
                   pg_relation_size(indexrelid) AS index_bytes
            FROM pg_stat_user_indexes
            ORDER BY idx_scan ASC
            LIMIT 30
        """)

        # ── Unused indexes (candidates for removal) ──────────────────
        data["unused_indexes"] = query(conn, """
            SELECT schemaname, relname AS table_name,
                   indexrelname AS index_name,
                   idx_scan,
                   pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
            FROM pg_stat_user_indexes
            WHERE idx_scan = 0
              AND indexrelname NOT LIKE '%_pkey'
            ORDER BY pg_relation_size(indexrelid) DESC
            LIMIT 20
        """)

        # ── Connection state ─────────────────────────────────────────
        data["connections"] = query(conn, """
            SELECT state, count(*) AS count
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY state
            ORDER BY count DESC
        """)

        # ── Lock state ───────────────────────────────────────────────
        data["locks"] = query(conn, """
            SELECT mode, granted, count(*) AS count
            FROM pg_locks
            WHERE database = (SELECT oid FROM pg_database WHERE datname = current_database())
            GROUP BY mode, granted
            ORDER BY count DESC
        """)

        # ── Current PostgreSQL settings (tuning-relevant) ────────────
        data["pg_settings"] = query(conn, """
            SELECT name, setting, unit, category, short_desc
            FROM pg_settings
            WHERE name IN (
                'shared_buffers', 'effective_cache_size', 'work_mem',
                'maintenance_work_mem', 'max_connections',
                'max_wal_size', 'min_wal_size', 'wal_buffers',
                'checkpoint_completion_target',
                'random_page_cost', 'effective_io_concurrency',
                'default_statistics_target',
                'autovacuum_max_workers', 'autovacuum_naptime',
                'autovacuum_vacuum_scale_factor', 'autovacuum_analyze_scale_factor',
                'shared_preload_libraries', 'track_activities',
                'track_counts', 'track_io_timing',
                'max_parallel_workers_per_gather', 'max_parallel_workers',
                'max_worker_processes', 'huge_pages',
                'temp_buffers', 'log_min_duration_statement'
            )
            ORDER BY category, name
        """)

        # ── Wait events (what queries are waiting on) ────────────────
        data["wait_events"] = query(conn, """
            SELECT wait_event_type, wait_event, count(*) AS count
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND wait_event IS NOT NULL
            GROUP BY wait_event_type, wait_event
            ORDER BY count DESC
            LIMIT 20
        """)

        return data

    finally:
        conn.close()


if __name__ == "__main__":
    data = collect_all()
    print(json.dumps(data, indent=2, default=str))
