"""Redacted OTLP generation, correlation, budgets and offline provider accounting."""

import asyncio
import json
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from aiseoonline_api import observability as obs
from aiseoonline_api.agents.execution import _BUDGET_LUA
from aiseoonline_api.ai_core.contracts import GenerationRequest, ModelPricing, TokenBudget
from aiseoonline_api.ai_core.meta_routes import _SPEND_SCRIPT
from aiseoonline_api.ai_core.openai_provider import OpenAIChatProvider
from aiseoonline_api.config import Settings


class Collector:
    def __init__(self):
        self.documents: list[dict[str, object]] = []

    def emit(self, document: dict[str, object]) -> None:
        self.documents.append(document)


def span_data(document: dict[str, object]) -> dict[str, object]:
    return document["resourceSpans"][0]["scopeSpans"][0]["spans"][0]


def test_correlation_across_worker_context_and_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = Collector()
    monkeypatch.setattr(obs, "_exporter", collector)
    with obs.request_trace("a" * 32):
        with obs.span("http.request", operation="api"):
            parent = obs.current_traceparent()
            assert parent is not None
            with obs.span("audit.dispatch", operation="schedule"):
                pass
    with obs.trace_from_parent(parent, request_id="a" * 32, job_id=str(uuid4())):
        with obs.span(
            "audit.job",
            operation="worker",
            prompt="PRIVATE WEBSITE CONTENT",
            url="https://private.example/page",
            api_key="sk-secret-should-not-appear",
        ):
            with obs.span("audit.node", operation="collect"):
                pass

    assert len(collector.documents) == 4
    spans = {item["name"]: item for item in map(span_data, collector.documents)}
    api = spans["http.request"]
    dispatch = spans["audit.dispatch"]
    worker = spans["audit.job"]
    node = spans["audit.node"]
    assert len({item["traceId"] for item in (api, dispatch, worker, node)}) == 1
    assert "parentSpanId" not in api
    assert dispatch["parentSpanId"] == api["spanId"]
    assert worker["parentSpanId"] == api["spanId"]
    assert node["parentSpanId"] == worker["spanId"]
    serialized = json.dumps(collector.documents)
    for forbidden in ("PRIVATE WEBSITE", "private.example", "sk-secret", "api_key", "prompt"):
        assert forbidden not in serialized
    assert "request_id" in serialized and "job_id" in serialized
    for item, expected in ((api, "span"), (worker, "agent"), (node, "span")):
        attrs = {attr["key"]: attr["value"] for attr in item["attributes"]}
        assert attrs["langfuse.observation.type"]["stringValue"] == expected
    assert obs.current_traceparent() is None


@pytest.mark.parametrize(
    "header",
    [
        "",
        "00-" + "0" * 32 + "-" + "1" * 16 + "-01",
        "00-" + "a" * 32 + "-" + "b" * 16 + "-00",
        "00-" + "a" * 32 + "-" + "b" * 16 + "-01,evil",
    ],
)
def test_invalid_parent_context_is_ignored(header: str) -> None:
    with obs.trace_from_parent(header):
        assert obs.current_traceparent() is None


def test_otel_and_langfuse_export_without_sensitive_body(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, dict[str, str], dict[str, object]]] = []

    class MockClient:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            sent.append((url, headers, json))
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(obs.httpx, "Client", MockClient)
    settings = Settings(
        _env_file=None,
        environment="test",
        otel_traces_endpoint="https://collector.example/v1/traces",
        langfuse_host="https://cloud.langfuse.com",
        langfuse_public_key="pk-test",
        langfuse_secret_key="private-key-fixture",
    )
    exporter = obs.TelemetryExporter(settings)
    with obs.request_trace("d" * 32):
        monkeypatch.setattr(obs, "_exporter", exporter)
        with obs.span(
            "ai.generate",
            model="gpt-4o-mini",
            input_tokens=45,
            output_tokens=9,
            secret_key="private-key-fixture",
            website_text="secret-data",
        ):
            pass
    exporter.queue.join()
    assert len(sent) == 2
    assert sent[0][0] == "https://collector.example/v1/traces"
    assert sent[1][0] == "https://cloud.langfuse.com/api/public/otel/v1/traces"
    assert sent[1][1]["x-langfuse-ingestion-version"] == "4"
    assert sent[1][1]["Authorization"].startswith("Basic ")
    payload = json.dumps([call[2] for call in sent])
    assert "private-key-fixture" not in payload
    assert "secret-data" not in payload
    assert "gen_ai.usage.input_tokens" in payload


