import pytest

from tests.integration.conftest import TEST_DB

pytestmark = pytest.mark.skipif(not TEST_DB, reason="POKER_TEST_DATABASE_URL not set")


async def test_health(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    r = await client.get("/health/ready")
    assert r.status_code == 200 and r.json()["db"] is True


async def test_create_and_resume_session(client):
    r = await client.post("/api/v1/guests/session", json={"nickname": "  Andrew  "})
    assert r.status_code == 200
    body = r.json()
    assert body["nickname"] == "Andrew"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie

    me = await client.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["guest_id"] == body["guest_id"]

    # resume: same guest, nickname updated (display-only)
    r2 = await client.post("/api/v1/guests/session", json={"nickname": "Andy"})
    assert r2.json()["guest_id"] == body["guest_id"] and r2.json()["nickname"] == "Andy"


async def test_unauthenticated_me_uses_error_envelope(app):
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as c:
        r = await c.get("/api/v1/me")
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "UNAUTHORIZED" and "request_id" in err


async def test_csrf_header_required(app):
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as c:
        r = await c.post("/api/v1/guests/session", json={"nickname": "x"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_FAILED"
        r = await c.post(
            "/api/v1/guests/session",
            json={"nickname": "x"},
            headers={"X-Poker-CSRF": "1", "Origin": "https://evil.example"},
        )
        assert r.status_code == 403


async def test_invalid_nickname(client):
    r = await client.post("/api/v1/guests/session", json={"nickname": "   "})
    assert r.status_code == 422


async def test_forged_cookie_rejected(app):
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
        cookies={"poker_session": "forged"},
    ) as c:
        assert (await c.get("/api/v1/me")).status_code == 401
