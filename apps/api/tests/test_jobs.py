"""Celery task tests without a broker; Redis integration tests live separately."""

import pytest

from aiseoonline_api.config import Settings


def test_example_task_works_in_eager_mode() -> None:
    pytest.importorskip("celery")
    from aiseoonline_api.jobs import create_celery_app

    app = create_celery_app(Settings(_env_file=None, environment="test", redis_url="memory://"))
    app.conf.update(
        task_always_eager=True, task_store_eager_result=True, result_backend="cache+memory://"
    )
    result = app.tasks["aiseoonline.ping"].delay("test")
    assert result.get(timeout=5) == {"status": "ok", "message": "test"}


def test_missing_redis_configuration_raises() -> None:
    pytest.importorskip("celery")
    from aiseoonline_api.jobs import create_celery_app

    with pytest.raises(RuntimeError, match="AISEO_REDIS_URL"):
        create_celery_app(Settings(_env_file=None, redis_url=None))
