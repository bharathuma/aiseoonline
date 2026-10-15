# Private-origin deployment and recovery

This runbook describes a **prepared, gated deployment**, not a deployed website.
The existing Astro application is statically generated and served by unprivileged
Nginx. FastAPI and Celery run in separate non-root containers. PostgreSQL with
pgvector and Redis remain on an internal network. Cloudflare handles public DNS,
TLS, CDN and WAF; a **remotely managed Cloudflare Tunnel** can connect only to
the web container's port 8080 over the Docker edge network. No public inbound
port, database port, Redis port, or direct origin DNS record is required.

The production-mode overlay is `infra/compose.deploy.yaml`, used **together**
with `compose.yaml`. It does not change the default local development stack.
The project has no separate `staging` application mode: staging intentionally
runs `AISEO_ENVIRONMENT=production` to exercise all production prohibitions.

## Prerequisites and manually provisioned infrastructure

1. A Linux Docker host with current Docker Engine and Docker Compose v2.24.4 or newer (for explicit\n   `!override` network replacement), disk/CPU/RAM
   monitored, outbound DNS/TLS, host firewall, encrypted off-host backup storage,
   protected operator access, and a separately reviewed outbound egress policy.
   Do **not** expose the bound ports 127.0.0.1:4321 or 127.0.0.1:8000 publicly.
2. Cloudflare DNS zone under your control. Create separate staging and production
   tunnels with independently rotated credentials. In the Cloudflare dashboard
   map the chosen public hostname to `http://web:8080` as reached by the tunnel
   container; use HTTPS for visitors, redirects to HTTPS, reasonable WAF and bot
   controls, and strict edge TLS. Never publish the private origin IP as a
   public DNS A/AAAA record. Test the actual tunnel URL separately.
3. GitHub repository admin configures protected **staging** and **production**
   Environments, with required reviewers (especially for production), restricts
   releases to the protected `main` branch, and protects `main` using required
   foundation, infrastructure, dependency and deployment smoke checks. None of
   these repository settings are silently enabled by source code.
4. Separate stage-specific credentials for DB, Redis, Cloudflare Tunnel,
   GHCR pull-only access and any optional paid model keys. Do not store secrets
   in GitHub PRs, unencrypted backups, published environment examples or Docker
   build arguments. Run approved secrets injection via a private 0600 file or
   external secret manager; `docker inspect` may expose environment variables
   to privileged Docker-host operators. Limit Docker daemon access.
5. Disk monitoring, database snapshots, backup encryption/off-host copies,
   restore exercises, image vulnerability review and resource alerts. Database
   and Redis Docker volumes are **not** backups. Set independent monitoring for
   5xx, readiness, tunnel disconnects, queue depth, long Celery jobs, Redis
   memory, DB disk/connection capacity, backup age, certificate health and
   unexpected spend.

**Important production blocker:** the current Compose database initializes
`aiseoonline` as the PostgreSQL bootstrap superuser, and the app uses that
same role for runtime and migrations. Before storing private production
customer data, separate migration/bootstrap credentials from restricted runtime
DB credentials (or use a managed PostgreSQL service with pgvector), enforce
network-level metadata/private-CIDR egress denials, and confirm source-IP
handling for quotas behind Cloudflare Tunnel. Docker network separation and
app-level SSRF guards do not replace host firewall policy.

## Test without server or domain credentials

From the repository root, with locally generated non-production passwords:

```sh
export AISEO_DB_PASSWORD="$(openssl rand -hex 24)"
export AISEO_REDIS_PASSWORD="$(openssl rand -hex 24)"
export AISEO_PUBLIC_ORIGIN=https://staging.aiseoonline.com
bash -n infra/scripts/*.sh
docker compose -f compose.yaml -f infra/compose.deploy.yaml config --quiet
docker compose -f compose.yaml -f infra/compose.deploy.yaml config --format json > /tmp/aiseoonline-resolved.json
python3 infra/scripts/verify_compose.py /tmp/aiseoonline-resolved.json
docker compose -f compose.yaml -f infra/compose.deploy.yaml up --build -d
python3 infra/scripts/verify_origin.py http://127.0.0.1:4321
docker compose -f compose.yaml -f infra/compose.deploy.yaml down -v --remove-orphans
```

