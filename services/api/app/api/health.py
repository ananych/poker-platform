"""/health/live and /health/ready (SDD §12)."""

from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.persistence.db import get_engine

router = APIRouter()


class _State:
    ready = False


state = _State()


@router.get("/health/live")
async def live():
    return {"status": "ok"}


@router.get("/health/ready")
async def ready():
    if not state.ready:  # still running startup recovery, or shutting down
        return JSONResponse({"status": "starting", "db": None}, status_code=503)
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable", "db": False}, status_code=503)
    return {"status": "ok", "db": True}


@router.get("/metrics")
async def metrics_endpoint(authorization: str | None = Header(default=None)):
    from app.config import get_settings
    from app.realtime.gateway import gateway
    from app.services.metrics import metrics

    s = get_settings()
    if s.metrics_token:
        if authorization != f"Bearer {s.metrics_token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    elif not s.is_dev:
        return JSONResponse(
            {"error": "metrics disabled (set POKER_METRICS_TOKEN)"}, status_code=404
        )
    return metrics.snapshot(gateway.gauges())
