from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import repository as repository_crud
from app.crud import webhook_delivery as delivery_crud
from app.tasks.inbox import process_one_delivery


def _seed(db: Session) -> tuple[int, int]:
    company = company_crud.upsert_from_github(
        db,
        github_account_id=501,
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
        github_repo_id=5010,
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
        github_issue_id=1,
        number=8,
        title="feat",
        body="b",
        html_url="https://github.com/acme/demo/issues/8",
        author_login="dev",
        github_state="open",
        label_names=["功能迭代"],
        github_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        action="opened",
    )
    issue.status = "pr_opened"
    issue.codegen_phase = "pr_opened"
    issue.pr_number = 25
    issue.pr_url = "https://github.com/acme/demo/pull/25"
    issue.pr_state = "open"
    issue.pr_state_updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    db.commit()
    return repo.github_repo_id, issue.id


def _payload(action: str, *, merged: bool = False, updated_at: str = "2026-01-03T00:00:00Z") -> dict:
    pr = {
        "number": 25,
        "state": "closed" if action == "closed" else "open",
        "merged": merged,
        "merged_at": "2026-01-03T00:00:00Z" if merged else None,
        "updated_at": updated_at,
        "html_url": "https://github.com/acme/demo/pull/25",
        "base": {"repo": {"id": 5010}},
    }
    return {"action": action, "pull_request": pr, "repository": {"id": 5010}}


class FakeClient:
    def close(self) -> None:
        pass

    def get_repository(self, repo_id: int) -> dict:
        return {
            "id": repo_id,
            "name": "demo",
            "full_name": "acme/demo",
            "description": None,
            "html_url": "https://github.com/acme/demo",
            "default_branch": "main",
            "private": False,
            "owner": {"id": 501, "login": "acme", "type": "Organization"},
        }

    def get_org(self, login: str) -> dict:
        return {
            "id": 501,
            "login": login,
            "name": "Acme",
            "description": None,
            "avatar_url": None,
            "html_url": "https://github.com/acme",
        }


def _queue(db: Session, delivery_id: str, payload: dict, *, event: str = "pull_request") -> None:
    delivery_crud.create_queued(
        db,
        delivery_id=delivery_id,
        event=event,
        action=payload.get("action"),
        repository_id=payload["repository"]["id"],
        payload=payload,
    )