**Never run `down -v` for a real staging or production database:** it deletes
persistent PostgreSQL and Redis data. The command above applies only to a fresh,
isolated and disposable local test environment. The GitHub Actions deployment
smoke workflow performs the same disposable test and exercises worker/Celery
readiness and applied migrations. It does not contact real Cloudflare or VPS hosts.

## Build/publish and manual release

A `workflow_dispatch` GitHub Action called
[Publish reviewed container artifacts](../.github/workflows/release-artifacts.yml)
accepts `target=staging|production` and `confirm=PUBLISH_IMAGES`. It runs
locked-source checks from `main`, requires the configured protected GitHub
Environment before publication and publishes two OCI images to GHCR. It has
**no SSH key, tunnel secret or deployment command**, and never deploys.
An operator copies the **image digests**, not mutable tags, from its job
summary. Both image references must contain `@sha256:<64 hex>`.

On a separate secured host prepare and validate a private 0600 env file based
on `infra/environments/staging.env.example` or
`infra/environments/production.env.example`. Supply new random hexadecimal
DB and Redis passwords and exact image digests. Use unique names, volumes and
hosts for staging and production: the Compose project is named `aiseoonline`
by the base file, so **do not run both environments on the same Docker daemon
without independent Compose projects and ports**. The examples are templates,
not secret stores. Review values using a secret manager where possible.

Only after explicit operator approval:

```sh
# Run in a trusted shell on the intended host; private file must be 0600.
set -a
source /path/to/private/staging.env
set +a
install -d -m 0700 "$AISEO_BACKUP_DIR"
export CONFIRM_DEPLOY=DEPLOY_STAGING
bash infra/scripts/deploy.sh staging
```

For production use a separate host/configuration and
`CONFIRM_DEPLOY=DEPLOY_PRODUCTION bash infra/scripts/deploy.sh production`
after reviewing staging and preparing an independent verified backup.
`AISEO_FRESH_INSTALL=true` is permitted **only** for an explicitly confirmed
empty data store. By default the script starts PostgreSQL/Redis and **requires
a successful database backup** before migrations or application replacement.
The sequence pulls both immutable images, creates a private backup, applies
Alembic migrations, starts API/worker/web with `--no-build`, and polls
loopback origin readiness. It refuses missing inputs and non-digest images.
The Cloudflare Tunnel starts only when `AISEO_START_TUNNEL=true` and both
a real token and digest-pinned tunnel image are configured. Inspect the
Cloudflare dashboard route after starting the tunnel.

**Release race policy:** accept only one operator at a time. Do not run
deployments, schema migrations and restores concurrently. Coordinate with
background worker leases and queues before structural migrations; design all
schema changes to be compatible with both previous and new code until the
rollout is complete.

## Backups, disaster recovery and rollback

The command below creates a custom-format PostgreSQL dump and SHA-256 sidecar,
mode 0600, under an already protected 0700 directory. Docker Compose's
`exec -T` prevents binary-stream corruption:

```sh
bash infra/scripts/backup.sh "$AISEO_BACKUP_DIR"
```

Encrypt each dump with an operator-managed key and copy off-host. Retain a
daily schedule (e.g. a host timer that alerts on failure), a documented
retention period based on privacy policy and *regular isolated restore tests*.
Back up and restore **Redis persistence** separately only when required for
durable Celery queues/rate limits; otherwise deliberately reconcile/requeue
jobs and accept Redis cache/counter loss. Document any job loss. For serious
production use, database PITR/WAL backups and object-storage history are
recommended: nightly `pg_dump` alone is **not** point-in-time recovery.

Rollback application images only by switching environment variables to
previous reviewed **digests** and rerunning the controlled rollout. **Do
not assume an older image can read a newer schema**. Expand/contract
migrations or restore a compatible database backup in an isolated recovery
environment before opening access. A restore is destructive:

