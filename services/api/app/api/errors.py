"""Canonical error envelope (SDD §7.1). Never leak stack traces."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.poker.errors import EngineError
from app.services.errors import ServiceError

log = logging.getLogger("poker.api")

STATUS = {
    "UNAUTHORIZED": 401,
    "ROOM_BANNED": 403,
    "NOT_HOST": 403,
    "CSRF_FAILED": 403,
    "NOT_FOUND": 404,
    "ROOM_CLOSED": 409,
    "ROOM_FULL": 409,
    "HAND_ALREADY_RUNNING": 409,
    "NOT_YOUR_TURN": 409,
    "STALE_VERSION": 409,
    "DEADLINE_EXPIRED": 409,
    "INVALID_PASSWORD": 403,
    "INVALID_BUYIN": 422,
    "INVALID_ACTION": 422,
    "TOPUP_LIMIT_EXCEEDED": 422,
    "VALIDATION_ERROR": 422,
    "RATE_LIMITED": 429,
    "ROOM_PAUSED": 409,
    "NOT_MEMBER": 403,
    "SEAT_TAKEN": 409,
    "ALREADY_SEATED": 409,
    "INTERNAL": 500,
}


ApiError = ServiceError  # REST layer alias


def envelope(code: str, message: str, room_version: int | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "room_version": room_version,
            "request_id": str(uuid.uuid4()),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            envelope(exc.code, exc.message, exc.room_version), status_code=STATUS.get(exc.code, 400)
        )

    @app.exception_handler(EngineError)
    async def _engine(_: Request, exc: EngineError) -> JSONResponse:
        return JSONResponse(envelope(exc.code, exc.message), status_code=STATUS.get(exc.code, 400))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(envelope("VALIDATION_ERROR", "Invalid request body."), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")  # structured log; no secrets in message
        return JSONResponse(envelope("INTERNAL", "Internal error."), status_code=500)
