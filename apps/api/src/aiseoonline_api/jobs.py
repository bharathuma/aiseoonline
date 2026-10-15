"""Celery application factory and a minimal verifiable example task."""

from uuid import UUID

from celery import Celery
from sqlalchemy.orm import Session

from aiseoonline_api.agents.execution import overdue_jobs
from aiseoonline_api.agents.runner import execute_audit_job
from aiseoonline_api.config import Settings
from aiseoonline_api.db.session import create_database_engine


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

    @app.task(name="aiseoonline.audit.execute", acks_late=True, reject_on_worker_lost=True)
    def execute_audit(identifier: str) -> str:
        return execute_audit_job(UUID(identifier), settings=settings)

    @app.task(name="aiseoonline.audit.recover")
    def recover_audits() -> int:
        if not settings.audit_jobs_enabled or settings.environment == "production":
            return 0
        engine = create_database_engine(settings)
        try:
            with Session(engine) as session, session.begin():
                identifiers = overdue_jobs(session)
            for identifier in identifiers:
                app.send_task("aiseoonline.audit.execute", args=[str(identifier)])
            return len(identifiers)
        finally:
            engine.dispose()

    if settings.audit_jobs_enabled and settings.environment != "production":
        # Run celery beat separately alongside the worker to repair lost publishes/crashes.
        app.conf.beat_schedule = {
            "recover-private-audits": {
                "task": "aiseoonline.audit.recover",
                "schedule": 15.0,
            }
        }
    app.conf.task_time_limit = 90
    app.conf.task_soft_time_limit = 80

    return app
