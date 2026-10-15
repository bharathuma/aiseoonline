#!/usr/bin/env bash
# Destructive restore requires operator control and an isolated target.
set -Eeuo pipefail
umask 077
file="${1:-}"
if [[ -z "$file" || ! -f "$file" || -L "$file" || "${CONFIRM_RESTORE:-}" != "RESTORE" ]]; then
  echo "Provide a regular .dump file and set CONFIRM_RESTORE=RESTORE." >&2
  exit 2
fi
if [[ ! -f "$file.sha256" ]]; then
  echo "Refusing restore without a matching SHA-256 sidecar." >&2
  exit 2
fi
(cd "$(dirname "$file")" && sha256sum -c "$(basename "$file").sha256")
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$root"
compose=(docker compose -f compose.yaml -f infra/compose.deploy.yaml)
if [[ -n "$("${compose[@]}" ps -q api)" || -n "$("${compose[@]}" ps -q worker)" ]]; then
  echo "Stop API and workers (and any other database clients) before restoring." >&2
  exit 2
fi
"${compose[@]}" exec -T db sh -c \
  'export PGPASSWORD="$POSTGRES_PASSWORD"; exec pg_restore -h 127.0.0.1 -U aiseoonline -d aiseoonline --clean --if-exists --exit-on-error --no-owner --no-acl' \
  < "$file"
echo "Restore completed. Check Alembic revision, permissions and application readiness."
