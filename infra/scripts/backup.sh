#!/usr/bin/env bash
# Backup a running PostgreSQL container to a private host directory.
set -Eeuo pipefail
umask 077

if [[ "${1:-}" == "" || ! -d "${1:-}" || -L "${1:-}" ]]; then
  echo "Provide an existing, private backup directory." >&2
  exit 2
fi
directory="$(cd "$1" && pwd -P)"
if [[ "$(stat -c %a "$directory")" != "700" ]]; then
  echo "Backup directory must have mode 0700." >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$root"
compose=(docker compose -f compose.yaml -f infra/compose.deploy.yaml)
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="$(mktemp "$directory/.postgres-${timestamp}-XXXXXXXX.dump")"
trap 'rm -f "$temporary"' EXIT
# -T is required: a pseudo-TTY corrupts the custom-format binary backup stream.
"${compose[@]}" exec -T db sh -c \
  'export PGPASSWORD="$POSTGRES_PASSWORD"; exec pg_dump -h 127.0.0.1 -U aiseoonline -d aiseoonline -Fc --no-owner --no-acl' \
  > "$temporary"
test -s "$temporary"
chmod 600 "$temporary"
final="$directory/postgres-${timestamp}-$(openssl rand -hex 6).dump"
mv -n "$temporary" "$final"
sha256sum "$final" > "$final.sha256"
chmod 600 "$final.sha256"
trap - EXIT
echo "Database backup: $final"
echo "Checksum: $final.sha256"
echo "Encrypt and copy backups off-host using an operator-managed key."
