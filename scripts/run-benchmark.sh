#!/usr/bin/env bash
set -euo pipefail

# ─── pgbench Benchmark Comparison Runner ────────────────────────────────
#
# Runs a structured benchmark comparing:
#   1. pgbench TPC-B (standard baseline)
#   2. pgbench with custom e-commerce scripts
#   3. Captures pg_stat_statements snapshots for pg-collector validation
#
# Usage:
#   ./scripts/run-benchmark.sh                    # Local (requires running stack)
#   ./scripts/run-benchmark.sh --remote 4         # Run on server 4
#   ./scripts/run-benchmark.sh --duration 600     # 10 minute run
#   ./scripts/run-benchmark.sh --mode all         # Run all benchmark modes

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

# Defaults.
REMOTE=""
DURATION="${PGBENCH_DURATION:-300}"
CLIENTS="${PGBENCH_CLIENTS:-10}"
MODE="${PGBENCH_MODE:-all}"
SCALE="${PGBENCH_SCALE:-100}"
OUTPUT_DIR="${PROJECT_DIR}/out/benchmark-$(date '+%Y%m%d-%H%M%S')"

# Parse arguments.
while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)   REMOTE="$2"; shift 2 ;;
        --duration) DURATION="$2"; shift 2 ;;
        --clients)  CLIENTS="$2"; shift 2 ;;
        --mode)     MODE="$2"; shift 2 ;;
        --scale)    SCALE="$2"; shift 2 ;;
        --output)   OUTPUT_DIR="$2"; shift 2 ;;
        --help)
            echo "Usage: $0 [--remote HOST] [--duration SECS] [--clients N] [--mode MODE] [--scale N]"
            echo ""
            echo "Modes: tpcb, readonly, mixed, custom, all"
            exit 0
            ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

log() { echo "[benchmark] $(date '+%H:%M:%S') $*"; }

mkdir -p "${OUTPUT_DIR}"

# ─── Pre-flight: capture system info ─────────────────────────────────────

capture_system_info() {
    local target="$1"
    log "Capturing system info..."

    if [ -n "${REMOTE}" ]; then
        ssh "${REMOTE}" "
            echo '--- CPU ---'
            nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo unknown
            echo '--- Memory ---'
            free -h 2>/dev/null || sysctl -n hw.memsize 2>/dev/null || echo unknown
            echo '--- Disk ---'
            df -h / 2>/dev/null || echo unknown
            echo '--- Docker ---'
            docker compose ps 2>/dev/null || echo 'no compose'
        " > "${target}/system_info.txt" 2>&1
    else
        {
            echo "--- CPU ---"
            nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo unknown
            echo "--- Memory ---"
            free -h 2>/dev/null || echo "$(sysctl -n hw.memsize 2>/dev/null || echo unknown) bytes"
            echo "--- Docker ---"
            cd "${PROJECT_DIR}" && docker compose ps 2>/dev/null || echo 'no compose'
        } > "${target}/system_info.txt" 2>&1
    fi
}

# ─── Pre-flight: snapshot current pg_stat_statements ─────────────────────

snapshot_pg_stats() {
    local label="$1"
    log "Snapshot pg_stat_statements (${label})..."

    local pg_cmd="psql -h localhost -p ${PG_PORT:-5434} -U postgres -d testdb"
    if [ -n "${REMOTE}" ]; then
        pg_cmd="ssh ${REMOTE} 'PGPASSWORD=postgres psql -h localhost -p 5434 -U postgres -d testdb'"
    fi

    eval "${pg_cmd}" -t -A -F$'\t' -c "
        SELECT queryid, calls, total_exec_time::bigint, mean_exec_time::numeric(10,2),
               rows, shared_blks_hit, shared_blks_read,
               left(query, 200) AS query_prefix
        FROM pg_stat_statements
        WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'testdb')
        ORDER BY total_exec_time DESC
        LIMIT 100
    " > "${OUTPUT_DIR}/pg_stat_statements_${label}.tsv" 2>/dev/null || true
}

# ─── Run pgbench via Docker ──────────────────────────────────────────────

