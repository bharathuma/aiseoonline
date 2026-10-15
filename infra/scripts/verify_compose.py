#!/usr/bin/env python3
"""Validate the resolved Compose security posture without contacting Docker services."""

import json
import re
import sys
from pathlib import Path


def validate(data: dict) -> None:
    services = data["services"]
    expected = ("api", "worker", "migrate", "web", "db", "redis")
    assert all(name in services for name in expected), "Required service missing"
    for name in ("api", "worker", "migrate"):
        environment = services[name]["environment"]
        assert environment["AISEO_ENVIRONMENT"] == "production", name
        for setting in (
            "AISEO_AUTH_REGISTRATION_ENABLED",
            "AISEO_AUDIT_JOBS_ENABLED",
            "AISEO_RAG_CHAT_ENABLED",
        ):
            assert environment[setting] == "false", f"{name}: {setting} unsafe"
        assert services[name]["security_opt"] == ["no-new-privileges:true"], name
        assert services[name]["read_only"] is True, name

    for name in ("db", "redis", "worker", "migrate"):
        assert not services[name].get("ports"), f"{name} must not publish ports"

    for name in ("api", "web"):
        ports = services[name]["ports"]
        assert len(ports) == 1 and ports[0]["host_ip"] == "127.0.0.1", name

    api_networks = set(services["api"]["networks"])
    web_networks = set(services["web"]["networks"])
    assert api_networks == {"backend", "frontend", "outbound"}
    assert web_networks == {"frontend", "edge"}
    assert set(services["db"]["networks"]) == {"backend"}
    assert set(services["redis"]["networks"]) == {"backend"}
    assert set(services["worker"]["networks"]) == {"backend", "outbound"}
    for name in ("web", "api", "worker"):
        # Compose v2 may preserve a limit as a string such as "256m".
        limit = str(services[name].get("mem_limit", ""))
        assert re.fullmatch(r"[1-9][0-9]*(?:[kKmMgG][bB]?)?", limit), name

    tunnel = services.get("tunnel")
    if tunnel is not None:
        assert tunnel.get("profiles") == ["tunnel"]
        assert set(tunnel["networks"]) == {"edge"}
        assert not tunnel.get("ports")
    assert data["networks"]["frontend"].get("internal") is True
    assert data["networks"]["backend"].get("internal") is True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify_compose.py <resolved-docker-compose.json>")
    validate(json.loads(Path(sys.argv[1]).read_text()))
    print("Private origin Compose security posture verified")
