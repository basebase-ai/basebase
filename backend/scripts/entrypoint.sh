#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [entrypoint] $*"
}

run_migrations="${RUN_DB_MIGRATIONS:-1}"
if [[ "$run_migrations" == "1" || "$run_migrations" == "true" || "$run_migrations" == "TRUE" ]]; then
  log "Running Alembic migrations (alembic upgrade head)."
  alembic upgrade head
  log "Alembic migrations complete."
else
  log "Skipping Alembic migrations because RUN_DB_MIGRATIONS=$run_migrations."
fi

log "Starting application command: $*"
exec "$@"
