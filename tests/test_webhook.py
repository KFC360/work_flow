from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.crud import webhook_delivery as delivery_crud
from app.core.settings import get_settings


def _sign(body: bytes) -> str:
    secret = get_settings().github_webhook_secret.encode()
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_webhook_invalid_signature(client: TestClient) -> None:
    body = b"{}"
    resp = client.post(
        "/api/v1/github-callback/",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Delivery": "d1",
            "X-GitHub-Event": "issues",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401


def test_webhook_queues_without_github_call(client: TestClient, db: Session, monkeypatch) -> None:
    called = {"n": 0}

    class Boom:
        def __init__(self, *a, **k):
            called["n"] += 1

    monkeypatch.setattr("app.services.github_api.httpx.Client", Boom)

    payload = {
        "action": "opened",
        "issue": {
            "id": 1,
            "number": 1,
            "title": "t",
            "body": "b",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "updated_at": "2026-01-01T00:00:00Z",
            "user": {"login": "u"},
            "labels": [{"name": "功能迭代"}],
        },
        "repository": {"id": 99},
    }
    body = json.dumps(payload).encode()
    resp = client.post(
        "/api/v1/github-callback/",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Delivery": "del-1",
            "X-GitHub-Event": "issues",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 202
    assert called["n"] == 0
    row = delivery_crud.get(db, "del-1")
    assert row is not None
    assert row.status == "queued"


def test_webhook_duplicate(client: TestClient, db: Session) -> None:
    payload = {"action": "opened", "issue": {"id": 1, "number": 1, "title": "t", "body": "", "html_url": "u", "state": "open", "user": {"login": "a"}, "labels": []}, "repository": {"id": 1}}
    body = json.dumps(payload).encode()
    headers = {
        "X-Hub-Signature-256": _sign(body),
        "X-GitHub-Delivery": "dup-1",
        "X-GitHub-Event": "issues",
        "Content-Type": "application/json",
    }
    assert client.post("/api/v1/github-callback/", content=body, headers=headers).status_code == 202
    resp2 = client.post("/api/v1/github-callback/", content=body, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate"


def test_webhook_ping(client: TestClient) -> None:
    body = b"{}"
    resp = client.post(
        "/api/v1/github-callback/",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Delivery": "ping-1",
            "X-GitHub-Event": "ping",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
