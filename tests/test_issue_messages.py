from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import json

from app.core.security import COOKIE_NAME, create_access_token
from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import issue_message as message_crud
from app.crud import repository as repository_crud
from app.crud import user as user_crud
from app.crud import webhook_delivery as delivery_crud
from app.services.issue_messages import (
    process_issue_comment_delivery,
    record_issue_action_event,
    sync_issue_comments,
)
from app.tasks.inbox import process_one_delivery
from tests.test_webhook import _sign


def _login(client: TestClient, db: Session) -> None:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    client.cookies.set(COOKIE_NAME, token)


def _seed(db: Session):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=70,
        account_type="Organization",
        login="acme",
        name="Acme",
        description=None,
        avatar_url=None,
        html_url=None,
    )
    repo = repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=770,
        name="demo",
        github_full_name="acme/demo",
        description=None,
        html_url="https://github.com/acme/demo",
        default_branch="main",
        private=False,
    )
    issue, _ = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=9001,
        number=28,
        title="sync messages",
        body="body",
        html_url="https://github.com/acme/demo/issues/28",
        author_login="Mengcf",
        github_state="open",
        label_names=["功能迭代"],
        github_updated_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        action="opened",
    )
    db.commit()
    return repo, issue


class FakeCommentsClient:
    def __init__(self, pages):
        self.pages = pages

    def list_issue_comments(self, owner, repo, number, **kwargs):
        return self.pages.get(kwargs.get("page", 1), [])


def test_sync_issue_comments_upserts(db: Session) -> None:
    repo, issue = _seed(db)
    client = FakeCommentsClient(
        {
            1: [
                {
                    "id": 11,
                    "body": "first comment",
                    "user": {"login": "alice"},
                    "created_at": "2026-11-13T07:00:00Z",
                    "updated_at": "2026-11-13T07:00:00Z",
                }
            ]
        }
    )
    n = sync_issue_comments(db, client, repo, issue, commit=True)
    assert n == 1
    rows = message_crud.list_for_issue(db, issue.id)
    assert len(rows) == 1
    assert rows[0].body == "first comment"
    assert rows[0].author_login == "alice"


def test_issue_comment_webhook_created_edited_deleted(db: Session) -> None:
    repo, issue = _seed(db)
    base = {
        "repository": {"id": repo.github_repo_id},
        "issue": {"number": issue.number},
        "comment": {
            "id": 42,
            "body": "hello",
            "user": {"login": "bob"},
            "created_at": "2026-11-13T08:00:00Z",
            "updated_at": "2026-11-13T08:00:00Z",
        },
    }
    ok, reason = process_issue_comment_delivery(db, {**base, "action": "created"})
    assert ok and reason is None
    db.commit()
    row = message_crud.get_by_comment_id(db, issue.id, 42)
    assert row is not None and row.body == "hello" and row.deleted_at is None

    base["comment"]["body"] = "hello edited"
    base["comment"]["updated_at"] = "2026-11-13T08:05:00Z"
    ok, _ = process_issue_comment_delivery(db, {**base, "action": "edited"})
    assert ok
    db.commit()
    db.refresh(row)
    assert row.body == "hello edited"

    ok, _ = process_issue_comment_delivery(db, {**base, "action": "deleted"})
    assert ok
    db.commit()
    db.refresh(row)
    assert row.deleted_at is not None


def test_record_closed_event_and_detail_renders(client: TestClient, db: Session) -> None:
    repo, issue = _seed(db)
    record_issue_action_event(
        db,
        issue,
        action="closed",
        actor_login="Mengcf",
        occurred_at=datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc),
        commit=True,
    )
    message_crud.upsert_comment(
        db,
        issue_id=issue.id,
        github_comment_id=7,
        author_login="Mengcf",
        body="done",
        occurred_at=datetime(2026, 11, 13, 8, 50, tzinfo=timezone.utc),
        github_updated_at=None,
        commit=True,
    )
    _login(client, db)
    resp = client.get(f"/issues/{issue.id}")
    assert resp.status_code == 200
    text = resp.text
    assert "讨论与动态" in text
    assert "done" in text
    assert "关闭了 Issue" in text


def test_webhook_queues_issue_comment(client: TestClient, db: Session) -> None:
    repo, issue = _seed(db)
    payload = {
        "action": "created",
        "repository": {"id": repo.github_repo_id},
        "issue": {"number": issue.number},
        "comment": {
            "id": 99,
            "body": "via webhook",
            "user": {"login": "carol"},
            "created_at": "2026-11-13T10:00:00Z",
            "updated_at": "2026-11-13T10:00:00Z",
        },
    }
    body = json.dumps(payload).encode()
    resp = client.post(
        "/api/v1/github-callback/",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Delivery": "msg-1",
            "X-GitHub-Event": "issue_comment",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 202
    row = delivery_crud.get(db, "msg-1")
    assert row is not None and row.status == "queued"
    assert process_one_delivery(db) is True
    messages = message_crud.list_for_issue(db, issue.id)
    assert any(m.body == "via webhook" for m in messages)
