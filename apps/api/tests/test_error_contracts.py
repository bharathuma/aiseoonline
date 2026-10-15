"""Error payloads must be predictable without revealing rejected values."""

import logging
import re
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from aiseoonline_api.config import Settings
from aiseoonline_api.errors import ErrorResponse
from aiseoonline_api.logging import LOGGER_NAME, PrivacyFilter, configure_logging, redact
from aiseoonline_api.main import create_app

REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None, environment="test"))

    class Input(BaseModel):
        size: int = Field(gt=0, le=10)

    @app.post("/api/v1/__test/validate")
    def validate(body: Input) -> Input:
        return body

    @app.get("/api/v1/__test/forbidden")
    def forbidden() -> None:
        raise HTTPException(status_code=403, detail="password=private-credential")

    @app.get("/api/v1/__test/crash")
    def crash() -> None:
        raise RuntimeError("secret=internal-private-detail")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_request_ids_are_random_and_cannot_be_spoofed(client: TestClient) -> None:
    first = client.get("/api/v1/health", headers={"X-Request-ID": "external-value"})
    second = client.get("/api/v1/health")
    assert first.status_code == 200
    assert REQUEST_ID.fullmatch(first.headers["x-request-id"])
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    assert first.headers["x-request-id"] != "external-value"


def test_unknown_resource_uses_shared_error_schema(client: TestClient) -> None:
    result = client.get("/api/v1/missing")
    assert result.status_code == 404
    envelope = ErrorResponse.model_validate(result.json())
    assert envelope.error.code == "not_found"
    assert envelope.request_id == result.headers["x-request-id"]


def test_method_not_allowed_preserves_allow_header(client: TestClient) -> None:
    result = client.post("/api/v1/health")
    assert result.status_code == 405
    assert result.json()["error"]["code"] == "method_not_allowed"
    assert "GET" in result.headers["allow"]


def test_validation_never_echoes_rejected_values(client: TestClient) -> None:
    result = client.post(
        "/api/v1/__test/validate",
        json={"size": -5, "secret": "sk-dangerous-secret-value"},
    )
    assert result.status_code == 422
    assert result.json()["error"]["details"] == [
        {"field": "body.size", "issue": "greater_than"}
    ]
    assert "dangerous" not in result.text
    assert REQUEST_ID.fullmatch(result.json()["request_id"])


def test_http_exception_does_not_echo_arbitrary_detail(client: TestClient) -> None:
    result = client.get("/api/v1/__test/forbidden")
    assert result.status_code == 403
    assert result.json()["error"]["code"] == "forbidden"
    assert "private-credential" not in result.text


def test_500_does_not_include_exception_or_traceback(client: TestClient) -> None:
    result = client.get("/api/v1/__test/crash")
    assert result.status_code == 500
    assert result.json()["error"]["code"] == "internal_error"
    assert "internal-private-detail" not in result.text
    assert "Traceback" not in result.text
    assert result.json()["request_id"] == result.headers["x-request-id"]


def test_openapi_describes_error_envelopes(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json").json()
    responses = schema["paths"]["/api/v1/health"]["get"]["responses"]
    assert responses["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorResponse"
    )
    assert responses["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorResponse"
    )


def test_redaction_masks_common_credentials() -> None:
    original = (
        "Bearer secretBearer password=hunter2 "
        "redis://user:redispass@localhost:6379/0 sk-secret-example-key"
    )
    masked = redact(original)
    assert "secretBearer" not in masked
    assert "hunter2" not in masked
    assert "redispass" not in masked
    assert "sk-secret-example-key" not in masked


def test_application_logger_sanitizes_formatted_messages() -> None:
    record = logging.LogRecord(
        LOGGER_NAME, logging.INFO, "test", 1, "api_key=%s", ("private-secret",), None
    )
    assert PrivacyFilter().filter(record)
    assert record.getMessage() == "api_key=[REDACTED]"
    assert record.request_id == "-"
    assert configure_logging("INFO").name == LOGGER_NAME
