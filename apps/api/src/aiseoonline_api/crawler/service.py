"""Robots-aware, one-page-only public crawl sessions with strict budgets."""

import threading
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin

from .html import ParsedHtml, parse_html
from .transport import USER_AGENT, HttpDocument, fetch_http
from .urls import (
    CrawlLimitExceeded,
    CrawlTimeout,
    HttpStatusError,
    InvalidPage,
    RobotsDenied,
    SafeURL,
    UnsafeTarget,
    normalize_url,
)

_GLOBAL_FETCH_SLOTS = threading.BoundedSemaphore(2)
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


@dataclass(frozen=True)
class CrawlLimits:
    max_pages: int = 1
    max_bytes: int = 1_048_576
    max_robots_bytes: int = 98_304
    max_redirects: int = 3
    connect_timeout: float = 3.0
    dns_timeout: float = 2.0
    total_timeout: float = 12.0
    min_interval: float = 0.25

    def __post_init__(self) -> None:
        if self.max_pages != 1:
            raise ValueError(
                "Multi-page crawling requires verified-site authorization (not implemented)"
            )
        if not (1024 <= self.max_bytes <= 1_048_576):
            raise ValueError("Public response budgets must be between 1 KiB and 1 MiB")
        if not (1024 <= self.max_robots_bytes <= 98_304):
            raise ValueError("Invalid robots.txt budget")
        if not (0 <= self.max_redirects <= 3):
            raise ValueError("Invalid public redirect budget")
        if not (0.05 <= self.connect_timeout <= 10):
            raise ValueError("Invalid connection timeout")
        if not (0.05 <= self.dns_timeout <= 5):
            raise ValueError("Invalid DNS timeout")
        if not (1 <= self.total_timeout <= 30):
            raise ValueError("Invalid total timeout")
        if not (0 <= self.min_interval <= 10):
            raise ValueError("Invalid politeness delay")


@dataclass(frozen=True)
class PageSnapshot:
    requested_url: str
    final_url: str
    captured_at: datetime
    http_status: int
    redirects: tuple[str, ...]
    content_bytes: int
    html: ParsedHtml


@dataclass(frozen=True)
class TextResource:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    charset: str
    body: bytes
    redirects: tuple[str, ...]


@dataclass(frozen=True)
class RedirectHop:
    url: str
    status: int
    location: str | None


@dataclass(frozen=True)
class RedirectInspection:
    requested_url: str
    final_url: str
    final_status: int | None
    hops: tuple[RedirectHop, ...]
    termination: str


@dataclass(frozen=True)
class LinkProbe:
    url: str
    final_url: str | None
    status: int | None
    state: str


