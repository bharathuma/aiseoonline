"""Shared API error contract. User-provided values are never echoed in errors."""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aiseoonline_api.logging import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


class FieldIssue(BaseModel):
    field: str
    issue: str


class ApiError(BaseModel):
    code: str
    message: str
    details: list[FieldIssue] | None = None


class ErrorResponse(BaseModel):
    error: ApiError
    request_id: str = Field(description="Server-generated request correlation ID")


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Bad request"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    405: {"model": ErrorResponse, "description": "Method not allowed"},
    422: {"model": ErrorResponse, "description": "Validation failed"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
    503: {"model": ErrorResponse, "description": "Service unavailable"},
}

HTTP_ERRORS: dict[int, tuple[str, str]] = {
    400: ("bad_request", "The request could not be processed."),
    401: ("unauthorized", "Authentication is required."),
    403: ("forbidden", "Access denied."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "This HTTP method is not supported."),
    409: ("conflict", "The request conflicts with the current resource state."),
    429: ("rate_limited", "Too many requests."),
    503: ("service_unavailable", "The service is temporarily unavailable."),
}


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[FieldIssue] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unavailable")
    body = ErrorResponse(
        error=ApiError(code=code, message=message, details=details),
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers={"X-Request-ID": request_id},
    )


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    code, message = HTTP_ERRORS.get(
        exc.status_code, ("http_error", "The request could not be completed.")
    )
    response = error_response(request, exc.status_code, code, message)
    # Preserve only standardized protocol headers; arbitrary detail may be private.
    for key, value in (exc.headers or {}).items():
        if key.lower() in ("www-authenticate", "retry-after", "allow"):
            response.headers[key] = value
    return response


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    issues: list[FieldIssue] = []
    for error in exc.errors():
        location = ".".join(
            str(part) for part in error.get("loc", ()) if isinstance(part, str | int)
        )
        kind = error.get("type", "invalid")
        issues.append(
            FieldIssue(
                field=location[:160] if location else "request",
                issue=kind if isinstance(kind, str) and kind.isidentifier() else "invalid",
            )
        )
    return error_response(
        request,
        422,
        "validation_error",
        "One or more request fields are invalid.",
        details=issues[:25],
    )


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Never log exception text, body, headers, query string or full stack traces.
    logger.error(
        "Unhandled API failure for request_id=%s",
        getattr(request.state, "request_id", "unavailable"),
    )
    return error_response(
        request,
        500,
        "internal_error",
        "An unexpected error occurred. Please try again later.",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unexpected_error)
