"""GET /api/v1/version: release number + exact commit for the UI."""

import pytest

from app import version
from tests.integration.conftest import TEST_DB

pytestmark = [
    pytest.mark.skipif(not TEST_DB, reason="POKER_TEST_DATABASE_URL not set"),
    pytest.mark.usefixtures("app"),
]


async def test_version_endpoint_reports_release_and_commit(make_client, monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "25f3d11fc1b0b46fa030e0a64f3840f73170aed5")
    version.commit.cache_clear()
    try:
        r = await make_client().get("/api/v1/version")  # no session needed
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == version.VERSION
        assert body["commit"] == "25f3d11"
        assert body["started_at"]
    finally:
        version.commit.cache_clear()
