from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import COOKIE_NAME, create_access_token, csrf_token_for_jti, decode_access_token
from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import repository as repository_crud
from app.crud import user as user_crud
from app.services.app_config import MailConfig
from app.services.ingest import apply_issue_action
from app.services.issue_notify import maybe_notify_new_issue, parse_notify_emails
from app.services.mail import MailSendError


def _mail(**overrides: object) -> MailConfig:
    values: dict[str, object] = {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "security": "starttls",
        "username": "u",
        "from_address": "from@example.com",
        "from_name": "GW",
        "default_to": "",
    }
    values.update(overrides)
    return MailConfig(**values)


def _login(client: TestClient, db: Session) -> str:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    client.cookies.set(COOKIE_NAME, token)
    return csrf_token_for_jti(decode_access_token(token)["jti"])


def _seed_repo(db: Session, *, emails: list[str] | None = None):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=9001,
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
        github_repo_id=90010,
        name="demo",
        github_full_name="acme/demo",
        description=None,
        html_url="https://github.com/acme/demo",
        default_branch="main",
        private=False,
    )
    if emails is not None:
        repo.notify_emails = emails
        db.commit()
        db.refresh(repo)
    return repo


def test_parse_notify_emails_splits_and_keeps_case() -> None:
    emails, err = parse_notify_emails("A@example.com, b@example.com\nc@example.com")
    assert err is None
    assert emails == ["A@example.com", "b@example.com", "c@example.com"]


def test_parse_notify_emails_rejects_duplicate() -> None:
    emails, err = parse_notify_emails("a@example.com, b@example.com\nA@Example.com")
    assert emails == []
    assert err == "重复邮箱：A@Example.com"


def test_parse_notify_emails_empty_is_allowed() -> None:
    assert parse_notify_emails("") == ([], None)
    assert parse_notify_emails(" , ;\n") == ([], None)


def test_parse_notify_emails_rejects_invalid() -> None:
    emails, err = parse_notify_emails("not-an-email")
    assert emails == []
    assert err is not None


def test_repo_save_notify_emails(client: TestClient, db: Session) -> None:
    csrf = _login(client, db)
    repo = _seed_repo(db)
    resp = client.post(
        f"/repos/{repo.id}",
        data={
            "csrf_token": csrf,
            "local_path": "",
            "doc_dir": "docs",
            "notify_emails": "a@example.com\nb@example.com",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(repo)
    assert repo.notify_emails == ["a@example.com", "b@example.com"]

    resp = client.post(
        f"/repos/{repo.id}",
        data={
            "csrf_token": csrf,
            "local_path": "",
            "doc_dir": "docs",
            "notify_emails": "bad-address",
        },
    )
    assert resp.status_code == 200
    assert "非法邮箱" in resp.text
    db.refresh(repo)
    assert repo.notify_emails == ["a@example.com", "b@example.com"]

    resp = client.post(
        f"/repos/{repo.id}",
        data={
            "csrf_token": csrf,
            "local_path": "",
            "doc_dir": "docs",
            "notify_emails": "a@example.com\nA@EXAMPLE.COM",
        },
    )
    assert resp.status_code == 200
    assert "重复邮箱" in resp.text
    db.refresh(repo)
    assert repo.notify_emails == ["a@example.com", "b@example.com"]

    resp = client.post(
        f"/repos/{repo.id}",
        data={
            "csrf_token": csrf,
            "local_path": "",
            "doc_dir": "docs",
            "notify_emails": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(repo)
    assert repo.notify_emails == []


def test_first_insert_sends_once(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.issue_notify.read_mail_config", lambda: _mail())
    monkeypatch.setattr("app.services.issue_notify.get_smtp_password", lambda: "secret")
    sent: list[tuple] = []

    def _fake_send(to, subject, html_body, *, text_fallback=None):
        sent.append((to, subject, html_body))

    monkeypatch.setattr("app.services.issue_notify.send_mail", _fake_send)

    repo = _seed_repo(db, emails=["ops@example.com"])
    payload = {
        "action": "opened",
        "issue": {
            "id": 1,
            "number": 7,
            "title": "Fix login",
            "body": "details",
            "html_url": "https://github.com/acme/demo/issues/7",
            "user": {"login": "alice"},
            "state": "open",
            "labels": [],
            "updated_at": "2026-11-13T01:00:00Z",
        },
    }
    assert apply_issue_action(db, repo.id, payload) is True
    assert len(sent) == 1
    assert "acme/demo" in sent[0][1]
    assert "#7" in sent[0][1]
    issue = issue_crud.get_by_repo_number(db, repo.id, 7)
    assert issue is not None
    assert issue.notify_email_sent_at is not None

    payload["action"] = "edited"
    payload["issue"]["title"] = "Fix login again"
    assert apply_issue_action(db, repo.id, payload) is True
    assert len(sent) == 1


def test_skip_when_no_recipients(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.issue_notify.send_mail",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not send")),
    )
    repo = _seed_repo(db, emails=[])
    issue, created = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=2,
        number=8,
        title="t",
        body="",
        html_url="https://github.com/acme/demo/issues/8",
        author_login="a",
        github_state="open",
        label_names=[],
        github_updated_at=datetime.now(timezone.utc),
        action="opened",
    )
    assert created is True
    assert maybe_notify_new_issue(db, repo, issue, created=True) is False
    assert issue.notify_email_sent_at is None


def test_smtp_error_keeps_issue(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.issue_notify.read_mail_config", lambda: _mail())
    monkeypatch.setattr("app.services.issue_notify.get_smtp_password", lambda: "secret")

    def _boom(*a, **k):
        raise MailSendError("smtp_error", "boom")

    monkeypatch.setattr("app.services.issue_notify.send_mail", _boom)
    repo = _seed_repo(db, emails=["ops@example.com"])
    payload = {
        "action": "opened",
        "issue": {
            "id": 3,
            "number": 9,
            "title": "Broken",
            "body": "",
            "html_url": "https://github.com/acme/demo/issues/9",
            "user": {"login": "bob"},
            "state": "open",
            "labels": [],
            "updated_at": "2026-11-13T02:00:00Z",
        },
    }
    assert apply_issue_action(db, repo.id, payload) is True
    issue = issue_crud.get_by_repo_number(db, repo.id, 9)
    assert issue is not None
    assert issue.notify_email_sent_at is None
