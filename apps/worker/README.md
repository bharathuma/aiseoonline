# Worker

The worker handles long-running jobs separately from FastAPI. It uses the same Python package as the API and starts via `run.py`:

```bash
PYTHONPATH=apps/worker uv run --project apps/api celery -A run:celery_app worker --loglevel=INFO
```

Set `AISEO_REDIS_URL` before starting. The example task is `aiseoonline.ping`, registered in `aiseoonline_api.jobs`. It returns the input message and status; real crawl jobs will be added later. Use `docker compose up --build` for the configured Redis instance.

The process is terminated gracefully by Docker using SIGTERM and a stop grace period. Broker URLs and credentials must not be logged.
