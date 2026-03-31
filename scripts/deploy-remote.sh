#!/usr/bin/env bash
set -euo pipefail

# ─── Deploy Burnside Test Suite to Remote Server ────────────────────────
#
# Usage:
#   ./scripts/deploy-remote.sh              # Deploy to default host (ssh 4)
#   ./scripts/deploy-remote.sh 4            # Deploy to ssh alias "4"
#   ./scripts/deploy-remote.sh user@host    # Deploy to specific host
#
# Prerequisites:
#   - SSH access to target host
#   - Docker + Docker Compose on target host
#   - Sibling repo: burnside-project-collector-agent

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
DEPLOY_HOST="${1:-${DEPLOY_HOST:-4}}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/burnside-test-suite}"
DEPLOY_PROFILE="${DEPLOY_PROFILE:-}"  # empty = core only

log() { echo "[deploy] $(date '+%H:%M:%S') $*"; }

log "Deploying to ${DEPLOY_HOST}:${DEPLOY_PATH}"

# ─── 1. Create deployment tarball ────────────────────────────────────────

log "Creating deployment archive..."
TARBALL=$(mktemp /tmp/burnside-deploy-XXXXX.tar.gz)

tar -czf "${TARBALL}" \
    -C "${PROJECT_DIR}" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='out/*' \
    --exclude='node_modules' \
    --exclude='.claude' \
    .

log "Archive: $(du -h "${TARBALL}" | cut -f1)"

# ─── 2. Transfer and extract on remote ──────────────────────────────────

log "Transferring to ${DEPLOY_HOST}..."
ssh "${DEPLOY_HOST}" "mkdir -p ${DEPLOY_PATH}"
scp -q "${TARBALL}" "${DEPLOY_HOST}:${DEPLOY_PATH}/deploy.tar.gz"

log "Extracting on remote..."
ssh "${DEPLOY_HOST}" "cd ${DEPLOY_PATH} && tar -xzf deploy.tar.gz && rm deploy.tar.gz"

# ─── 3. Check for collector sibling repo ─────────────────────────────────

log "Checking for collector agent repo..."
COLLECTOR_PATH="$(dirname "${DEPLOY_PATH}")/burnside-project-collector-agent"
ssh "${DEPLOY_HOST}" "
    if [ ! -d '${COLLECTOR_PATH}' ]; then
        echo '[deploy] WARNING: ${COLLECTOR_PATH} not found on remote.'
        echo '[deploy] Collector/truth-service profiles will not work.'
        echo '[deploy] Clone burnside-project-collector-agent as a sibling directory.'
    else
        echo '[deploy] Collector repo found at ${COLLECTOR_PATH}'
    fi
"

# ─── 4. Build and start on remote ───────────────────────────────────────

PROFILE_FLAG=""
if [ -n "${DEPLOY_PROFILE}" ]; then
    PROFILE_FLAG="--profile ${DEPLOY_PROFILE}"
fi

log "Building and starting stack on ${DEPLOY_HOST}..."
ssh "${DEPLOY_HOST}" "
    cd ${DEPLOY_PATH}

    # Copy .env if it doesn't exist.
    [ -f .env ] || cp .env.example .env 2>/dev/null || true

    # Pull and build.
    docker compose ${PROFILE_FLAG} build
    docker compose ${PROFILE_FLAG} up -d

    echo ''
    docker compose ${PROFILE_FLAG} ps
"

# ─── 5. Cleanup ─────────────────────────────────────────────────────────

rm -f "${TARBALL}"
log "Deployment complete!"
log ""
log "  SSH:       ssh ${DEPLOY_HOST}"
log "  Dashboard: http://$(ssh "${DEPLOY_HOST}" hostname -I | awk '{print $1}'):8000"
log "  Postgres:  $(ssh "${DEPLOY_HOST}" hostname -I | awk '{print $1}'):5434"
log ""
log "  Manage:    ssh ${DEPLOY_HOST} 'cd ${DEPLOY_PATH} && make status'"
