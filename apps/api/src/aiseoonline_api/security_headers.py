"""Conservative API security headers without exposing credentials in responses."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiseoonline_api.config import Settings


class SecurityHeadersMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], settings: Settings) -> None:
        self.app = app
        self.production = settings.environment == "production"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secured(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing = {name.lower() for name, _ in headers}
                safe = {
                    b"x-content-type-options": b"nosniff",
                    b"referrer-policy": b"no-referrer",
                    b"x-frame-options": b"DENY",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                }
                if scope.get("path", "").startswith("/api/v1/account/"):
                    safe[b"cache-control"] = b"no-store"
                if self.production:
                    safe[b"strict-transport-security"] = b"max-age=31536000"
                for key, value in safe.items():
                    if key not in existing:
                        headers.append((key, value))
            await send(message)

        await self.app(scope, receive, secured)