def test_observability_outage_does_not_fail_business_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, *, json, headers):
            return httpx.Response(503, request=httpx.Request("POST", url))

    monkeypatch.setattr(obs.httpx, "Client", UnavailableClient)
    exporter = obs.TelemetryExporter(
        Settings(_env_file=None, otel_traces_endpoint="https://collector.example/v1/traces")
    )
    monkeypatch.setattr(obs, "_exporter", exporter)
    with obs.span("audit.tool", operation="headings"):
        result = "completed"
    exporter.queue.join()
    assert result == "completed"
    assert exporter.failed_exports == 1


def test_agent_tool_and_model_observation_types(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = Collector()
    monkeypatch.setattr(obs, "_exporter", collector)
    with obs.request_trace("b" * 32):
        for name in ("audit.tool", "ai.generate", "ai.stream"):
            with obs.span(name, operation="headings", model="gpt-4o-mini"):
                pass
    seen = {
        item["name"]: next(
            attr["value"]["stringValue"]
            for attr in item["attributes"]
            if attr["key"] == "langfuse.observation.type"
        )
        for item in map(span_data, collector.documents)
    }
    assert seen == {
        "audit.tool": "tool",
        "ai.generate": "generation",
        "ai.stream": "generation",
    }


def test_opt_in_configuration_fails_closed() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(_env_file=None, otel_traces_endpoint="http://localhost:4318/v1/traces")
    with pytest.raises(ValidationError, match="Langfuse requires"):
        Settings(_env_file=None, langfuse_host="https://cloud.langfuse.com")


def test_provider_real_usage_and_estimated_cost_span(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = Collector()
    monkeypatch.setattr(obs, "_exporter", collector)

    def answer(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "Verified"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140},
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            provider = OpenAIChatProvider(
                api_key="offline-fixture",
                model="gpt-4o-mini",
                budget=TokenBudget(
                    max_input_tokens=8192, max_output_tokens=256, max_total_tokens=8448
                ),
                pricing=ModelPricing(
                    input_usd_per_million=Decimal("1"), output_usd_per_million=Decimal("2")
                ),
                http_client=client,
            )
            with obs.request_trace("a" * 32):
                value = await provider.complete(
                    GenerationRequest(
                        task="Explain observed facts",
                        website_text="safe test",
                        max_output_tokens=128,
                    )
                )
            assert value.usage.total_tokens == 140
            assert value.cost_usd == Decimal("0.000160")

    asyncio.run(run())
    assert len(collector.documents) == 1
    span = span_data(collector.documents[0])
    attrs = {x["key"]: x["value"] for x in span["attributes"]}
    assert attrs["total_tokens"]["intValue"] == "140"
    assert attrs["retry_count"]["intValue"] == "0"
    assert Decimal(attrs["estimated_cost_usd"]["stringValue"]) == Decimal("0.000160")


@pytest.mark.integration
def test_atomic_owner_operation_and_global_redis_budgets() -> None:
    import os

    from redis import Redis
    from redis.exceptions import RedisError

    url = os.environ.get("AISEO_TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis service unavailable")
    prefix = "test:budget:" + uuid4().hex
    keys = [prefix + suffix for suffix in (":count", ":audit", ":owner", ":global", ":meta")]
    try:
        with Redis.from_url(url) as redis:
            assert redis.eval(_BUDGET_LUA, 4, *keys[:4], 3, 160, 500, 200, 300) == 1
            assert redis.eval(_BUDGET_LUA, 4, *keys[:4], 3, 160, 500, 200, 300) == -3
            assert redis.eval(_SPEND_SCRIPT, 2, keys[4], keys[3], 100, 200, 300) == 1
            assert redis.eval(_SPEND_SCRIPT, 2, keys[4], keys[3], 100, 200, 300) == -1
            assert int(redis.get(keys[3])) == 260
    except RedisError:
        pytest.skip("Redis is not reachable")
    finally:
        try:
            with Redis.from_url(url) as redis:
                redis.delete(*keys)
        except RedisError:
            pass
