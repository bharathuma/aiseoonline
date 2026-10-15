"""Measured, isolated HTTP concurrency and atomic quota regression tests.

These are in-process synthetic checks, not internet or production throughput tests.
"""

import asyncio
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from math import ceil
from uuid import uuid4

import httpx
import pytest
from redis import Redis

from aiseoonline_api.config import Settings
from aiseoonline_api.main import create_app
from aiseoonline_api.public_tools import routes
from aiseoonline_api.public_tools.checks import ToolReport


def test_controlled_public_api_burst_respects_request_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 concurrent simulated visitors cannot bypass the per-process four-fetch limit."""
    active = 0
    peak = 0
    lock = threading.Lock()

    async def free_budget(*_args: object) -> bool:
        return True

    def bounded_fixture(url: str) -> ToolReport:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.025)
            return ToolReport(
                tool="meta",
                requested_url=url,
                final_url=url,
                checked_at=datetime.now(UTC),
                facts={"fixture": True},
                issues=[],
            )
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(routes, "reserve_budget", free_budget)
    monkeypatch.setattr(routes, "check_meta", bounded_fixture)
    app = create_app(Settings(_env_file=None, environment="test"))

    async def burst() -> tuple[list[int], list[float]]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", timeout=15
        ) as client:

            async def call() -> tuple[int, float]:
                started = time.perf_counter()
                result = await client.post(
                    "/api/v1/tools/meta", json={"url": "https://example.org/"}
                )
                return result.status_code, (time.perf_counter() - started) * 1000

            results = await asyncio.gather(*(call() for _ in range(20)))
        return [item[0] for item in results], [item[1] for item in results]

    statuses, times = asyncio.run(burst())
    assert statuses == [200] * 20
    assert 1 <= peak <= 4
    ordered = sorted(times)
    measurement = {
        "environment": "in_process_mocked_crawl",
        "requests": len(statuses),
        "simulated_fetch_sleep_ms": 25,
        "max_concurrent_fetches": peak,
        "p50_ms": round(ordered[ceil(len(ordered) * 0.5) - 1], 2),
        "p95_ms": round(ordered[ceil(len(ordered) * 0.95) - 1], 2),
    }
    print("QA_API_LOAD|" + json.dumps(measurement, sort_keys=True))


@pytest.mark.integration
def test_real_redis_denied_peer_requests_do_not_exhaust_site_quota() -> None:
    url = os.getenv("AISEO_TEST_REDIS_URL")
    if not url:
        pytest.skip("Requires an isolated Redis integration service")
    host = uuid4().hex + ".example.org"
    peer = "load-peer-" + uuid4().hex
    second = "other-peer-" + uuid4().hex
    domain_url = "https://" + host + "/"
    peer_key = "seo:ip:" + hashlib.sha256(peer.encode()).hexdigest()
    second_key = "seo:ip:" + hashlib.sha256(second.encode()).hexdigest()
    site_key = "seo:site:" + hashlib.sha256(host.encode()).hexdigest()
    keys = (peer_key, second_key, site_key)
    with Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1) as redis:
        try:
            redis.delete(*keys)
            with ThreadPoolExecutor(max_workers=12) as executor:
                accepted = list(
                    executor.map(lambda _: routes._check_quota(domain_url, peer, url), range(24))
                )
            assert sum(accepted) == 12
            assert int(redis.get(peer_key) or 0) == 12
            # Denied abusive requests do not consume the shared domain allowance.
            assert int(redis.get(site_key) or 0) == 12
            assert routes._check_quota(domain_url, second, url)
            assert int(redis.get(site_key) or 0) == 13
            assert 0 < redis.ttl(site_key) <= 3600
        finally:
            redis.delete(*keys)


@pytest.mark.integration
def test_real_redis_domain_quota_is_atomic_across_distinct_peers() -> None:
    url = os.getenv("AISEO_TEST_REDIS_URL")
    if not url:
        pytest.skip("Requires an isolated Redis integration service")
    host = uuid4().hex + ".example.org"
    site_url = "https://" + host + "/"
    peers = ["load-" + uuid4().hex for _ in range(135)]
    keys = ["seo:site:" + hashlib.sha256(host.encode()).hexdigest()]
    keys += ["seo:ip:" + hashlib.sha256(peer.encode()).hexdigest() for peer in peers]
    with Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1) as redis:
        try:
            with ThreadPoolExecutor(max_workers=16) as executor:
                admitted = list(
                    executor.map(lambda peer: routes._check_quota(site_url, peer, url), peers)
                )
            assert sum(admitted) == 120
            assert int(redis.get(keys[0]) or 0) == 120
        finally:
            redis.delete(*keys)
