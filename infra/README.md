# Infrastructure

`compose.yaml` starts five application services: the built Astro website, FastAPI API, Celery worker, one-shot Alembic migration, PostgreSQL with pgvector, and Redis (six services total).

Both PostgreSQL and Redis are accessible only inside the Compose network; frontend and API ports are bound to `127.0.0.1` by default. Generate unique passwords in `.env` before starting.

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(24))"   # generate twice
# Edit .env: set AISEO_DB_PASSWORD and AISEO_REDIS_PASSWORD to the generated values.
docker compose -f compose.yaml up --build -d
curl -fsS http://127.0.0.1:8000/api/v1/ready
curl -fsS http://127.0.0.1:4321/
```

Inspect `docker compose ps` and `docker compose logs api worker migrate` if services are unhealthy. Run a migration status check:

```bash
docker compose exec api alembic -c alembic.ini current
```

The first migration creates the pgvector extension; PostgreSQL must have the extension installed and the migration role must have permission to create extensions. `pgvector/pgvector:pg16` provides that extension. Production requires separately configured TLS, backups, least-privilege roles, secrets storage, and private worker egress restrictions. This Compose file is for **local development**, not an internet-exposed production deployment.

Docker volumes persist DB and Redis data. `docker compose down` keeps them; `docker compose down -v` irreversibly deletes local data.
