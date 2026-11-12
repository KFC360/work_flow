from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import COOKIE_NAME, create_access_token, csrf_token_for_jti, decode_access_token
from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.crud import user as user_crud
from app.services.github_api import GitHubAPIError

OLD_UPDATED_AT = datetime(2026, 11, 10, 8, 30, tzinfo=timezone.utc)
NEW_UPDATED_AT = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _login(client: TestClient, db: Session) -> str:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    client.cookies.set(COOKIE_NAME, token)
    return csrf_token_for_jti(decode_access_token(token)["jti"])


def _seed(db: Session, *, status: str = "recorded", kind: str = "feature"):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=55,
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
        github_repo_id=550,
        name="demo",
        github_full_name="acme/demo",
        description=None,
        html_url="https://github.com/acme/demo",
        default_branch="main",
        private=False,
    )
    issue = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=999,
        number=9,
        title="旧标题",
        body="旧正文",
        html_url="https://github.com/acme/demo/issues/9",
        author_login="old-dev",
        github_state="open",
        label_names=["功能迭代"],
        github_updated_at=OLD_UPDATED_AT,
        action="opened",
    )
    issue.status = status
    issue.kind = kind
    issue.design_doc_path = "docs/v0001-9/design.md"
    issue.design_doc_text = "# 本地文档"
    issue.design_source_updated_at = OLD_UPDATED_AT
    issue.last_error = "本地错误"
    db.commit()
    db.refresh(issue)
    return repo, issue


def _payload(**overrides):
    data = {
        "id": 999,
        "number": 9,
        "title": "新标题",
        "body": "新正文",
        "html_url": "https://github.com/acme/demo/issues/9",
        "author_login": None,
        "user": {"login": "new-dev"},
        "state": "closed",
        "updated_at": NEW_UPDATED_AT.isoformat().replace("+00:00", "Z"),
        "labels": [{"name": "人工介入"}, {"name": "bug"}],
        "type": {"id": 1, "name": "Bug"},
    }
    data.update(overrides)
    return data


class FakeClient:
    def __init__(self, payload: object):
        self.payload = payload
        self.issue_args: tuple[str, str, int] | None = None
        self.closed = False

    def get_issue(self, owner: str, repo: str, number: int):
        self.issue_args = (owner, repo, number)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def close(self) -> None:
        self.closed = True


def _use_client(monkeypatch, payload):
    client = FakeClient(payload)
    monkeypatch.setattr("app.api.v1.issues.GitHubClient", lambda: client)
    return client


def test_refresh_success_updates_metadata_and_keeps_local_doc(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo, issue = _seed(db)
    fake = _use_client(monkeypatch, _payload())

    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert f"/issues/{issue.id}" in resp.headers["location"]
    assert "flash=ok" in resp.headers["location"]
    assert fake.issue_args == ("acme", "demo", 9)
    assert fake.closed is True

    db.refresh(issue)
    assert issue.title == "新标题"
    assert issue.body == "新正文"
    assert issue.author_login == "new-dev"
    assert sorted(issue.label_names) == ["bug", "人工介入"]
    assert issue.github_issue_type == "Bug"
    assert issue.github_state == "closed"
    assert issue.github_updated_at == NEW_UPDATED_AT
    assert issue.github_state_updated_at == NEW_UPDATED_AT
    # Local doc/PR/job fields are untouched by a metadata refresh.
    assert issue.design_doc_path == "docs/v0001-9/design.md"
    assert issue.design_doc_text == "# 本地文档"
    assert issue.design_source_updated_at == OLD_UPDATED_AT
    assert issue.last_error == "本地错误"


def test_refresh_writes_and_clears_issue_type(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db)
    _use_client(monkeypatch, _payload())

    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(issue)
    assert issue.github_issue_type == "Bug"

    _use_client(monkeypatch, _payload(type=None))
    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(issue)
    assert issue.github_issue_type is None


def test_refresh_reclassifies_early_status_only(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db, status="pending_classify", kind="pending")
    _use_client(monkeypatch, _payload(labels=[{"name": "人工介入"}]))

    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(issue)
    assert issue.kind == "support"
    assert issue.status == "support_open"


def test_refresh_does_not_reopen_locked_status(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db, status="drafting", kind="feature")
    _use_client(monkeypatch, _payload(labels=[{"name": "人工介入"}]))

    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(issue)
    assert issue.kind == "feature"
    assert issue.status == "drafting"
    assert sorted(issue.label_names) == ["人工介入"]


def test_refresh_github_error_keeps_local_row(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo, issue = _seed(db)
    _use_client(monkeypatch, GitHubAPIError("network down", status_code=500))

    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash=error" in resp.headers["location"]
    db.refresh(issue)
    assert issue.title == "旧标题"
    assert issue.body == "旧正文"
    assert issue.github_state == "open"


def test_refresh_network_exception_keeps_local_row(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db)
    _use_client(monkeypatch, httpx.ConnectError("boom"))

    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash=error" in resp.headers["location"]
    db.refresh(issue)
    assert issue.title == "旧标题"


def test_refresh_identity_mismatch_writes_nothing(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db)
    _use_client(monkeypatch, _payload(id=1000))

    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash=error" in resp.headers["location"]
    db.refresh(issue)
    assert issue.title == "旧标题"
    assert issue.body == "旧正文"


def test_refresh_keeps_active_job_untouched(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo, issue = _seed(db)
    job = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="write_doc")
    _use_client(monkeypatch, _payload())

    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash=ok" in resp.headers["location"]

    db.refresh(issue)
    db.refresh(job)
    assert issue.title == "新标题"
    assert job.status == "queued"
    assert job_crud.has_active_for_issue(db, issue.id)


def test_refresh_requires_csrf_and_login(client: TestClient, db: Session) -> None:
    _repo, issue = _seed(db)

    resp = client.post(f"/issues/{issue.id}/refresh", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    csrf = _login(client, db)
    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": csrf + "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/issues/{issue.id}/refresh",
        data={"csrf_token": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_refresh_get_is_rejected(client: TestClient, db: Session) -> None:
    _login(client, db)
    _repo, issue = _seed(db)
    resp = client.get(f"/issues/{issue.id}/refresh", follow_redirects=False)
    assert resp.status_code == 405
