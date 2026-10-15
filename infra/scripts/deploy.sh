#!/usr/bin/env bash
# Explicit operator-only rollout; never invoked automatically by CI.
set -Eeuo pipefail
umask 077
stage="${1:-}"
if [[ "$stage" != "staging" && "$stage" != "production" ]]; then
  echo "Usage: CONFIRM_DEPLOY=DEPLOY_<STAGING|PRODUCTION> ... deploy.sh staging|production" >&2
  exit 2
fi
if [[ "${CONFIRM_DEPLOY:-}" != "DEPLOY_${stage^^}" ]]; then
  echo "Explicit CONFIRM_DEPLOY gate missing." >&2
  exit 2
fi
for name in AISEO_API_IMAGE AISEO_WEB_IMAGE AISEO_DB_PASSWORD AISEO_REDIS_PASSWORD AISEO_PUBLIC_ORIGIN AISEO_BACKUP_DIR; do
  if [[ -z "${!name:-}" ]]; then echo "Missing $name" >&2; exit 2; fi
done
if [[ ! "$AISEO_API_IMAGE" =~ @sha256:[a-f0-9]{64}$ || ! "$AISEO_WEB_IMAGE" =~ @sha256:[a-f0-9]{64}$ ]]; then
  echo "Both deployment images must be pinned to reviewed SHA-256 digests." >&2
  exit 2
fi
if [[ ! "$AISEO_PUBLIC_ORIGIN" =~ ^https://[a-zA-Z0-9.-]+$ ]]; then
  echo "Public origin must be a single HTTPS hostname." >&2
  exit 2
fi
if [[ "${AISEO_START_TUNNEL:-false}" == "true" ]]; then
  if [[ -z "${AISEO_CLOUDFLARED_TOKEN:-}" || ! "${AISEO_CLOUDFLARED_IMAGE:-}" =~ @sha256:[a-f0-9]{64}$ ]]; then
    echo "Tunnel requires a secret token and a digest-pinned image." >&2
    exit 2
  fi
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$root"
compose=(docker compose -f compose.yaml -f infra/compose.deploy.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" pull api worker migrate web
"${compose[@]}" up -d db redis
if [[ "${AISEO_FRESH_INSTALL:-false}" != "true" ]]; then
  bash infra/scripts/backup.sh "$AISEO_BACKUP_DIR"
else
  echo "Fresh install explicitly selected; no existing database backup created."
fi
# A failing migration stops the deployment before application images are replaced.
"${compose[@]}" up --no-build --force-recreate migrate
"${compose[@]}" up -d --no-build api worker web
if [[ "${AISEO_START_TUNNEL:-false}" == "true" ]]; then
  "${compose[@]}" --profile tunnel up -d tunnel
fi
for attempt in $(seq 1 30); do
  if curl --silent --show-error --fail --max-time 4 http://127.0.0.1:4321/api/v1/ready >/dev/null &&
     curl --silent --show-error --fail --max-time 4 http://127.0.0.1:4321/ >/dev/null; then
    echo "$stage rollout passed local origin readiness."
    exit 0
  fi
  sleep 3
done
echo "Origin readiness did not succeed; inspect logs and follow rollback runbook." >&2
exit 1
