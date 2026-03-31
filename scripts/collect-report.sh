#!/usr/bin/env bash
set -euo pipefail

# ─── Collect All Test Results into a Report ─────────────────────────────
#
# Gathers data from all running services and produces a consolidated
# report in out/.
#
# Usage:
#   ./scripts/collect-report.sh                # Local
#   ./scripts/collect-report.sh --remote 4     # From server 4

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

REMOTE=""
[[ "${1:-}" == "--remote" ]] && REMOTE="${2:-4}"

REPORT_DIR="${PROJECT_DIR}/out/report-$(date '+%Y%m%d-%H%M%S')"
mkdir -p "${REPORT_DIR}"

log() { echo "[report] $(date '+%H:%M:%S') $*"; }

run_cmd() {
    if [ -n "${REMOTE}" ]; then
        ssh "${REMOTE}" "$@"
    else
        eval "$@"
    fi
}

PG_PORT="${PG_PORT:-5434}"
PG_CMD="PGPASSWORD=postgres psql -h localhost -p ${PG_PORT} -U postgres -d testdb -t -A"

# ─── 1. Service Status ──────────────────────────────────────────────────

log "Collecting service status..."
run_cmd "cd ${DEPLOY_PATH:-${PROJECT_DIR}} && docker compose ps" > "${REPORT_DIR}/services.txt" 2>&1 || true

# ─── 2. Load Generator Stats ────────────────────────────────────────────

log "Collecting load generator stats..."
curl -s "http://${REMOTE:-localhost}:9090/healthz" > "${REPORT_DIR}/loadgen_raw.json" 2>/dev/null || echo '{"error":"not reachable"}' > "${REPORT_DIR}/loadgen_raw.json"
curl -s "http://${REMOTE:-localhost}:9091/healthz" > "${REPORT_DIR}/loadgen_orm.json" 2>/dev/null || echo '{"error":"not reachable"}' > "${REPORT_DIR}/loadgen_orm.json"

# ─── 3. pg_stat_statements Snapshot ──────────────────────────────────────

log "Collecting pg_stat_statements..."
run_cmd "${PG_CMD} -F$'\t' -c \"
    SELECT queryid, calls, total_exec_time::bigint AS total_ms,
           mean_exec_time::numeric(10,2) AS mean_ms,
           rows, shared_blks_hit, shared_blks_read,
           left(query, 300) AS query_prefix
    FROM pg_stat_statements
    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'testdb')
    ORDER BY total_exec_time DESC
    LIMIT 200
\"" > "${REPORT_DIR}/pg_stat_statements.tsv" 2>/dev/null || true

# ─── 4. Database Size & Table Stats ─────────────────────────────────────

log "Collecting database stats..."
run_cmd "${PG_CMD} -c \"
    SELECT pg_size_pretty(pg_database_size('testdb')) AS db_size
\"" > "${REPORT_DIR}/db_size.txt" 2>/dev/null || true

run_cmd "${PG_CMD} -F$'\t' -c \"
    SELECT relname AS table_name,
           n_live_tup AS live_rows,
           n_dead_tup AS dead_rows,
           pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
           last_vacuum,
           last_autovacuum,
           last_analyze
    FROM pg_stat_user_tables
    ORDER BY pg_total_relation_size(relid) DESC
\"" > "${REPORT_DIR}/table_stats.tsv" 2>/dev/null || true

# ─── 5. Connection & Activity ───────────────────────────────────────────

log "Collecting connection info..."
run_cmd "${PG_CMD} -F$'\t' -c \"
    SELECT state, count(*) FROM pg_stat_activity
    WHERE datname = 'testdb'
    GROUP BY state ORDER BY count DESC
\"" > "${REPORT_DIR}/connections.tsv" 2>/dev/null || true

# ─── 6. pg_stat_database ────────────────────────────────────────────────

log "Collecting database-level stats..."
run_cmd "${PG_CMD} -F$'\t' -c \"
    SELECT numbackends, xact_commit, xact_rollback,
           blks_read, blks_hit,
           CASE WHEN blks_hit + blks_read > 0
                THEN round(blks_hit::numeric / (blks_hit + blks_read), 4)
                ELSE 0 END AS cache_hit_ratio,
           tup_returned, tup_fetched, tup_inserted, tup_updated, tup_deleted,
           deadlocks, temp_files, temp_bytes,
           pg_size_pretty(pg_database_size('testdb')) AS size
    FROM pg_stat_database
    WHERE datname = 'testdb'
\"" > "${REPORT_DIR}/pg_stat_database.tsv" 2>/dev/null || true

# ─── 7. Lock Info ───────────────────────────────────────────────────────

log "Collecting lock info..."
run_cmd "${PG_CMD} -F$'\t' -c \"
    SELECT mode, count(*) FROM pg_locks
    WHERE database = (SELECT oid FROM pg_database WHERE datname = 'testdb')
    GROUP BY mode ORDER BY count DESC
\"" > "${REPORT_DIR}/locks.tsv" 2>/dev/null || true

# ─── 8. pgbench Results (if available) ──────────────────────────────────

log "Checking for pgbench results..."
if [ -n "${REMOTE}" ]; then
    local_pgbench="${REPORT_DIR}/pgbench/"
    mkdir -p "${local_pgbench}"
    scp -rq "${REMOTE}:/opt/burnside-test-suite/out/benchmark-*" "${local_pgbench}" 2>/dev/null || true
else
    if ls "${PROJECT_DIR}/out/benchmark-"* >/dev/null 2>&1; then
        cp -r "${PROJECT_DIR}/out/benchmark-"* "${REPORT_DIR}/" 2>/dev/null || true
    fi
fi

# ─── 9. Generate Markdown Report ────────────────────────────────────────

log "Generating report..."
cat > "${REPORT_DIR}/REPORT.md" <<EOF
# Burnside Test Suite — Collected Report

**Generated:** $(date '+%Y-%m-%d %H:%M:%S')
**Source:** ${REMOTE:-localhost}

## Database Overview

$(cat "${REPORT_DIR}/db_size.txt" 2>/dev/null || echo "N/A")

## Connections by State

\`\`\`
$(cat "${REPORT_DIR}/connections.tsv" 2>/dev/null || echo "N/A")
\`\`\`

## Cache Hit Ratio

\`\`\`
$(cat "${REPORT_DIR}/pg_stat_database.tsv" 2>/dev/null || echo "N/A")
\`\`\`

## Table Sizes & Vacuum Status

\`\`\`
$(cat "${REPORT_DIR}/table_stats.tsv" 2>/dev/null || echo "N/A")
\`\`\`

## Top Queries by Total Execution Time

\`\`\`
$(head -30 "${REPORT_DIR}/pg_stat_statements.tsv" 2>/dev/null || echo "N/A")
\`\`\`

## Lock Distribution

\`\`\`
$(cat "${REPORT_DIR}/locks.tsv" 2>/dev/null || echo "N/A")
\`\`\`

## Load Generator Status

### Raw SQL (Go)
\`\`\`json
$(cat "${REPORT_DIR}/loadgen_raw.json" 2>/dev/null || echo "{}")
\`\`\`

### ORM (SQLAlchemy)
\`\`\`json
$(cat "${REPORT_DIR}/loadgen_orm.json" 2>/dev/null || echo "{}")
\`\`\`

## Files in This Report

$(ls -1 "${REPORT_DIR}/" | sed 's/^/- /')

---
*Collected by collect-report.sh*
EOF

log ""
log "Report complete: ${REPORT_DIR}/REPORT.md"
log "All artifacts:   ${REPORT_DIR}/"
log ""
ls -la "${REPORT_DIR}/"