```sh
# First stop all API/worker clients and verify a separate pre-restore backup.
docker compose -f compose.yaml -f infra/compose.deploy.yaml stop api worker web
export CONFIRM_RESTORE=RESTORE
bash infra/scripts/restore.sh /secure/backups/postgres-verified.dump
```

This script requires a verified SHA-256 sidecar and refuses a restore if the
API or worker still has a container ID. Complete the restore while offline,
check current Alembic migration version and app compatibility, test counts
and data integrity on a staging copy first, and only then restart workloads.
The script does not restore LangGraph external checkpoints, object storage,
Redis append-only state, secrets, or DNS. Their recovery is a separate
operator responsibility.

Recovery priorities: protect customer data and revoke compromised keys,
preserve forensic logs, stop new jobs, assess backup integrity, restore an
isolated staging copy, then re-enable traffic after approval. The deployment
does not configure automatic backup scheduling or off-site storage for you.

## Post-deployment external verification

On the selected public hostname (only after authorized tunnel setup):

- Check TLS validity and HTTPS-only redirects, Cloudflare DNS proxy/WAF
  settings, expected origin hostname, and **no** direct internet ingress.
- Confirm `/api/v1/health` and `/api/v1/ready` return healthy responses.
  Readiness tests PostgreSQL and Redis. API liveness uses `/health` so a
  short dependency outage cannot cause needless application restart loops.
- Confirm nine public SEO routes and normal anonymous quotas, 4xx for
  unsafe URLs, 401 for unauthenticated account data; private audit/RAG routes
  must be **absent** in production. No AI key means paid API tools must
  clearly reject the request, not pretend it succeeded.
- Verify HTTP headers on **actual Cloudflare responses**: HTML
  `must-revalidate`, fingerprinted `/_astro/*` immutable, **all**
  `/api/*` non-cacheable, no private responses or session cookies in CDN.
  Configure HSTS/modern TLS at Cloudflare; do not claim the local HTTP
  tunnel origin provides HTTPS itself. Add a tested CSP when inline script
  requirements have been audited.
- Simulate a stopped worker, failed Redis/DB connection, invalid migration,
  revoked session, and tunnel disconnect in **staging only**; ensure alerts
  and rollback instructions work. Confirm disk, memory, worker capacity,
  backup and AI spend alarms. Perform a runbook-reviewed DB restore test.

## Limitations and open infrastructure controls

- The private audit and RAG routes are **intentionally disabled in
  production** and multi-page scans cannot be safely exposed yet. This
  deployment does not bypass authorization or unlock new paid features.
- Cloudflare Tunnel and origin Nginx currently make requests appear to
  share a proxy IP to the FastAPI backend. The backend's per-peer quotas
  therefore **cannot be claimed accurate per visitor behind Cloudflare**
  until a verified, explicitly trusted client IP forwarding strategy is
  implemented and tested. Do not accept arbitrary client-supplied
  `CF-Connecting-IP` or `X-Forwarded-For` headers. Apply edge-level
  per-visitor rate limits temporarily and resolve the app layer before
  a public launch.
- Deny outbound metadata (`169.254.169.254`, IPv6 link local), private
  and reserved network destinations at **host/VPC/firewall**, including
  redirects, and restrict worker outbound access. Docker bridges alone
  are not SSRF egress policy.
- Lock down staging independently, including robots/noindex or Cloudflare
  Access, to avoid SEO duplication and unauthorized tests. Neither route
  nor Access policy is created by this code.
- Container source base images are still tag-based upstream. Lock reviewed
  image digests, scan SBOMs, and update intentionally when upgrading.
  GHCR build output images are content-addressable but this does not prove
  fully reproducible upstream source layers.
- Resource sizes and queue concurrency are provisional operator defaults.
  They are not measured production sizing. Set alert thresholds only from
  real measurements.
- These scripts assume Linux/GNU utilities, Docker Compose v2, and a
  trusted operator. They do not provision a VPS, DNS zone, WAF, secrets
  manager, SMTP, external backup service, server firewall or telemetry
  subscription.
