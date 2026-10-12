"""CSRF defence for cookie-authenticated REST (SDD §7, §12).

State-changing requests must carry the custom header `X-Poker-CSRF: 1` (cannot
be sent cross-site without a CORS preflight) and, when present, an allowed Origin.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.errors import envelope

SAFE = {"GET", "HEAD", "OPTIONS"}


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed = set(allowed_origins)

    async def dispatch(self, request: Request, call_next):
        if request.method not in SAFE and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin is not None and origin not in self.allowed:
                return JSONResponse(envelope("CSRF_FAILED", "Origin not allowed."), 403)
            if request.headers.get("x-poker-csrf") != "1":
                return JSONResponse(envelope("CSRF_FAILED", "Missing CSRF header."), 403)
        return await call_next(request)
