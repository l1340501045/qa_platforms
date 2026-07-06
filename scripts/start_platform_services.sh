#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
API_PID_FILE="${LOG_DIR}/platform_api.pid"
WORKER_PID_FILE="${LOG_DIR}/celery.pid"

cd "$ROOT_DIR"
mkdir -p "$LOG_DIR"

if [[ ! -f .env ]]; then
  echo "[ERR] Missing .env"
  exit 1
fi

# Stop previous processes to avoid port/queue contention.
if [[ -f "$API_PID_FILE" ]] && kill -0 "$(cat "$API_PID_FILE")" 2>/dev/null; then
  echo "[INFO] Stopping old API process $(cat "$API_PID_FILE")"
  kill "$(cat "$API_PID_FILE")" || true
fi
if [[ -f "$WORKER_PID_FILE" ]] && kill -0 "$(cat "$WORKER_PID_FILE")" 2>/dev/null; then
  echo "[INFO] Stopping old worker process $(cat "$WORKER_PID_FILE")"
  kill "$(cat "$WORKER_PID_FILE")" || true
fi

nohup ./.venv/bin/python -m uvicorn src.platform_api.main:app \
  --host 0.0.0.0 --port 8000 \
  > "${LOG_DIR}/platform_api.log" 2>&1 < /dev/null &
echo $! > "$API_PID_FILE"

nohup ./.venv/bin/python -m celery -A src.platform_api.core.celery_app:celery_app worker \
  -Q testcase_generation,kb_parsing,export \
  --loglevel=info --pool=solo --concurrency=4 \
  > "${LOG_DIR}/celery.log" 2>&1 < /dev/null &
echo $! > "$WORKER_PID_FILE"

echo "[INFO] API PID: $(cat "$API_PID_FILE")"
echo "[INFO] Worker PID: $(cat "$WORKER_PID_FILE")"
echo "[INFO] Logs: ${LOG_DIR}/platform_api.log , ${LOG_DIR}/celery.log"
