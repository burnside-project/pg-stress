#!/usr/bin/env bash
set -euo pipefail

# ─── pgbench Runner Entrypoint ──────────────────────────────────────────
#
# Runs pgbench in multiple modes against the shared PostgreSQL instance,
# outputs structured JSON results for comparison with custom load generators.
#
# Modes:
#   tpcb     — Standard TPC-B (default pgbench workload)
#   readonly — Read-only TPC-B (SELECT only)
#   mixed    — Alternates TPC-B and read-only phases
#   custom   — Runs custom SQL scripts from /opt/pgbench/scripts/
#   all      — Runs all modes sequentially and produces comparison report

PG_HOST="${PG_HOST:-postgres}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_DB="${PG_DB:-testdb}"
PGPASSWORD="${PGPASSWORD:-postgres}"
export PGPASSWORD

CLIENTS="${PGBENCH_CLIENTS:-10}"
THREADS="${PGBENCH_THREADS:-2}"
DURATION="${PGBENCH_DURATION:-300}"
SCALE="${PGBENCH_SCALE:-100}"
MODE="${PGBENCH_MODE:-mixed}"
OUTPUT_DIR="${PGBENCH_OUTPUT_DIR:-/out}"
WARMUP="${PGBENCH_WARMUP:-30}"

mkdir -p "${OUTPUT_DIR}"

log() { echo "[pgbench-runner] $(date '+%Y-%m-%dT%H:%M:%S') $*"; }

# ─── Wait for PostgreSQL ────────────────────────────────────────────────

wait_for_pg() {
    log "Waiting for PostgreSQL at ${PG_HOST}:${PG_PORT}..."
    for i in $(seq 1 60); do
        if pg_isready -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" >/dev/null 2>&1; then
            log "PostgreSQL is ready."
            return 0
        fi
        sleep 2
    done
    log "ERROR: PostgreSQL not ready after 120s"
    exit 1
}

# ─── Initialize pgbench tables ──────────────────────────────────────────

init_pgbench() {
    log "Initializing pgbench tables (scale=${SCALE})..."
    pgbench -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
        --initialize --scale="${SCALE}" --foreign-keys --no-vacuum 2>&1 || true
    log "pgbench tables ready."
}

# ─── Snapshot pg_stat_statements before/after ───────────────────────────

snapshot_statements() {
    local label="$1"
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
        -t -A -F$'\t' -c "
        SELECT queryid, calls, total_exec_time, mean_exec_time,
               rows, shared_blks_hit, shared_blks_read, query
        FROM pg_stat_statements
        WHERE dbid = (SELECT oid FROM pg_database WHERE datname = '${PG_DB}')
        ORDER BY total_exec_time DESC
        LIMIT 50
    " > "${OUTPUT_DIR}/statements_${label}.tsv" 2>/dev/null || true
}

# ─── Run a pgbench phase ────────────────────────────────────────────────

run_phase() {
    local phase_name="$1"
    shift
    local extra_args=("$@")

    log "=== Phase: ${phase_name} ==="
    log "Clients=${CLIENTS} Threads=${THREADS} Duration=${DURATION}s"

    # Reset pg_stat_statements.
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
        -c "SELECT pg_stat_statements_reset()" >/dev/null 2>&1 || true

    # Warmup.
    if [ "${WARMUP}" -gt 0 ]; then
        log "Warmup: ${WARMUP}s..."
        pgbench -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
            -c "${CLIENTS}" -j "${THREADS}" -T "${WARMUP}" \
            "${extra_args[@]}" >/dev/null 2>&1 || true
    fi

    snapshot_statements "${phase_name}_before"

    # Main run with progress reporting.
    local raw_output
    raw_output=$(pgbench -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
        -c "${CLIENTS}" -j "${THREADS}" -T "${DURATION}" \
        --progress=30 --report-per-command \
        "${extra_args[@]}" 2>&1)

    snapshot_statements "${phase_name}_after"

    # Parse pgbench output into JSON.
    local tps_incl tps_excl latency_avg latency_stddev txn_count
    tps_incl=$(echo "${raw_output}" | grep -oP 'tps = \K[0-9.]+(?= \(including)' || echo "0")
    tps_excl=$(echo "${raw_output}" | grep -oP 'tps = \K[0-9.]+(?= \(excluding)' || echo "0")
    latency_avg=$(echo "${raw_output}" | grep -oP 'latency average = \K[0-9.]+' || echo "0")
    latency_stddev=$(echo "${raw_output}" | grep -oP 'latency stddev = \K[0-9.]+' || echo "0")
    txn_count=$(echo "${raw_output}" | grep -oP 'number of transactions actually processed: \K[0-9]+' || echo "0")

    # Write raw output.
    echo "${raw_output}" > "${OUTPUT_DIR}/${phase_name}_raw.txt"

    # Write structured JSON result.
    cat > "${OUTPUT_DIR}/${phase_name}.json" <<ENDJSON
{
  "phase": "${phase_name}",
  "timestamp": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "config": {
    "clients": ${CLIENTS},
    "threads": ${THREADS},
    "duration_seconds": ${DURATION},
    "scale": ${SCALE},
    "warmup_seconds": ${WARMUP}
  },
  "results": {
    "tps_including_connections": ${tps_incl:-0},
    "tps_excluding_connections": ${tps_excl:-0},
    "latency_avg_ms": ${latency_avg:-0},
    "latency_stddev_ms": ${latency_stddev:-0},
    "transactions_processed": ${txn_count:-0}
  }
}
ENDJSON

    log "Phase ${phase_name} complete: tps=${tps_excl} latency_avg=${latency_avg}ms txns=${txn_count}"
    echo "${raw_output}"
}

