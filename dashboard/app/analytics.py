"""DuckDB analytics engine for pg-stress dashboard.

Reads metrics from the SQLite store and runs fast analytical queries:
time-series rollups, growth rates, anomaly detection, before/after comparisons.

DuckDB is embedded — no server, no config. Reads SQLite directly.
"""
import logging

import duckdb

log = logging.getLogger("analytics")

SQLITE_PATH = "/data/metrics.db"


def _con():
    """Create a DuckDB connection that reads from the SQLite metrics store."""
    con = duckdb.connect(":memory:")
    con.execute("SET memory_limit='256MB'")
    con.execute("SET threads=1")
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{SQLITE_PATH}' AS metrics (TYPE sqlite, READ_ONLY);")
    return con


def summary(minutes: int = 60) -> dict:
    """Aggregate metrics over the last N minutes using DuckDB."""
    try:
        con = _con()
        # Limit to last 500 samples max to avoid OOM on large datasets.
        max_rows = min(minutes * 6, 500)  # ~6 samples/min at 10s interval
        result = con.execute(f"""
            WITH raw AS (
                SELECT timestamp, data
                FROM metrics.samples
                ORDER BY id DESC
                LIMIT {max_rows}
            ),
            parsed AS (
                SELECT
                    timestamp,
                    json_extract_string(data, '$.txn_per_sec')::DOUBLE AS txn_per_sec,
                    json_extract_string(data, '$.total_connections')::INT AS total_connections,
                    json_extract_string(data, '$.cache_hit_ratio')::DOUBLE AS cache_hit_ratio,
                    json_extract_string(data, '$.database_size_bytes')::BIGINT AS db_size_bytes,
                    json_extract_string(data, '$.tup_inserted_per_sec')::DOUBLE AS inserts_per_sec,
                    json_extract_string(data, '$.tup_updated_per_sec')::DOUBLE AS updates_per_sec,
                    json_extract_string(data, '$.tup_deleted_per_sec')::DOUBLE AS deletes_per_sec,
                    json_extract_string(data, '$.lock_count')::INT AS locks,
                    json_extract_string(data, '$.deadlocks')::INT AS deadlocks,
                    json_extract_string(data, '$.temp_files')::INT AS temp_files
                FROM raw
            )
            SELECT
                COUNT(*) AS sample_count,
                MIN(timestamp) AS first_sample,
                MAX(timestamp) AS last_sample,
                ROUND(AVG(txn_per_sec), 1) AS avg_tps,
                ROUND(MAX(txn_per_sec), 1) AS peak_tps,
                ROUND(MIN(txn_per_sec), 1) AS min_tps,
                ROUND(AVG(total_connections), 0)::INT AS avg_connections,
                MAX(total_connections) AS peak_connections,
                ROUND(AVG(cache_hit_ratio) * 100, 2) AS avg_cache_hit_pct,
                ROUND(MIN(cache_hit_ratio) * 100, 2) AS min_cache_hit_pct,
                MAX(db_size_bytes) AS max_db_size_bytes,
                ROUND(AVG(inserts_per_sec), 1) AS avg_inserts_per_sec,
                ROUND(AVG(updates_per_sec), 1) AS avg_updates_per_sec,
                ROUND(AVG(deletes_per_sec), 1) AS avg_deletes_per_sec,
                MAX(locks) AS peak_locks,
                MAX(deadlocks) AS total_deadlocks,
                MAX(temp_files) AS total_temp_files
            FROM parsed
        """).fetchone()
        con.close()

        if not result or result[0] == 0:
            return {"error": "no data", "minutes": minutes}

        cols = ["sample_count", "first_sample", "last_sample",
                "avg_tps", "peak_tps", "min_tps",
                "avg_connections", "peak_connections",
                "avg_cache_hit_pct", "min_cache_hit_pct",
                "max_db_size_bytes",
                "avg_inserts_per_sec", "avg_updates_per_sec", "avg_deletes_per_sec",
                "peak_locks", "total_deadlocks", "total_temp_files"]
        return dict(zip(cols, result))
    except Exception as e:
        log.error("analytics summary error: %s", e)
        return {"error": str(e)}


def tps_by_minute(minutes: int = 60) -> list[dict]:
    """TPS aggregated per minute for charting."""
    try:
        con = _con()
        max_rows = min(minutes * 6, 500)
        rows = con.execute(f"""
            WITH raw AS (
                SELECT timestamp, data FROM metrics.samples ORDER BY id DESC LIMIT {max_rows}
            ),
            parsed AS (
                SELECT
                    timestamp,
                    json_extract_string(data, '$.txn_per_sec')::DOUBLE AS txn_per_sec,
                    json_extract_string(data, '$.total_connections')::INT AS conns,
                    json_extract_string(data, '$.cache_hit_ratio')::DOUBLE AS cache_ratio
                FROM raw
            )
            SELECT
                date_trunc('minute', timestamp::TIMESTAMP) AS minute,
                ROUND(AVG(txn_per_sec), 1) AS avg_tps,
                MAX(txn_per_sec)::INT AS peak_tps,
                ROUND(AVG(conns), 0)::INT AS avg_conns,
                ROUND(AVG(cache_ratio) * 100, 2) AS cache_pct
            FROM parsed
            GROUP BY 1
            ORDER BY 1
        """).fetchall()
        con.close()
        return [{"minute": str(r[0]), "avg_tps": r[1], "peak_tps": r[2],
                 "avg_conns": r[3], "cache_pct": r[4]} for r in rows]
    except Exception as e:
        return [{"error": str(e)}]


def growth_rate() -> list[dict]:
    """Calculate table size growth rate from metrics samples."""
    try:
        con = _con()
        rows = con.execute("""
            WITH bounded AS (
                SELECT timestamp, data FROM metrics.samples ORDER BY id DESC LIMIT 500
            ),
            first_last AS (
                SELECT
                    json_extract_string(data, '$.database_size_bytes')::BIGINT AS db_bytes,
                    timestamp,
                    ROW_NUMBER() OVER (ORDER BY timestamp ASC) AS rn_asc,
                    ROW_NUMBER() OVER (ORDER BY timestamp DESC) AS rn_desc
                FROM bounded
            )
            SELECT
                (SELECT db_bytes FROM first_last WHERE rn_asc = 1) AS first_bytes,
                (SELECT db_bytes FROM first_last WHERE rn_desc = 1) AS last_bytes,
                (SELECT timestamp FROM first_last WHERE rn_asc = 1) AS first_ts,
                (SELECT timestamp FROM first_last WHERE rn_desc = 1) AS last_ts
        """).fetchone()
        con.close()

        if not rows or not rows[0] or not rows[1]:
            return [{"error": "insufficient data"}]

        first_b, last_b, first_ts, last_ts = rows
        delta_bytes = last_b - first_b
        return [{
            "first_bytes": first_b, "last_bytes": last_b,
            "delta_bytes": delta_bytes,
            "first_ts": str(first_ts), "last_ts": str(last_ts),
            "growth_mb": round(delta_bytes / (1024 * 1024), 1),
        }]
    except Exception as e:
        return [{"error": str(e)}]
