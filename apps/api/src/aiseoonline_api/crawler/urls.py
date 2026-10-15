"""Strict URL and DNS validation for public website fetching."""

import ipaddress
import queue
import re
import socket
import threading
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit


class CrawlError(Exception):
    """Controlled failure without raw response bodies or user credentials."""

    code = "crawl_error"


class UnsafeTarget(CrawlError):
    code = "unsafe_target"


class NetworkFailure(CrawlError):
    code = "network_failure"


class CrawlTimeout(CrawlError):
    code = "crawl_timeout"


class CrawlLimitExceeded(CrawlError):
    code = "crawl_limit_exceeded"


class RobotsDenied(CrawlError):
    code = "robots_denied"


class InvalidPage(CrawlError):
    code = "invalid_page"


class HttpStatusError(CrawlError):
    code = "http_status_error"

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__("The website returned an HTTP error status")


@dataclass(frozen=True)
class SafeURL:
    value: str
    scheme: str
    host: str
    port: int
    request_target: str

    @property
    def origin(self) -> tuple[str, str, int]:
        return self.scheme, self.host, self.port


_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_RESERVED_SUFFIX = (
    ".localhost", ".local", ".internal", ".test", ".invalid", ".example", ".home.arpa"
)
_MAX_URL_CHARS = 4096


def _valid_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped or address.sixtofour or address.teredo or address.scope_id:
            return False
    return address.is_global


def normalize_url(raw: str) -> SafeURL:
    """Accept public HTTP(S) URLs on standard ports only; strip fragments."""
    if not isinstance(raw, str) or not raw or len(raw) > _MAX_URL_CHARS:
        raise UnsafeTarget("Invalid URL length")
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in raw) or "\\" in raw:
        raise UnsafeTarget("URL contains forbidden characters")
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.netloc or parsed.username is not None:
            raise UnsafeTarget("Only public HTTP and HTTPS URLs are allowed")
        if parsed.password is not None or "@" in parsed.netloc:
            raise UnsafeTarget("Credentials in URLs are not allowed")
        hostname = parsed.hostname
        if not hostname or "%" in hostname:
            raise UnsafeTarget("Invalid hostname")
        host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port or (443 if scheme == "https" else 80)
    except (ValueError, UnicodeError) as exc:
        raise UnsafeTarget("Invalid URL authority") from exc
    if port != (443 if scheme == "https" else 80):
        raise UnsafeTarget("Only standard HTTP and HTTPS ports are supported")
    if len(host) > 253 or not host:
        raise UnsafeTarget("Invalid hostname length")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host):
            raise UnsafeTarget("Invalid or ambiguous numeric hostname")
        if host == "localhost" or host.endswith(_RESERVED_SUFFIX):
            raise UnsafeTarget("Reserved or local hostname")
        if not all(_HOST_LABEL.fullmatch(label) for label in host.split(".")):
            raise UnsafeTarget("Invalid hostname label")
        if "." not in host:
            raise UnsafeTarget("Hostname must be a public DNS name")
    else:
        if not _valid_ip(address):
            raise UnsafeTarget("Non-public IP addresses are not allowed")
        host = address.compressed
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="/%:@!$&'()*+,;=?-._~")
    bracketed = f"[{host}]" if ":" in host else host
    value = urlunsplit((scheme, bracketed, path, query, ""))
    request_target = path + ("?" + query if query else "")
    return SafeURL(value, scheme, host, port, request_target)


# Four daemonized DNS slots bound the damage from stalled system resolvers.
_DNS_SLOTS = threading.BoundedSemaphore(4)


def resolve_public_addresses(target: SafeURL, *, timeout: float = 2.0) -> tuple[str, ...]:
    """Reject any non-public DNS address; return IPs for direct numerical dialing."""
    try:
        literal = ipaddress.ip_address(target.host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _valid_ip(literal):
            raise UnsafeTarget("Non-public destination")
        return (literal.compressed,)

    if not _DNS_SLOTS.acquire(timeout=timeout):
        raise CrawlTimeout("DNS resolver is busy")
    responses: queue.Queue[object] = queue.Queue(maxsize=1)

    def lookup() -> None:
        try:
            responses.put(socket.getaddrinfo(target.host, target.port, type=socket.SOCK_STREAM))
        except (OSError, ValueError) as exc:
            responses.put(exc)
        finally:
            _DNS_SLOTS.release()

    threading.Thread(target=lookup, daemon=True, name="aiseo-dns").start()
    try:
        result = responses.get(timeout=timeout)
    except queue.Empty as exc:
        raise CrawlTimeout("DNS lookup timed out") from exc
    if isinstance(result, Exception):
        raise NetworkFailure("Could not resolve hostname") from result
    if not isinstance(result, list):
        raise NetworkFailure("DNS resolver returned an invalid response")

    addresses: list[str] = []
    for family, _, _, _, sockaddr in result:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise UnsafeTarget("Invalid DNS response") from exc
        if not _valid_ip(address):
            raise UnsafeTarget("DNS response includes a restricted IP address")
        if address.compressed not in addresses:
            addresses.append(address.compressed)
    if not addresses:
        raise NetworkFailure("No usable DNS address was returned")
    return tuple(addresses)