# ─── Mode runners ───────────────────────────────────────────────────────

run_tpcb() {
    run_phase "tpcb" --no-vacuum
}

run_readonly() {
    run_phase "readonly" --select-only --no-vacuum
}

run_mixed() {
    # Phase 1: standard TPC-B.
    local saved_duration="${DURATION}"
    DURATION=$(( saved_duration / 2 ))

    run_phase "mixed_tpcb" --no-vacuum

    # Phase 2: read-only.
    run_phase "mixed_readonly" --select-only --no-vacuum

    DURATION="${saved_duration}"
}

run_custom() {
    local script_dir="/opt/pgbench/scripts"
    if [ ! -d "${script_dir}" ] || [ -z "$(ls -A "${script_dir}"/*.sql 2>/dev/null)" ]; then
        log "No custom scripts found in ${script_dir}, skipping."
        return 0
    fi

    for script in "${script_dir}"/*.sql; do
        local script_name
        script_name=$(basename "${script}" .sql)
        run_phase "custom_${script_name}" --no-vacuum -f "${script}"
    done
}

run_all() {
    log "Running ALL benchmark modes..."
    init_pgbench
    run_tpcb
    run_readonly
    run_custom
    generate_comparison
}

# ─── Comparison report ──────────────────────────────────────────────────

generate_comparison() {
    log "Generating comparison report..."

    local report="${OUTPUT_DIR}/comparison.json"
    local phases=()

    for f in "${OUTPUT_DIR}"/*.json; do
        [ "$(basename "$f")" = "comparison.json" ] && continue
        phases+=("$(cat "$f")")
    done

    # Merge all phase results into a single comparison document.
    local joined
    joined=$(printf '%s,' "${phases[@]}")
    joined="[${joined%,}]"

    cat > "${report}" <<ENDJSON
{
  "benchmark": "burnside-pgbench-comparison",
  "generated_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "host": "$(hostname)",
  "phases": ${joined}
}
ENDJSON

    log "Comparison report: ${report}"
}

# ─── Main ───────────────────────────────────────────────────────────────

main() {
    log "pgbench-runner starting (mode=${MODE})"
    wait_for_pg
    init_pgbench

    case "${MODE}" in
        tpcb)     run_tpcb ;;
        readonly) run_readonly ;;
        mixed)    run_mixed ;;
        custom)   run_custom ;;
        all)      run_all ;;
        *)
            log "ERROR: unknown mode '${MODE}'. Use: tpcb|readonly|mixed|custom|all"
            exit 1
            ;;
    esac

    generate_comparison
    log "pgbench-runner complete. Results in ${OUTPUT_DIR}/"

    # Keep container alive for result retrieval if running in Docker.
    if [ "${PGBENCH_KEEP_ALIVE:-false}" = "true" ]; then
        log "Keeping container alive for result retrieval..."
        tail -f /dev/null
    fi
}

main "$@"
