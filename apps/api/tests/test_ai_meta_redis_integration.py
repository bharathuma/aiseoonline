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

    day = datetime.now(UTC).strftime("%Y%m%d")
    keys = ("ai:daily:" + day, "ai:global:" + day)
    with Redis.from_url(url) as redis_client:
        prior = [(key, redis_client.get(key), redis_client.ttl(key)) for key in keys]
        try:
            redis_client.delete(*keys)
            assert _reserve_spend(url, 7, 10, 10)
            assert not _reserve_spend(url, 7, 10, 10)
            assert all(int(redis_client.get(key) or 0) == 7 for key in keys)
            assert all(0 < redis_client.ttl(key) <= 90000 for key in keys)
        finally:
            redis_client.delete(*keys)
            for key, value, ttl in prior:
                if value is not None:
                    redis_client.set(key, value, ex=max(ttl, 1))