run_pgbench_docker() {
    log "Starting pgbench runner (mode=${MODE}, duration=${DURATION}s, clients=${CLIENTS})..."

    local compose_cmd="docker compose --profile pgbench"
    if [ -n "${REMOTE}" ]; then
        compose_cmd="ssh ${REMOTE} 'cd /opt/burnside-test-suite && docker compose --profile pgbench'"
    fi

    # Set environment and run.
    local env_vars="PGBENCH_MODE=${MODE} PGBENCH_DURATION=${DURATION} PGBENCH_CLIENTS=${CLIENTS} PGBENCH_SCALE=${SCALE} PGBENCH_KEEP_ALIVE=true"

    eval "${env_vars} ${compose_cmd} up --build -d pgbench-runner" 2>&1

    log "pgbench running... waiting for completion."

    # Wait for pgbench to finish (check logs for completion message).
    local max_wait=$(( DURATION + 120 ))  # duration + warmup + overhead
    local elapsed=0
    while [ ${elapsed} -lt ${max_wait} ]; do
        if eval "${compose_cmd} logs pgbench-runner 2>&1" | grep -q "pgbench-runner complete"; then
            break
        fi
        sleep 10
        elapsed=$(( elapsed + 10 ))
        log "Waiting... (${elapsed}s / ~${max_wait}s)"
    done

    # Copy results out.
    log "Collecting results..."
    local container_id
    container_id=$(eval "${compose_cmd} ps -q pgbench-runner" 2>/dev/null || echo "")
    if [ -n "${container_id}" ]; then
        if [ -n "${REMOTE}" ]; then
            ssh "${REMOTE}" "docker cp ${container_id}:/out/. /tmp/pgbench-results/"
            scp -rq "${REMOTE}:/tmp/pgbench-results/"* "${OUTPUT_DIR}/"
            ssh "${REMOTE}" "rm -rf /tmp/pgbench-results"
        else
            docker cp "${container_id}:/out/." "${OUTPUT_DIR}/"
        fi
    fi

    # Stop the runner.
    eval "${compose_cmd} stop pgbench-runner" 2>&1 || true
}

# ─── Generate comparison summary ────────────────────────────────────────

generate_summary() {
    log "Generating summary..."

    cat > "${OUTPUT_DIR}/summary.md" <<'HEADER'
# pgbench Benchmark Results

HEADER

    echo "**Date:** $(date '+%Y-%m-%d %H:%M:%S')" >> "${OUTPUT_DIR}/summary.md"
    echo "**Mode:** ${MODE}" >> "${OUTPUT_DIR}/summary.md"
    echo "**Duration:** ${DURATION}s per phase" >> "${OUTPUT_DIR}/summary.md"
    echo "**Clients:** ${CLIENTS}" >> "${OUTPUT_DIR}/summary.md"
    echo "**Scale:** ${SCALE}" >> "${OUTPUT_DIR}/summary.md"
    echo "" >> "${OUTPUT_DIR}/summary.md"

    echo "## Results" >> "${OUTPUT_DIR}/summary.md"
    echo "" >> "${OUTPUT_DIR}/summary.md"
    echo "| Phase | TPS (excl. conn) | Avg Latency (ms) | Transactions |" >> "${OUTPUT_DIR}/summary.md"
    echo "|-------|-----------------|-------------------|--------------|" >> "${OUTPUT_DIR}/summary.md"

    for f in "${OUTPUT_DIR}"/*.json; do
        [ "$(basename "$f")" = "comparison.json" ] && continue
        [ ! -f "$f" ] && continue
        local phase tps latency txns
        phase=$(python3 -c "import json; d=json.load(open('$f')); print(d.get('phase','?'))" 2>/dev/null || echo "?")
        tps=$(python3 -c "import json; d=json.load(open('$f')); print(d['results']['tps_excluding_connections'])" 2>/dev/null || echo "0")
        latency=$(python3 -c "import json; d=json.load(open('$f')); print(d['results']['latency_avg_ms'])" 2>/dev/null || echo "0")
        txns=$(python3 -c "import json; d=json.load(open('$f')); print(d['results']['transactions_processed'])" 2>/dev/null || echo "0")
        echo "| ${phase} | ${tps} | ${latency} | ${txns} |" >> "${OUTPUT_DIR}/summary.md"
    done

    echo "" >> "${OUTPUT_DIR}/summary.md"
    echo "## pg_stat_statements Snapshots" >> "${OUTPUT_DIR}/summary.md"
    echo "" >> "${OUTPUT_DIR}/summary.md"
    echo "Before/after snapshots saved as TSV files in this directory." >> "${OUTPUT_DIR}/summary.md"
    echo "Compare with pg-collector output to validate fingerprint tracking." >> "${OUTPUT_DIR}/summary.md"

    log "Summary: ${OUTPUT_DIR}/summary.md"
}

# ─── Main ───────────────────────────────────────────────────────────────

main() {
    log "═══════════════════════════════════════════════════════════"
    log "  Burnside pgbench Benchmark"
    log "  Mode: ${MODE} | Duration: ${DURATION}s | Clients: ${CLIENTS}"
    log "  Output: ${OUTPUT_DIR}"
    log "═══════════════════════════════════════════════════════════"

    capture_system_info "${OUTPUT_DIR}"
    snapshot_pg_stats "pre_benchmark"
    run_pgbench_docker
    snapshot_pg_stats "post_benchmark"
    generate_summary

    log ""
    log "Benchmark complete!"
    log "Results: ${OUTPUT_DIR}"
    log ""
    ls -la "${OUTPUT_DIR}/"
}

main
