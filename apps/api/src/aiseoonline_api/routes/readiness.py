"""External dependency readiness. Liveness remains independent."""

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(tags=["health"])


class ReadinessResponse(BaseModel):
    status: str
    database: str
    redis: str


@router.get("/ready", response_model=ReadinessResponse, summary="Database and Redis readiness")
def ready(request: Request, response: Response) -> ReadinessResponse:
    settings = request.app.state.settings
    engine = request.app.state.database_engine
    if settings.redis_url is None or engine is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="unavailable", database="unconfigured", redis="unconfigured"
        )

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable", database="unavailable", redis="unchecked")

    # Import lazily, so liveness and the API docs don't require Redis connectivity.
    import redis

    try:
        client = redis.Redis.from_url(
            settings.require_redis_url(), socket_connect_timeout=2, socket_timeout=2
        )
        try:
            if not client.ping():
                raise redis.RedisError("Redis ping failed")
        finally:
            client.close()
    except (redis.RedisError, OSError, ValueError):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable", database="ok", redis="unavailable")

    return ReadinessResponse(status="ready", database="ok", redis="ok")
