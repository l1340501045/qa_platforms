#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
ENV_FILE="${ROOT_DIR}/.env.prod"
STAMP="${1:-$(date +%Y%m%d-%H%M%S)}"
BACKUP_DIR="${ROOT_DIR}/backups/${STAMP}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERR] Missing .env.prod. Copy .env.prod.example and fill real values first." >&2
  exit 1
fi

cd "$ROOT_DIR"
mkdir -p "$BACKUP_DIR"

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

echo "[INFO] Backing up Postgres to ${BACKUP_DIR}/postgres.sql"
"${COMPOSE[@]}" exec -T postgres sh -c \
  'pg_dump --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "${BACKUP_DIR}/postgres.sql"

echo "[INFO] Backing up MinIO bucket to ${BACKUP_DIR}/minio"
"${COMPOSE[@]}" --profile tools run --rm -T -e BACKUP_STAMP="$STAMP" minio-client \
  'mc alias set local http://minio:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
   mkdir -p "/backups/$BACKUP_STAMP/minio"
   mc mirror --overwrite "local/$MINIO_BUCKET" "/backups/$BACKUP_STAMP/minio/$MINIO_BUCKET"'

{
  echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git_commit=$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || true)"
  echo "compose_file=docker-compose.prod.yml"
} > "${BACKUP_DIR}/metadata.txt"

echo "[OK] Backup written to ${BACKUP_DIR}"
