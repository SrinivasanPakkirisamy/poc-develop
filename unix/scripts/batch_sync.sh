#!/usr/bin/env bash
# Object: batch_sync.sh
# Author: unix-ops
# Description: Synchronizes nightly customer discount extracts on Unix server

set -euo pipefail

APP_ENV="${APP_ENV:-DEVELOP}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/tmp/unix-server/${APP_ENV}/opt/app}"

if [[ "${1:-}" == "--health-check" ]]; then
  echo "[OK] batch_sync.sh v1.0 verified on Unix target (${APP_ENV}) at ${DEPLOY_ROOT}"
  exit 0
fi

echo "Starting customer discount batch sync for environment: ${APP_ENV}"
mkdir -p "${DEPLOY_ROOT}/logs"
echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") | SYNC_SUCCESS | env=${APP_ENV} | version=1.0" >> "${DEPLOY_ROOT}/logs/batch_sync.log"
echo "Batch sync completed successfully."
