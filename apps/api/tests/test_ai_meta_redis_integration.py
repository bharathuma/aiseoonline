"""Real Redis budget atomicity tests when CI has the integration service."""

import hashlib
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aiseoonline_api.ai_core.meta_routes import _check_peer, _reserve_spend


@pytest.mark.integration
def test_ai_visitor_quota_is_atomic_across_requests() -> None:
    url = os.environ.get("AISEO_TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis integration URL is not configured")
    from redis import Redis

    peer = "integration-" + uuid4().hex
    hashed = hashlib.sha256(peer.encode()).hexdigest()
    key = f"ai:peer:{hashed}"
    with Redis.from_url(url) as redis_client:
        try:
            assert [_check_peer(url, peer) for _ in range(4)] == [2, 1, 0, -2]
            assert int(redis_client.get(key) or 0) == 3
            assert 0 < redis_client.ttl(key) <= 3600
        finally:
            redis_client.delete(key)


@pytest.mark.integration
def test_ai_daily_spending_allocation_is_atomic_and_bounded() -> None:
    url = os.environ.get("AISEO_TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis integration URL is not configured")
    from redis import Redis

    key = "ai:daily:" + datetime.now(UTC).strftime("%Y%m%d")
    with Redis.from_url(url) as redis_client:
        prior = redis_client.get(key)
        prior_ttl = redis_client.ttl(key)
        try:
            redis_client.delete(key)
            assert _reserve_spend(url, 7, 10)
            assert not _reserve_spend(url, 7, 10)
            assert int(redis_client.get(key) or 0) == 7
            assert 0 < redis_client.ttl(key) <= 90000
        finally:
            redis_client.delete(key)
            if prior is not None:
                redis_client.set(key, prior, ex=max(prior_ttl, 1))
