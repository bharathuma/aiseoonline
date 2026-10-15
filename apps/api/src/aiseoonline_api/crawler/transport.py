"""Restricted HTTP transport: connect directly to vetted DNS IP addresses."""

import http.client
import socket
import ssl
import time
from dataclasses import dataclass

from .urls import (
    CrawlLimitExceeded,
    CrawlTimeout,
    InvalidPage,
    NetworkFailure,
    SafeURL,
    resolve_public_addresses,
)

USER_AGENT = "AISEOOnlineBot/0.1 (+https://aiseoonline.com/open-source/)"


@dataclass(frozen=True)
class HttpDocument:
    status: int
    content_type: str
    charset: str
    location: str | None
    body: bytes


def fetch_http(
    target: SafeURL,
    *,
    max_bytes: int,
    deadline: float,
    connect_timeout: float,
    dns_timeout: float,
    allowed_mime: tuple[str, ...] = ("text/html", "application/xhtml+xml", "text/plain"),
) -> HttpDocument:
    """Use the validated numerical IP for the socket and the hostname for TLS."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CrawlTimeout("Crawl deadline reached")
    addresses = resolve_public_addresses(target, timeout=min(dns_timeout, remaining))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CrawlTimeout("Crawl deadline reached")
    sock: socket.socket | ssl.SSLSocket | None = None
    try:
        sock = socket.create_connection(
            (addresses[0], target.port), timeout=min(connect_timeout, remaining)
        )
        if target.scheme == "https":
            context = ssl.create_default_context()
            sock.settimeout(min(connect_timeout, max(0.001, deadline - time.monotonic())))
            sock = context.wrap_socket(sock, server_hostname=target.host)
        host_header = f"[{target.host}]" if ":" in target.host else target.host
        request = (
            f"GET {target.request_target} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            f"User-Agent: {USER_AGENT}\r\n"
            "Accept: text/html, application/xhtml+xml, text/plain;q=0.5\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        sock.settimeout(max(0.001, min(connect_timeout, deadline - time.monotonic())))
        sock.sendall(request)
        response = http.client.HTTPResponse(sock)
        response.begin()
        if (
            len(response.getheaders()) > 100
            or sum(len(k) + len(v) for k, v in response.getheaders()) > 32768
        ):
            raise CrawlLimitExceeded("HTTP headers are too large")
        raw_length = response.getheader("Content-Length")
        if raw_length:
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise InvalidPage("Invalid Content-Length") from exc
            if length < 0 or length > max_bytes:
                raise CrawlLimitExceeded("Response exceeds the byte budget")
        encoding = response.getheader("Content-Encoding", "identity").lower().strip()
        if encoding != "identity":
            raise InvalidPage("Compressed HTTP responses are not accepted")
        mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        content_type = response.getheader("Content-Type", "")
        charset = "utf-8"
        for part in content_type.split(";")[1:]:
            if part.strip().lower().startswith("charset="):
                charset = part.split("=", 1)[1].strip().strip('"')[:48]
        location = response.getheader("Location")
        if 300 <= response.status < 400 or response.status >= 400:
            return HttpDocument(response.status, mime, charset, location, b"")
        if mime not in allowed_mime:
            raise InvalidPage("Unsupported document content type")
        body = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CrawlTimeout("Crawl deadline reached")
            sock.settimeout(min(connect_timeout, remaining))
            chunk = response.read(min(8192, max_bytes + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > max_bytes:
                raise CrawlLimitExceeded("Response exceeds the byte budget")
        return HttpDocument(response.status, mime, charset, location, bytes(body))
    except TimeoutError as exc:
        raise CrawlTimeout("Website request timed out") from exc
    except (ssl.SSLError, OSError, http.client.HTTPException) as exc:
        raise NetworkFailure("Website connection failed") from exc
    finally:
        if sock is not None:
            sock.close()
