"""Tests that guarded API endpoints require authentication."""

import pytest

GUARDED_ENDPOINTS = [
    "/api/runs",
    "/api/active",
    "/api/stats",
    "/api/daily-runs",
]


@pytest.mark.parametrize("endpoint", GUARDED_ENDPOINTS)
async def test_unauthenticated_returns_401(client, endpoint):
    response = await client.get(endpoint)
    assert response.status_code == 401
