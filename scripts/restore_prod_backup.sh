#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
ENV_FILE="${ROOT_DIR}/.env.prod"

if [[ $# -ne 1 ]]; then
  echo "Usage: CONFIRM_RESTORE=1 $0 <backup-stamp-or-backups-path>" >&2
  exit 1
fi

if [[ "${CONFIRM_RESTORE:-}" != "1" ]]; then
  echo "[ERR] Restore overwrites database objects and MinIO files. Re-run with CONFIRM_RESTORE=1." >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERR] Missing .env.prod. Copy .env.prod.example and fill real values first." >&2
  exit 1
fi

cd "$ROOT_DIR"
BACKUP_ARG="$1"
BACKUP_STAMP="$(basename "$BACKUP_ARG")"
BACKUP_DIR="${ROOT_DIR}/backups/${BACKUP_STAMP}"

if [[ -d "$BACKUP_ARG" ]]; then
  BACKUP_DIR="$(cd "$BACKUP_ARG" && pwd)"
  BACKUP_STAMP="$(basename "$BACKUP_DIR")"
fi

if [[ ! -f "${BACKUP_DIR}/postgres.sql" ]]; then
  echo "[ERR] Missing ${BACKUP_DIR}/postgres.sql" >&2
  exit 1
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

echo "[INFO] Restoring Postgres from ${BACKUP_DIR}/postgres.sql"
"${COMPOSE[@]}" exec -T postgres sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "${BACKUP_DIR}/postgres.sql"

if [[ -d "${BACKUP_DIR}/minio" ]]; then
  echo "[INFO] Restoring MinIO objects from ${BACKUP_DIR}/minio"
  "${COMPOSE[@]}" --profile tools run --rm -T -e BACKUP_STAMP="$BACKUP_STAMP" minio-client \
    'mc alias set local http://minio:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
     mc mirror --overwrite "/backups/$BACKUP_STAMP/minio/$MINIO_BUCKET" "local/$MINIO_BUCKET"'
else
  echo "[WARN] ${BACKUP_DIR}/minio not found; skipped MinIO restore"
fi

echo "[OK] Restore finished from ${BACKUP_DIR}"
