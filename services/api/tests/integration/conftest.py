"""Integration fixtures: real PostgreSQL (POKER_TEST_DATABASE_URL), skipped if absent."""

import os

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DB = os.environ.get("POKER_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="POKER_TEST_DATABASE_URL not set")


@pytest.fixture(scope="session")
async def app():
    if not TEST_DB:
        pytest.skip("POKER_TEST_DATABASE_URL not set")
    os.environ["POKER_DATABASE_URL"] = TEST_DB
    os.environ["POKER_ENV"] = "test"
    os.environ["POKER_BACKGROUND_JOBS"] = "false"
    from app.security.crypto import Cipher

    os.environ.setdefault("POKER_DATA_ENCRYPTION_KEY", Cipher.generate_key())
    from app.config import get_settings
    from app.services.secrets import get_cipher

    get_settings.cache_clear()
    get_cipher.cache_clear()
    from app.persistence.models import Base

    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    from app.api import health
    from app.main import create_app
    from app.persistence.db import dispose_engine, init_engine
    from app.realtime.gateway import gateway
    from app.services import publisher

    init_engine(TEST_DB)
    publisher.set_publisher(gateway)
    health.state.ready = True
    application = create_app()
    yield application
    await dispose_engine()


@pytest.fixture(autouse=True)
def _reset_clock_and_limits():
    from app.security.ratelimit import guest_create_limiter, password_guess_limiter
    from app.services import clock

    clock.reset()
    password_guess_limiter.reset()
    guest_create_limiter.reset()
    yield
    clock.reset()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://testserver", headers={"X-Poker-CSRF": "1"}
    ) as c:
        yield c


@pytest.fixture
def make_client(app):
    """Factory for independent browser-like clients (separate cookie jars)."""
    clients: list[httpx.AsyncClient] = []

    def _make() -> httpx.AsyncClient:
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://testserver",
            headers={"X-Poker-CSRF": "1"},
        )
        clients.append(c)
        return c

    yield _make
    # clients are closed by GC; AsyncClient.aclose would need a running loop here
