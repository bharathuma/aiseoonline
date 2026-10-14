"""Celery application factory and a minimal verifiable example task."""

from celery import Celery

from aiseoonline_api.config import Settings


def create_celery_app(settings: Settings) -> Celery:
    broker_url = settings.require_redis_url()
    if settings.environment != "test" and not broker_url.startswith(("redis://", "rediss://")):
        raise ValueError("AISEO_REDIS_URL must use redis:// or rediss://")
    app = Celery("aiseoonline", broker=broker_url, backend=broker_url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        result_expires=3600,
    )

    @app.task(name="aiseoonline.ping")
    def ping(message: str = "hello") -> dict[str, str]:
        return {"status": "ok", "message": message}

    return app
