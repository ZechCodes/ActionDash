"""Tests for the authenticated JSON API endpoints."""


async def test_runs_empty_db(authed_client):
    response = await authed_client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == {"runs": []}


async def test_daily_runs_returns_60_days(authed_client):
    response = await authed_client.get("/api/daily-runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data["days"]) == 60
    for day in data["days"]:
        assert "date" in day
        assert "success" in day
        assert "failure" in day


async def test_stats_empty_db(authed_client):
    response = await authed_client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["active_count"] == 0
    assert data["success_count"] == 0
    assert data["failure_count"] == 0


async def test_active_empty_db(authed_client):
    response = await authed_client.get("/api/active")
    assert response.status_code == 200
    assert response.json() == {"runs": []}
