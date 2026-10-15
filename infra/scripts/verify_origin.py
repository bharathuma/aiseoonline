#!/usr/bin/env python3
"""Verify local origin behavior. Not a substitute for external TLS/CDN tests."""

import json
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    parsed = urlsplit(url)
    if parsed.hostname not in ("127.0.0.1", "localhost") or parsed.scheme != "http":
        raise ValueError("Verification may target only an HTTP loopback origin")
    request = urllib.request.Request(url, headers={"User-Agent": "aiseoonline-origin-probe"})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, dict(response.headers.items()), response.read(1_000_000)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, dict(error.headers.items()), error.read(1_000_000)


def header(headers: dict[str, str], key: str) -> str:
    return next((value for name, value in headers.items() if name.lower() == key), "")


def check(base: str) -> None:
    root = base.rstrip("/")
    status, headers, _ = fetch(root + "/")
    assert status == 200, "Static root unavailable"
    assert "must-revalidate" in header(headers, "cache-control")
    assert header(headers, "x-frame-options") == "DENY"
    tool_status, _, tool_html = fetch(root + "/tools/meta-tag-checker/")
    assert tool_status == 200
    scripts = re.findall(rb"/_astro/[A-Za-z0-9._/-]+[.]js", tool_html)
    assert scripts, "Expected one fingerprinted Astro JavaScript resource"
    resource_status, resource_headers, _ = fetch(root + scripts[0].decode("ascii"))
    assert resource_status == 200
    assert "immutable" in header(resource_headers, "cache-control")
    status, headers, _ = fetch(root + "/api/v1/health")
    assert status == 200
    assert "no-store" in header(headers, "cache-control")
    status, _, ready = fetch(root + "/api/v1/ready")
    assert status == 200 and json.loads(ready)["status"] == "ready"
    status, _, content = fetch(root + "/api/v1/openapi.json")
    assert status == 200
    paths = json.loads(content)["paths"]
    assert "/api/v1/tools/meta" in paths
    assert "/api/v1/internal/audits" not in paths
    assert not any("/rag-chat" in key for key in paths)
    status, _, _ = fetch(root + "/api/v1/account/projects")
    assert status == 401
    status, _, _ = fetch(root + "/_headers")
    assert status == 404, "Static hosting policy must not be served as content"
    print("Local private origin checks passed; Cloudflare edge was not contacted.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify_origin.py http://127.0.0.1:4321")
    check(sys.argv[1])
