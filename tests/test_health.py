"""Tests for the health check endpoint."""


async def test_health_returns_ok(client):
    response = await client.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_health_no_auth_required(client):
    """Health endpoint works without any session data."""
    response = await client.get("/healthz/")
    assert response.status_code == 200
    assert "ok" in response.json()
