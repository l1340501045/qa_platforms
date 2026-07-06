#!/usr/bin/env sh
set -eu

case "${1:-api}" in
  api)
    echo "[INFO] Running database migrations"
    alembic upgrade head
    echo "[INFO] Starting API"
    exec python -m uvicorn src.platform_api.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    echo "[INFO] Starting Celery worker"
    exec python -m celery -A src.platform_api.core.celery_app:celery_app worker \
      -Q testcase_generation,kb_parsing,export \
      --loglevel="${CELERY_LOG_LEVEL:-info}" \
      --pool=solo \
      --concurrency="${CELERY_WORKER_CONCURRENCY:-4}"
    ;;
  *)
    exec "$@"
    ;;
esac
