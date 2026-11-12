from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import COOKIE_NAME, create_access_token, csrf_token_for_jti, decode_access_token
from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.crud import user as user_crud


def _login(client: TestClient, db: Session) -> str:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    client.cookies.set(COOKIE_NAME, token)
    return csrf_token_for_jti(decode_access_token(token)["jti"])


def _seed_issue(db: Session, *, status: str = "pending_classify", kind: str = "pending"):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=42,
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
        github_repo_id=420,
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
        title="t",
        body="b",
        html_url="https://github.com/acme/demo/issues/9",
        author_login="dev",
        github_state="open",
        label_names=[],
        github_updated_at=None,
        action="opened",
    )
    issue.status = status
    issue.kind = kind
    db.commit()
    db.refresh(issue)
    return repo, issue


def test_classify_and_queue_guard(client: TestClient, db: Session) -> None:
    csrf = _login(client, db)
    repo, issue = _seed_issue(db)
    resp = client.post(f"/issues/{issue.id}/classify/feature", data={"csrf_token": csrf}, follow_redirects=False)
    assert resp.status_code == 303
    db.refresh(issue)
    assert issue.kind == "feature"
    assert issue.status == "recorded"

    # no agent / path -> enqueue fails
    resp2 = client.post(
        f"/issues/{issue.id}/enqueue/write_doc",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp2.status_code == 303
    assert "flash=error" in resp2.headers["location"]


def test_queued_does_not_change_status(client: TestClient, db: Session, monkeypatch, tmp_path) -> None:
    csrf = _login(client, db)
    repo, issue = _seed_issue(db, status="recorded", kind="feature")
    repo.local_path = str(tmp_path)
    db.commit()
    monkeypatch.setattr("app.api.v1.issues.read_agent", lambda: "claude")
    monkeypatch.setattr("app.services.actions.read_agent", lambda: "claude")
    resp = client.post(
        f"/issues/{issue.id}/enqueue/write_doc",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash=ok" in resp.headers["location"]
    db.refresh(issue)
    assert issue.status == "recorded"
    assert job_crud.has_active_for_issue(db, issue.id)


def test_issue_filter_query(client: TestClient, db: Session) -> None:
    _login(client, db)
    repo, _issue = _seed_issue(db, status="support_open", kind="support")
    resp = client.get(f"/repos/{repo.id}/issues?kind=support&github_state=open")
    assert resp.status_code == 200
    assert "人工介入" in resp.text


def _summary_repo(db: Session, *, gh_id: int = 77):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=gh_id,
        account_type="Organization",
        login="acme",
        name="Acme",
        description=None,
        avatar_url=None,
        html_url=None,
    )
    return repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=gh_id,
        name="demo",
        github_full_name="acme/demo",
        description=None,
        html_url="https://github.com/acme/demo",
        default_branch="main",
        private=False,
    )


def _summary_issue(db: Session, repo, *, number: int, kind: str, status: str, state: str = "open"):
    issue = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=7000 + number,
        number=number,
        title=f"issue-{number}",
        body="b",
        html_url=f"https://github.com/acme/demo/issues/{number}",
        author_login="dev",
        github_state=state,
        label_names=[],
        github_updated_at=None,
        action="opened",
    )
    issue.kind = kind
    issue.status = status
    db.commit()
    db.refresh(issue)
    return issue


def test_unfinished_filter_matches_summary_counts(client: TestClient, db: Session) -> None:
    _login(client, db)
    repo = _summary_repo(db)
    _summary_issue(db, repo, number=1, kind="feature", status="recorded")
    _summary_issue(db, repo, number=2, kind="feature", status="pr_opened")
    _summary_issue(db, repo, number=3, kind="feature", status="failed")
    _summary_issue(db, repo, number=4, kind="support", status="support_open")
    _summary_issue(db, repo, number=5, kind="feature", status="recorded", state="closed")

    summary = issue_crud.repo_open_summary(db, repo.id)
    assert summary.feature_unfinished == 2
    assert summary.support_open == 1
    assert summary.failed == 1

    resp = client.get(
        f"/repos/{repo.id}/issues?kind=feature&status=unfinished&github_state=open"
    )
    assert resp.status_code == 200
    assert '<span class="font-mono-data text-slate-900">2</span>' in resp.text
    assert "issue-1" in resp.text
    assert "issue-3" in resp.text
    assert "issue-2" not in resp.text
    assert "issue-5" not in resp.text
    assert 'value="unfinished" selected' in resp.text

    resp = client.get(
        f"/repos/{repo.id}/issues?kind=support&status=support_open&github_state=open"
    )
    assert '<span class="font-mono-data text-slate-900">1</span>' in resp.text
    assert "issue-4" in resp.text

    resp = client.get(f"/repos/{repo.id}/issues?status=failed&github_state=open")
    assert '<span class="font-mono-data text-slate-900">1</span>' in resp.text
    assert "issue-3" in resp.text


def test_exact_status_filter_unchanged(client: TestClient, db: Session) -> None:
    _login(client, db)
    repo = _summary_repo(db, gh_id=78)
    _summary_issue(db, repo, number=1, kind="feature", status="recorded")
    _summary_issue(db, repo, number=2, kind="feature", status="failed")

    resp = client.get(f"/repos/{repo.id}/issues?status=recorded&github_state=open")
    assert resp.status_code == 200
    assert '<span class="font-mono-data text-slate-900">1</span>' in resp.text
    assert "issue-1" in resp.text
    assert "issue-2" not in resp.text


def test_unfinished_value_is_display_only(db: Session) -> None:
    repo = _summary_repo(db, gh_id=79)
    _summary_issue(db, repo, number=1, kind="feature", status="recorded")
    assert issue_crud.list_for_repo(db, repo.id, status="unfinished")[0].status == "recorded"
    assert issue_crud.count_for_repo(db, repo.id, status="unfinished") == 1
