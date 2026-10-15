"""Opt-in, privacy-allowlisted OTLP/HTTP JSON spans for collectors and Langfuse.

Only explicit primitive attributes are exported. No prompts, results, URLs, headers,
user identifiers, request bodies, exceptions or retrieved website content.
"""

import base64
import logging
import queue
import re
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

import httpx

from aiseoonline_api.config import Settings

logger = logging.getLogger("aiseoonline.telemetry")
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-01$")
_SAFE_ATTRIBUTES = frozenset(
    {
        "request_id",
        "job_id",
        "operation",
        "model",
        "template_id",
        "status",
        "error_code",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "retry_count",
        "duration_ms",
        "attempt",
    }
)
_SAFE_TEXT = re.compile(r"^[a-zA-Z0-9_.:-]{1,100}$")


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    request_id: str = "-"
    job_id: str = ""


_current: ContextVar[TraceContext | None] = ContextVar("ai_trace", default=None)
_exporter: "TelemetryExporter | None" = None


def current_traceparent() -> str | None:
    ctx = _current.get()
    if ctx is None or not ctx.span_id:
        return None
    return f"00-{ctx.trace_id}-{ctx.span_id}-01"


def _attributes(values: dict[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for key, value in values.items():
        if key not in _SAFE_ATTRIBUTES or value is None or isinstance(value, bool):
            continue
        if isinstance(value, int) and 0 <= value < 10**12:
            encoded: dict[str, object] = {"intValue": str(value)}
        elif isinstance(value, float) and 0 <= value < 10**12:
            encoded = {"doubleValue": value}
        elif isinstance(value, str) and _SAFE_TEXT.fullmatch(value):
            encoded = {"stringValue": value}
        else:
            continue
        result.append({"key": key, "value": encoded})
    return result


def _document(
    ctx: TraceContext,
    parent_id: str | None,
    name: str,
    began: int,
    ended: int,
    values: dict[str, object],
    failed: bool,
) -> dict[str, object]:
    attributes = _attributes(values)
    kind = {
        "ai.generate": "generation",
        "ai.stream": "generation",
        "audit.job": "agent",
        "audit.tool": "tool",
    }.get(name, "span")
    attributes.append({"key": "langfuse.observation.type", "value": {"stringValue": kind}})
    if kind == "generation":
        model = values.get("model")
        if isinstance(model, str) and _SAFE_TEXT.fullmatch(model):
            attributes.append({"key": "gen_ai.request.model", "value": {"stringValue": model}})
        for label, key in (("input_tokens", "input"), ("output_tokens", "output")):
            count = values.get(label)
            if type(count) is int and 0 <= count < 10**12:
                attributes.append(
                    {"key": f"gen_ai.usage.{key}_tokens", "value": {"intValue": str(count)}}
                )
    item: dict[str, object] = {
        "traceId": ctx.trace_id,
        "spanId": ctx.span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(began),
        "endTimeUnixNano": str(ended),
        "attributes": attributes,
        "status": {"code": 2 if failed else 1},
    }
    if parent_id:
        item["parentSpanId"] = parent_id
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "aiseoonline-api"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "aiseoonline.privacy", "version": "1"},
                        "spans": [item],
                    }
                ],
            }
        ]
    }


class TelemetryExporter:
    """Best-effort bounded queue; never delays an audit to contact monitoring hosts."""

    def __init__(self, settings: Settings) -> None:
        destinations: list[tuple[str, dict[str, str]]] = []
        if settings.otel_traces_endpoint:
            destinations.append(
                (settings.otel_traces_endpoint, {"Content-Type": "application/json"})
            )
        if settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key:
            public_key = settings.langfuse_public_key.get_secret_value()
            secret_key = settings.langfuse_secret_key.get_secret_value()
            pair = f"{public_key}:{secret_key}"
            credentials = base64.b64encode(pair.encode()).decode("ascii")
            destinations.append(
                (
                    settings.langfuse_host.rstrip("/") + "/api/public/otel/v1/traces",
                    {
                        "Content-Type": "application/json",
                        "Authorization": "Basic " + credentials,
                        "x-langfuse-ingestion-version": "4",
                    },
                )
            )
        self.destinations = destinations
        self.queue: queue.Queue[dict[str, object] | None] = queue.Queue(maxsize=256)
        self.failed_exports = 0
        self.dropped_spans = 0
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def emit(self, document: dict[str, object]) -> None:
        if not self.destinations:
            return
        try:
            self.queue.put_nowait(document)
        except queue.Full:
            self.dropped_spans += 1
            logger.warning("observability_queue_full")
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._drain, name="ai-telemetry", daemon=True
                )
                self._thread.start()

    def _drain(self) -> None:
        while True:
            try:
                document = self.queue.get(timeout=0.5)
            except queue.Empty:
                with self._lock:
                    if self.queue.empty():
                        self._thread = None
                        return
                continue
            if document is None:
                self.queue.task_done()
                return
            for url, headers in self.destinations:
                try:
                    with httpx.Client(
                        timeout=1.0, follow_redirects=False, trust_env=False
                    ) as client:
                        response = client.post(url, json=document, headers=headers)
                        response.raise_for_status()
                except (httpx.HTTPError, OSError):
                    self.failed_exports += 1
                    logger.warning("observability_export_failed")
            self.queue.task_done()


def configure_telemetry(settings: Settings) -> None:
    global _exporter
    _exporter = TelemetryExporter(settings)


@contextmanager
def trace_from_parent(
    parent: str | None, *, request_id: str = "-", job_id: str = ""
) -> Iterator[None]:
    """Only accept W3C sampled trace context persisted by our own API."""
    match = _TRACEPARENT.fullmatch(parent or "")
    ctx = (
        TraceContext(match.group(1), match.group(2), request_id, job_id)
        if match and match.group(1) != "0" * 32 and match.group(2) != "0" * 16
        else None
    )
    token = _current.set(ctx)
    try:
        yield
    finally:
        _current.reset(token)


@dataclass
class Span:
    attributes: dict[str, object] = field(default_factory=dict)

    def set(self, **attributes: object) -> None:
        self.attributes.update(attributes)


@contextmanager
def span(name: str, **attributes: object) -> Iterator[Span]:
    """Scope child spans and capture sanitized timings and outcome, even without an exporter."""
    previous = _current.get()
    trace_id = previous.trace_id if previous else secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    ctx = TraceContext(
        trace_id,
        span_id,
        request_id=previous.request_id if previous else "-",
        job_id=previous.job_id if previous else "",
    )
    token = _current.set(ctx)
    item = Span(dict(attributes))
    if ctx.request_id != "-":
        item.set(request_id=ctx.request_id)
    if ctx.job_id:
        item.set(job_id=ctx.job_id)
    began = time.time_ns()
    failed = False
    try:
        yield item
    except BaseException as exc:
        failed = True
        code = getattr(exc, "code", type(exc).__name__)
        item.set(status="error", error_code=code)
        raise
    finally:
        ended = time.time_ns()
        _current.reset(token)
        item.set(duration_ms=round((ended - began) / 1000000, 2))
        exporter = _exporter
        if exporter is not None:
            exporter.emit(
                _document(
                    ctx,
                    previous.span_id if previous else None,
                    name,
                    began,
                    ended,
                    item.attributes,
                    failed,
                )
            )


@contextmanager
def request_trace(request_id: str) -> Iterator[None]:
    token = _current.set(TraceContext(secrets.token_hex(16), "", request_id))
    try:
        yield
    finally:
        _current.reset(token)
