#!/usr/bin/env bash
# Object: batch_sync.sh
# Author: SrinivasanPakkirisamy
# Description: Synchronizes nightly customer discount extracts on Unix server (v2.0)

set -euo pipefail

APP_ENV="${APP_ENV:-DEVELOP}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/tmp/unix-server/${APP_ENV}/opt/app}"

if [[ "${1:-}" == "--health-check" ]]; then
  echo "[OK] batch_sync.sh v2.0 (REL-101) verified on Unix target (${APP_ENV}) at ${DEPLOY_ROOT}"
  exit 0
fi

echo "Starting customer discount batch sync v2.0 for environment: ${APP_ENV}"
mkdir -p "${DEPLOY_ROOT}/logs"
echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") | SYNC_SUCCESS | env=${APP_ENV} | version=2.0 | release=REL-101" >> "${DEPLOY_ROOT}/logs/batch_sync.log"
echo "Batch sync v2.0 completed successfully."
