"""Liveness endpoint that does not require any external dependencies."""

from fastapi import APIRouter
from pydantic import BaseModel

from aiseoonline_api import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse, summary="API liveness")
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="aiseoonline-api", version=__version__)
