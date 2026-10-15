"""No paid calls: controlled API, evidence, quota, cache and failure tests."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aiseoonline_api.ai_core import (
    FixtureProvider,
    InvalidModelOutput,
    ProviderUnavailable,
    TokenUsage,
)
from aiseoonline_api.ai_core.meta_generator import MetaDraft, review_draft
from aiseoonline_api.ai_core import meta_routes
from aiseoonline_api.config import Settings
from aiseoonline_api.main import create_app

SOURCE = (
    "Handmade ceramic planters for indoor houseplants. "
    "Every planter is handmade by a local studio from natural clay. "
    "Customers can explore different shapes for small houseplants and "
    "learn about gentle indoor care and watering."
)
IDEAS = {
    "suggestions": [
        {
            "title": "Handmade Ceramic Planters for Indoor Plants",
            "description": "Explore handmade ceramic planters crafted from natural clay "
                           "for small indoor houseplants and discover gentle plant care tips.",
            "evidence_quote": "Handmade ceramic planters for indoor houseplants",
            "rationale": "Describes the core page topic clearly.",
        },
        {
            "title": "Natural Clay Planters and Indoor Plant Care",
            "description": "Discover natural clay planters made by a local studio, "
                           "with useful ideas for growing and watering houseplants indoors.",
            "evidence_quote": "Every planter is handmade by a local studio",
            "rationale": "Emphasizes the actual studio production.",
        },
        {
            "title": "Choose Small Ceramic Planters for Your Home",
            "description": "Browse shapes of ceramic planters for your indoor plants "
                           "and read gentle plant care advice to choose a suitable style.",
            "evidence_quote": "different shapes for small houseplants",
            "rationale": "Focuses on the available planter shapes.",
        },
    ]
}


def settings(**kwargs: Any) -> Settings:
    return Settings(
        _env_file=None, environment="test", openai_api_key="local-placeholder",
        redis_url="redis://localhost:6379/0",
        llm_input_usd_per_million=Decimal("0.5"),
        llm_output_usd_per_million=Decimal("2"),
        **kwargs,
    )


class FakeProvider:
    calls = 0

    async def complete(self, request: Any, *, schema: Any = None) -> Any:
        FakeProvider.calls += 1
        assert request.template_id == "meta_draft"
        assert request.website_text
        import json
        fixture = FixtureProvider(
            text=json.dumps(IDEAS),
            usage=TokenUsage(input_tokens=250, output_tokens=170, total_tokens=420),
        )
        return await fixture.complete(request, schema=schema)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    FakeProvider.calls = 0
    monkeypatch.setattr(meta_routes, "_check_peer", lambda *args: 2)
    monkeypatch.setattr(meta_routes, "_reserve_spend", lambda *args: True)
    monkeypatch.setattr(meta_routes, "make_openai_provider", lambda _: FakeProvider())
    return TestClient(create_app(settings()))


def test_pasted_content_returns_three_verified_suggestions(client: TestClient) -> None:
    response = client.post("/api/v1/tools/ai-meta", json={"content": SOURCE})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source_type"] == "text"
    assert result["cached"] is False
    assert len(result["suggestions"]) == 3
    assert result["usage"]["total_tokens"] == 420
    assert result["estimated_cost_usd"] is not None
    assert all("verify all factual claims" in " ".join(s["warnings"]) for s in result["suggestions"])
    assert FakeProvider.calls == 1


@pytest.mark.parametrize("value", [
    {}, {"url": "https://example.org/", "content": SOURCE},
    {"content": "tiny"}, {"content": " " * 160},
    {"url": "http://127.0.0.1/"}, {"url": "http://169.254.169.254/latest"},
    {"url": "file:///etc/passwd"},
])
def test_source_validation_rejects_bad_requests_before_provider(
    client: TestClient, value: dict[str, str]
) -> None:
    response = client.post("/api/v1/tools/ai-meta", json=value)
    assert response.status_code == 422
    assert FakeProvider.calls == 0


def test_missing_key_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    c = TestClient(create_app(Settings(_env_file=None, environment="test",
                                       redis_url="redis://localhost:6379/0",
                                       openai_api_key=None)))
    response = c.post("/api/v1/tools/ai-meta", json={"content": SOURCE})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"


def test_missing_price_rates_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    c = TestClient(create_app(Settings(_env_file=None, environment="test",
                                       openai_api_key="fixture-only",
                                       redis_url="redis://localhost:6379/0")))
    response = c.post("/api/v1/tools/ai-meta", json={"content": SOURCE})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_budget_not_configured"


def test_visitor_rate_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meta_routes, "_check_peer", lambda *a: -2)
    response = client.post("/api/v1/tools/ai-meta", json={"content": SOURCE})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "ai_rate_limited"
    assert response.headers["retry-after"] == "3600"
    assert FakeProvider.calls == 0


def test_global_daily_budget(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meta_routes, "_reserve_spend", lambda *a: False)
    response = client.post("/api/v1/tools/ai-meta", json={"content": SOURCE})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "ai_daily_budget_reached"
    assert FakeProvider.calls == 0


def test_failed_budget_service_never_calls_ai(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    def fail(*args: Any) -> bool:
        raise RedisConnectionError("private endpoint")

    monkeypatch.setattr(meta_routes, "_reserve_spend", fail)
    response = client.post("/api/v1/tools/ai-meta", json={"content": SOURCE})
    assert response.status_code == 503
    assert "private endpoint" not in response.text
    assert FakeProvider.calls == 0


def test_url_mode_uses_bounded_extracted_evidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(meta_routes, "_source_from_url",
                        lambda url: (SOURCE, "https://example.org/article"))
    monkeypatch.setattr(meta_routes, "_cache_key", lambda *args: None)
    response = client.post("/api/v1/tools/ai-meta",
                           json={"url": "https://example.org/article"})
    assert response.status_code == 200, response.text
    assert response.json()["source_url"] == "https://example.org/article"
    assert response.json()["source_type"] == "url"


def test_model_evidence_is_checked_against_actual_text() -> None:
    import copy
    bad = copy.deepcopy(IDEAS)
    bad["suggestions"][0]["evidence_quote"] = "A completely invented marketing claim"
    with pytest.raises(InvalidModelOutput):
        review_draft(MetaDraft.model_validate(bad), SOURCE)


def test_potentially_unsupported_numbers_and_claims_are_warned() -> None:
    import copy
    value = copy.deepcopy(IDEAS)
    value["suggestions"][0]["title"] = "Number One Ceramic Planters — 500 Sold"
    review = review_draft(MetaDraft.model_validate(value), SOURCE)
    assert any("numbers not found" in w for w in review[0].warnings)


def test_duplicate_suggestions_rejected() -> None:
    import copy
    bad = copy.deepcopy(IDEAS)
    bad["suggestions"][2]["title"] = bad["suggestions"][0]["title"]
    with pytest.raises(ValueError):
        MetaDraft.model_validate(bad)


def test_provider_error_is_not_exposed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(FakeProvider):
        async def complete(self, request: Any, *, schema: Any = None) -> Any:
            raise ProviderUnavailable("internal credentials are not to be shown")

    monkeypatch.setattr(meta_routes, "make_openai_provider", lambda _: Broken())
    response = client.post("/api/v1/tools/ai-meta", json={"content": SOURCE})
    assert response.status_code == 503
    assert "internal credentials" not in response.text


def test_price_allocation_is_conservative_and_bounded() -> None:
    cfg = settings()
    allocation = meta_routes._limits(cfg)
    assert allocation is not None
    assert 0 < allocation[0] <= int(cfg.ai_meta_request_usd_cap * 1_000_000)
    assert allocation[1] == 2_000_000
