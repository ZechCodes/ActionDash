"""Tests for the GitHub webhook endpoint."""

import hashlib
import hmac
import json
import os
from unittest.mock import patch

WEBHOOK_URL = "/webhooks/github"


def _sign(payload: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _workflow_run_payload():
    return {
        "action": "completed",
        "workflow_run": {
            "id": 12345,
            "name": "CI",
            "workflow_id": 1,
            "head_branch": "main",
            "head_sha": "abc1234567890abcdef1234567890abcdef12345",
            "status": "completed",
            "conclusion": "success",
            "event": "push",
            "run_number": 42,
            "run_attempt": 1,
            "html_url": "https://github.com/test/repo/actions/runs/12345",
            "actor": {
                "login": "testuser",
                "avatar_url": "https://example.com/avatar.png",
            },
            "run_started_at": "2026-02-20T10:00:00Z",
            "updated_at": "2026-02-20T10:05:00Z",
        },
        "repository": {"full_name": "test/repo"},
    }


def _headers(event="workflow_run", signature=None):
    h = {"x-github-event": event, "content-type": "application/json"}
    if signature:
        h["x-hub-signature-256"] = signature
    return h


@patch("actiondash.controllers.notify_user")
async def test_accepts_without_secret(mock_notify, client):
    """No GITHUB_WEBHOOK_SECRET → signature check skipped."""
    payload = json.dumps(_workflow_run_payload()).encode()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
        response = await client.post(
            WEBHOOK_URL, content=payload, headers=_headers()
        )
    assert response.status_code == 200


@patch("actiondash.controllers.notify_user")
async def test_accepts_valid_signature(mock_notify, client):
    secret = "test-webhook-secret"
    payload = json.dumps(_workflow_run_payload()).encode()
    signature = _sign(payload, secret)
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": secret}):
        response = await client.post(
            WEBHOOK_URL,
            content=payload,
            headers=_headers(signature=signature),
        )
    assert response.status_code == 200


async def test_rejects_invalid_signature(client):
    payload = json.dumps(_workflow_run_payload()).encode()
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": "real-secret"}):
        response = await client.post(
            WEBHOOK_URL,
            content=payload,
            headers=_headers(signature="sha256=invalidsignature"),
        )
    assert response.status_code == 401


async def test_rejects_missing_signature_when_secret_set(client):
    payload = json.dumps(_workflow_run_payload()).encode()
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": "real-secret"}):
        response = await client.post(
            WEBHOOK_URL, content=payload, headers=_headers()
        )
    assert response.status_code == 401


async def test_missing_event_header_returns_400(client):
    payload = json.dumps(_workflow_run_payload()).encode()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
        response = await client.post(
            WEBHOOK_URL,
            content=payload,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 400


@patch("actiondash.controllers.notify_user")
async def test_workflow_run_creates_record(mock_notify, client, _db):
    _, session_maker = _db
    payload = json.dumps(_workflow_run_payload()).encode()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
        response = await client.post(
            WEBHOOK_URL, content=payload, headers=_headers()
        )
    assert response.status_code == 200
    assert response.json()["run_id"] == 12345

    from sqlalchemy import select
    from actiondash.models import WorkflowRun

    async with session_maker() as session:
        result = await session.execute(
            select(WorkflowRun).where(WorkflowRun.run_id == 12345)
        )
        run = result.scalar_one_or_none()
        assert run is not None
        assert run.repo_full_name == "test/repo"
        assert run.workflow_name == "CI"
        assert run.conclusion == "success"


async def test_unknown_event_returns_ignored(client):
    payload = json.dumps({"action": "completed"}).encode()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
        response = await client.post(
            WEBHOOK_URL, content=payload, headers=_headers(event="ping")
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": "ping"}