class CrawlSession:
    """At most one page attempt for a fixed origin. Deep mode is disabled."""

    def __init__(self, seed_url: str, *, limits: CrawlLimits | None = None) -> None:
        self.seed = normalize_url(seed_url)
        self.limits = limits or CrawlLimits()
        self._pages_used = 0
        self._probed_links = False
        self._previous_request: float | None = None
        self._lock = threading.Lock()

    def _wait_politely(self, delay: float, deadline: float) -> None:
        if self._previous_request is not None:
            wait = max(0.0, self._previous_request + delay - time.monotonic())
            if wait > deadline - time.monotonic():
                raise CrawlTimeout("Politeness delay exceeds crawl deadline")
            if wait:
                time.sleep(wait)

    def _request(
        self,
        start: SafeURL,
        *,
        deadline: float,
        byte_budget: int,
        allowed_by_robots: urllib.robotparser.RobotFileParser | None = None,
        crawl_delay: float = 0,
        allowed_mime: tuple[str, ...] | None = None,
        on_hop: Callable[[SafeURL, HttpDocument], None] | None = None,
        headers_only: bool = False,
    ) -> tuple[SafeURL, HttpDocument, tuple[str, ...]]:
        current = start
        redirects: list[str] = []
        visited: set[str] = set()
        for _ in range(self.limits.max_redirects + 1):
            if current.origin != self.seed.origin:
                raise UnsafeTarget("Redirect leaves the authorized origin")
            if current.value in visited:
                raise CrawlLimitExceeded("Redirect loop detected")
            visited.add(current.value)
            if allowed_by_robots is not None and not allowed_by_robots.can_fetch(
                USER_AGENT, current.value
            ):
                raise RobotsDenied("robots.txt disallows this page")
            self._wait_politely(max(self.limits.min_interval, crawl_delay), deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not _GLOBAL_FETCH_SLOTS.acquire(timeout=remaining):
                raise CrawlTimeout("No crawl budget remaining")
            try:
                result = fetch_http(
                    current,
                    max_bytes=byte_budget,
                    deadline=deadline,
                    connect_timeout=self.limits.connect_timeout,
                    dns_timeout=self.limits.dns_timeout,
                    allowed_mime=allowed_mime
                    or ("text/html", "application/xhtml+xml", "text/plain"),
                    **({"headers_only": True} if headers_only else {}),
                )
            finally:
                self._previous_request = time.monotonic()
                _GLOBAL_FETCH_SLOTS.release()
            if on_hop is not None:
                on_hop(current, result)
            if result.status not in _REDIRECT_STATUSES:
                return current, result, tuple(redirects)
            if not result.location:
                raise InvalidPage("Redirect has no destination")
            if len(redirects) >= self.limits.max_redirects:
                raise CrawlLimitExceeded("Redirect limit exceeded")
            destination = normalize_url(urljoin(current.value, result.location))
            if current.scheme == "https" and destination.scheme == "http":
                raise UnsafeTarget("HTTPS downgrade redirect is prohibited")
            redirects.append(current.value)
            current = destination
        raise CrawlLimitExceeded("Redirect limit exceeded")

    def fetch_page(self) -> PageSnapshot:
        """Fetch one allowed HTML page and return its structured evidence."""
        with self._lock:
            if self._pages_used >= self.limits.max_pages:
                raise CrawlLimitExceeded("Public sessions allow only one page")
            self._pages_used += 1
            deadline = time.monotonic() + self.limits.total_timeout
            robots_host = f"[{self.seed.host}]" if ":" in self.seed.host else self.seed.host
            robots_url = normalize_url(f"{self.seed.scheme}://{robots_host}/robots.txt")
            final_robots, robots, _ = self._request(
                robots_url, deadline=deadline, byte_budget=self.limits.max_robots_bytes
            )
            if final_robots.origin != self.seed.origin:
                raise RobotsDenied("robots.txt leaves the permitted origin")
            if robots.status in (404, 410):
                rules = None
                crawl_delay = 0.0
            elif robots.status != 200 or robots.content_type not in ("text/plain", ""):
                raise RobotsDenied("robots.txt was not accessible")
            else:
                rules = urllib.robotparser.RobotFileParser()
                rules.parse(robots.body.decode("utf-8", errors="replace").splitlines())
                delay = rules.crawl_delay(USER_AGENT) or 0
                crawl_delay = float(delay)
                if crawl_delay > self.limits.total_timeout:
                    raise RobotsDenied("Crawl-delay exceeds available crawl budget")
            final, page, redirects = self._request(
                self.seed,
                deadline=deadline,
                byte_budget=self.limits.max_bytes,
                allowed_by_robots=rules,
                crawl_delay=crawl_delay,
            )
            if page.status >= 400:
                raise HttpStatusError(page.status)
            if page.status != 200:
                raise InvalidPage("Website did not return a readable page")
            if page.content_type not in ("text/html", "application/xhtml+xml"):
                raise InvalidPage("The destination is not HTML")
            html = parse_html(page.body, final.value, page.charset)
            return PageSnapshot(
                requested_url=self.seed.value,
                final_url=final.value,
                captured_at=datetime.now(UTC),
                http_status=page.status,
                redirects=redirects,
                content_bytes=len(page.body),
                html=html,
            )

    def fetch_resource(self, kind: str) -> TextResource:
        """Read one robots.txt or XML sitemap through the restricted transport.

        This does not enable deep crawling. For sitemaps, check robots.txt before
        fetching the requested document. Sitemap references are never followed.
        """
        if kind not in ("robots", "sitemap"):
            raise ValueError("Unsupported resource kind")
        with self._lock:
            if self._pages_used:
                raise CrawlLimitExceeded("A session permits only one requested resource")
            self._pages_used += 1
            deadline = time.monotonic() + self.limits.total_timeout
            host = f"[{self.seed.host}]" if ":" in self.seed.host else self.seed.host
            robots_url = normalize_url(f"{self.seed.scheme}://{host}/robots.txt")
            if kind == "robots":
                final, document, redirects = self._request(
                    robots_url,
                    deadline=deadline,
                    byte_budget=self.limits.max_robots_bytes,
                    allowed_mime=("text/plain", "text/html"),
                )
                if document.status not in (200, 404, 410):
                    raise HttpStatusError(document.status)
                return TextResource(
                    robots_url.value,
                    final.value,
                    document.status,
                    document.content_type,
                    document.charset,
                    document.body,
                    redirects,
                )

            _, robots, _ = self._request(
                robots_url,
                deadline=deadline,
                byte_budget=self.limits.max_robots_bytes,
                allowed_mime=("text/plain",),
            )
            if robots.status in (404, 410):
                rules = None
                crawl_delay = 0.0
            elif robots.status == 200 and robots.content_type in ("text/plain", ""):
                rules = urllib.robotparser.RobotFileParser()
                rules.parse(robots.body.decode("utf-8", errors="replace").splitlines())
                crawl_delay = float(rules.crawl_delay(USER_AGENT) or 0)
                if crawl_delay > self.limits.total_timeout:
                    raise RobotsDenied("Crawl-delay exceeds public scan budget")
            else:
                raise RobotsDenied("robots.txt cannot be checked")
            final, document, redirects = self._request(
                self.seed,
                deadline=deadline,
                byte_budget=min(self.limits.max_bytes, 524288),
                allowed_by_robots=rules,
                crawl_delay=crawl_delay,
                allowed_mime=("application/xml", "text/xml", "application/rss+xml", "text/plain"),
            )
            if document.status >= 400:
                raise HttpStatusError(document.status)
            if document.status != 200:
                raise InvalidPage("Sitemap did not return HTTP 200")
            return TextResource(
                self.seed.value,
                final.value,
                document.status,
                document.content_type,
                document.charset,
                document.body,
                redirects,
            )

    def inspect_redirects(self) -> RedirectInspection:
        """Trace one same-origin redirect path without fetching document bodies.

        Unsafe and outside-origin destinations are never contacted. Incomplete
        chains retain only the hops already observed from the permitted origin.
        """
        with self._lock:
            if self._pages_used:
                raise CrawlLimitExceeded("Public sessions permit one check")
            self._pages_used += 1
            deadline = time.monotonic() + self.limits.total_timeout
            host = f"[{self.seed.host}]" if ":" in self.seed.host else self.seed.host
            robots_url = normalize_url(f"{self.seed.scheme}://{host}/robots.txt")
            _, robots, _ = self._request(
                robots_url, deadline=deadline, byte_budget=self.limits.max_robots_bytes
            )
            if robots.status in (404, 410):
                rules = None
                delay = 0.0
            elif robots.status == 200 and robots.content_type in ("text/plain", ""):
                rules = urllib.robotparser.RobotFileParser()
                rules.parse(robots.body.decode("utf-8", errors="replace").splitlines())
                delay = float(rules.crawl_delay(USER_AGENT) or 0)
                if delay > self.limits.total_timeout:
                    raise RobotsDenied("Crawl-delay exceeds public scan budget")
            else:
                raise RobotsDenied("robots.txt cannot be checked")
            hops: list[RedirectHop] = []

            def collect(target: SafeURL, result: HttpDocument) -> None:
                location: str | None = None
                if result.location and result.status in _REDIRECT_STATUSES:
                    try:
                        location = normalize_url(urljoin(target.value, result.location)).value
                    except (UnsafeTarget, ValueError):
                        # Do not reflect private, credential-bearing or malformed redirects.
                        pass
                hops.append(RedirectHop(target.value, result.status, location))

            termination = "completed"
            try:
                self._request(
                    self.seed,
                    deadline=deadline,
                    byte_budget=1024,
                    allowed_by_robots=rules,
                    crawl_delay=delay,
                    on_hop=collect,
                    headers_only=True,
                )
            except CrawlLimitExceeded as exc:
                if str(exc) == "Redirect loop detected":
                    termination = "loop"
                elif str(exc) == "Redirect limit exceeded":
                    termination = "limit"
                else:
                    raise
            except UnsafeTarget:
                termination = "blocked_destination"
            if not hops:
                raise InvalidPage("No HTTP response was received")
            final = hops[-1]
            return RedirectInspection(
                requested_url=self.seed.value,
                final_url=final.url,
                final_status=final.status if termination == "completed" else None,
                hops=tuple(hops),
                termination=termination,
            )

    def probe_same_origin_links(self, targets: tuple[str, ...]) -> tuple[LinkProbe, ...]:
        """Probe at most three same-origin destinations by response headers only.

        Used after fetch_page(). All probes share one five-second network deadline.
        Each destination and redirect is subject to robots rules and the secure
        pinned-IP transport. No document bodies or off-origin pages are fetched.
        """
        if len(targets) > 3:
            raise CrawlLimitExceeded("Only three link targets may be checked")
        with self._lock:
            if self._pages_used != 1 or self._probed_links:
                raise CrawlLimitExceeded("Link probes require one previously fetched page")
            self._probed_links = True
            deadline = time.monotonic() + 5.0
            host = f"[{self.seed.host}]" if ":" in self.seed.host else self.seed.host
            robots_url = normalize_url(f"{self.seed.scheme}://{host}/robots.txt")
            try:
                _, robots, _ = self._request(
                    robots_url, deadline=deadline, byte_budget=self.limits.max_robots_bytes
                )
                if robots.status in (404, 410):
                    rules = None
                    delay = 0.0
                elif robots.status == 200 and robots.content_type in ("text/plain", ""):
                    rules = urllib.robotparser.RobotFileParser()
                    rules.parse(robots.body.decode("utf-8", errors="replace").splitlines())
                    delay = float(rules.crawl_delay(USER_AGENT) or 0)
                else:
                    raise RobotsDenied("Unable to verify robots rules")
            except (CrawlTimeout, CrawlLimitExceeded, RobotsDenied, InvalidPage, UnsafeTarget):
                return tuple(LinkProbe(url, None, None, "unverified") for url in targets)
            from .urls import CrawlError

            results: list[LinkProbe] = []
            for raw in targets:
                try:
                    target = normalize_url(raw)
                    if target.origin != self.seed.origin:
                        raise UnsafeTarget("Target is outside source origin")
                    if time.monotonic() >= deadline:
                        raise CrawlTimeout("Link-probe budget exhausted")
                    final, response, _ = self._request(
                        target, deadline=deadline, byte_budget=1024,
                        allowed_by_robots=rules, crawl_delay=delay, headers_only=True,
                    )
                    results.append(LinkProbe(raw, final.value, response.status, "verified"))
                except RobotsDenied:
                    results.append(LinkProbe(raw, None, None, "robots_blocked"))
                except (CrawlError, ValueError):
                    results.append(LinkProbe(raw, None, None, "unverified"))
            return tuple(results)
