"""FastAPI entrypoint — modular monolith (SDD §1, §14).

Run a SINGLE worker: room serialization relies on an in-process per-room mutex
plus DB row locks (SDD §8). Do not configure multiple Uvicorn workers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api import guests, health, rooms
from app.api.csrf import CSRFMiddleware
from app.api.errors import install_error_handlers
from app.config import get_settings
from app.persistence.db import dispose_engine, init_engine
from app.realtime.gateway import gateway
from app.realtime.jobs import sweeper_loop
from app.services import publisher, table
from app.services.timers import timers
from app.version import VERSION

log = logging.getLogger("poker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_engine()
    publisher.set_publisher(gateway)
    sweeper = None
    if get_settings().background_jobs:
        # SDD §9: freeze unfinished hands; the host must Resume manually.
        paused = await table.pause_live_rooms_on_startup()
        if paused:
            log.warning("paused %d room(s) for recovery", len(paused))
        timers.enabled = True
        sweeper = asyncio.create_task(sweeper_loop(), name="sweeper")
    health.state.ready = True
    yield
    # graceful shutdown: stop new hands, drop readiness, close sockets (clients
    # reconnect to the next instance, which pauses live hands for host Resume)
    table.lifecycle.draining = True
    health.state.ready = False
    timers.cancel_all()
    await gateway.close_all()
    if sweeper is not None:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(
        title="Private Texas Hold'em API",
        version=VERSION,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.is_dev else None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(CSRFMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["content-type", "x-poker-csrf", "idempotency-key"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(guests.router, prefix="/api/v1")
    app.include_router(rooms.router, prefix="/api/v1")

    @app.websocket("/ws/rooms/{room_id}")
    async def ws_room(websocket: WebSocket, room_id: uuid.UUID):
        await gateway.handle(websocket, room_id)

    return app


app = create_app()