def _sign(body: bytes) -> str:
    secret = get_settings().github_webhook_secret.encode()
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_webhook_queues_pull_request_and_ignores_other_events(
    client: TestClient, db: Session
) -> None:
    payload = _payload("opened")
    body = json.dumps(payload).encode()
    resp = client.post(
        "/api/v1/github-callback/",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Delivery": "pr-route-1",
            "X-GitHub-Event": "pull_request",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 202
    row = delivery_crud.get(db, "pr-route-1")
    assert row is not None
    assert row.event == "pull_request"
    assert row.status == "queued"

    push_body = b"{}"
    resp = client.post(
        "/api/v1/github-callback/",
        content=push_body,
        headers={
            "X-Hub-Signature-256": _sign(push_body),
            "X-GitHub-Delivery": "push-route-1",
            "X-GitHub-Event": "push",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert delivery_crud.get(db, "push-route-1") is None


def test_pull_request_merged_updates_only_pr_columns(db: Session) -> None:
    _gh_id, issue_id = _seed(db)
    _queue(db, "pr-merged", _payload("closed", merged=True))
    assert process_one_delivery(db, object()) is True
    issue = issue_crud.get(db, issue_id)
    assert issue is not None
    assert issue.status == "pr_opened"
    assert issue.codegen_phase == "pr_opened"
    assert issue.pr_state == "merged"
    assert issue.pr_merged_at == datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert delivery_crud.get(db, "pr-merged").status == "succeeded"


def test_pull_request_closed_unmerged_and_reopened(db: Session) -> None:
    _gh_id, issue_id = _seed(db)
    _queue(db, "pr-closed", _payload("closed"))
    process_one_delivery(db, object())
    issue = issue_crud.get(db, issue_id)
    assert issue is not None
    assert issue.pr_state == "closed"
    assert issue.pr_merged_at is None

    _queue(db, "pr-reopened", _payload("reopened", updated_at="2026-01-04T00:00:00Z"))
    process_one_delivery(db, object())
    db.refresh(issue)
    assert issue.pr_state == "open"
    assert issue.pr_merged_at is None


def test_late_pr_event_does_not_roll_back(db: Session) -> None:
    _gh_id, issue_id = _seed(db)
    _queue(db, "pr-new", _payload("closed", merged=True, updated_at="2026-01-05T00:00:00Z"))
    process_one_delivery(db, object())
    _queue(
        db,
        "pr-stale",
        _payload("opened", updated_at="2026-01-03T00:00:00Z"),
    )
    process_one_delivery(db, object())
    issue = issue_crud.get(db, issue_id)
    assert issue is not None
    assert issue.pr_state == "merged"
    assert delivery_crud.get(db, "pr-stale").status == "succeeded"


def test_unmatched_pull_request_is_ignored(db: Session) -> None:
    _seed(db)
    payload = _payload("opened")
    payload["pull_request"]["number"] = 999
    _queue(db, "pr-miss", payload)
    process_one_delivery(db, object())
    row = delivery_crud.get(db, "pr-miss")
    assert row is not None
    assert row.status == "ignored"
    assert "未匹配到 Issue" in (row.last_error or "")


def test_issue_closed_and_reopened_guards(db: Session) -> None:
    _gh_id, issue_id = _seed(db)
    closed = {
        "action": "closed",
        "issue": {
            "id": 1,
            "number": 8,
            "title": "feat",
            "body": "b",
            "html_url": "https://github.com/acme/demo/issues/8",
            "state": "closed",
            "updated_at": "2026-01-06T00:00:00Z",
            "user": {"login": "dev"},
            "labels": [{"name": "功能迭代"}],
        },
        "repository": {"id": 5010},
    }
    _queue(db, "issue-closed", {**closed, "action": "closed"}, event="issues")
    process_one_delivery(db, FakeClient())
    issue = issue_crud.get(db, issue_id)
    assert issue is not None
    assert issue.github_state == "closed"

    stale = {**closed, "action": "reopened", "issue": {**closed["issue"], "state": "open", "updated_at": "2026-01-04T00:00:00Z"}}
    _queue(db, "issue-stale-reopen", stale, event="issues")
    process_one_delivery(db, FakeClient())
    db.refresh(issue)
    assert issue.github_state == "closed"

    reopened = {**closed, "action": "reopened", "issue": {**closed["issue"], "state": "open", "updated_at": "2026-01-07T00:00:00Z"}}
    _queue(db, "issue-reopened", reopened, event="issues")
    process_one_delivery(db, FakeClient())
    db.refresh(issue)
    assert issue.github_state == "open"


def test_pr_state_filter_and_merged_not_unfinished(db: Session, client) -> None:
    from app.core.security import COOKIE_NAME, create_access_token

    from app.crud import user as user_crud

    user_crud.ensure_admin_user(db)
    client.cookies.set(COOKIE_NAME, create_access_token("admin"))
    gh_id, issue_id = _seed(db)
    repo = repository_crud.get_by_github_repo_id(db, gh_id)
    assert repo is not None

    resp = client.get(f"/issues/{issue_id}")
    assert resp.status_code == 200
    assert "PR 状态" in resp.text
    assert "开放" in resp.text

    _queue(db, "pr-filter-merged", _payload("closed", merged=True))
    process_one_delivery(db, object())

    resp = client.get(f"/repos/{repo.id}/issues?pr_state=merged&github_state=open")
    assert resp.status_code == 200
    assert "feat" in resp.text
    assert "已合并" in resp.text

    summary = issue_crud.repo_open_summary(db, repo.id)
    assert summary.feature_unfinished == 0
    company = company_crud.get(db, repo.company_id)
    assert company is not None
    assert company_crud.open_issue_count(db, company.id) == 0

    resp = client.get(f"/issues/{issue_id}")
    assert resp.status_code == 200
    assert "PR 状态" in resp.text
    assert "已合并" in resp.text
    assert "合并于" in resp.text
