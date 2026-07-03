#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
BACKUP_ROOT="${ROOT_DIR}/scripts/backups/run-guard"
PG_CONTAINER="qa-platforms-infra-postgres-1"
DB_DUMP_CONTAINER_HOST="localhost"
LABEL=""
RUN_CMD=()

usage() {
  cat <<'EOF'
Usage:
  ./scripts/run_batch_with_backup.sh [--label text] -- <batch command...>
  ./scripts/run_batch_with_backup.sh --help

Examples:
  ./scripts/run_batch_with_backup.sh -- uv run python scripts/reverify_batch.py 278c211f-6f25-4970-a425-9db94cbc8ff7
  ./scripts/run_batch_with_backup.sh --label 20260703 -- uv run python -m pytest tests/...

What it does:
  1) ensure .env exists
  2) export PostgreSQL connection from DATABASE_URL
  3) perform PostgreSQL pre-run backup
  4) run your batch command
EOF
}

while (($# > 0)); do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --label)
      LABEL="${2:-}"
      shift 2
      ;;
    --)
      shift
      RUN_CMD=("$@")
      break
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERR] Missing ${ENV_FILE}"
  exit 1
fi
if [[ ! -s "$ENV_FILE" ]]; then
  echo "[ERR] ${ENV_FILE} is empty"
  exit 1
fi

set -o allexport
source "$ENV_FILE"
set +o allexport

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[ERR] DATABASE_URL not set in ${ENV_FILE}"
  exit 1
fi

read -r DB_USER DB_PASS DB_HOST DB_PORT DB_NAME <<<"$(
python - <<'PY'
import sys
import urllib.parse

u = urllib.parse.urlsplit(sys.argv[1])
print(
    u.username or "",
    u.password or "",
    u.hostname or "localhost",
    str(u.port or "5432"),
    (u.path or "/").lstrip("/") or "qa_platforms",
)
PY
"$DATABASE_URL"
)"

if ! docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
  echo "[ERR] Postgres container not running: ${PG_CONTAINER}"
  echo "Hint: docker compose -f docker-compose.infra.yml up -d"
  exit 1
fi

mkdir -p "${BACKUP_ROOT}"

if [[ "${DB_HOST}" == "localhost" || "${DB_HOST}" == "127.0.0.1" ]]; then
  DB_DUMP_CONTAINER_HOST="localhost"
else
  DB_DUMP_CONTAINER_HOST="${DB_HOST}"
fi
STAMP="$(date '+%Y%m%d_%H%M%S')"
if [[ -n "$LABEL" ]]; then
  SAFE_LABEL="$(echo "$LABEL" | tr -cs 'A-Za-z0-9._-' '_')"
  BACKUP_FILE="${BACKUP_ROOT}/db_${SAFE_LABEL}_${STAMP}.sql.gz"
else
  BACKUP_FILE="${BACKUP_ROOT}/db_${STAMP}.sql.gz"
fi

if [[ -z "$DB_USER" ]]; then
  echo "[ERR] Cannot parse user from DATABASE_URL"
  exit 1
fi
if [[ -z "$DB_NAME" ]]; then
  echo "[ERR] Cannot parse database name from DATABASE_URL"
  exit 1
fi

echo "[INFO] Pre-run backup to: ${BACKUP_FILE}"
if command -v gzip >/dev/null 2>&1; then
  docker exec -e PGPASSWORD="${DB_PASS}" "${PG_CONTAINER}" \
    pg_dump -U "${DB_USER}" -h "${DB_DUMP_CONTAINER_HOST}" -p "${DB_PORT}" "${DB_NAME}" \
    | gzip > "${BACKUP_FILE}"
else
  docker exec -e PGPASSWORD="${DB_PASS}" "${PG_CONTAINER}" \
    pg_dump -U "${DB_USER}" -h "${DB_DUMP_CONTAINER_HOST}" -p "${DB_PORT}" "${DB_NAME}" \
    > "${BACKUP_FILE}"
fi
echo "[INFO] Backup done."

if [[ "${#RUN_CMD[@]}" -eq 0 ]]; then
  echo "[WARN] No batch command provided. Backup finished only."
  echo "[INFO] Example: ${0} -- uv run python scripts/reverify_batch.py <batch_id>"
  exit 0
fi

echo "[INFO] Run command: ${RUN_CMD[*]}"
(cd "${ROOT_DIR}" && "${RUN_CMD[@]}")
echo "[INFO] Done."
