from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import unquote

from fastapi.testclient import TestClient
from sqlalchemy import text
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
_TYPE_ABSENT = object()


def _login(client: TestClient, db: Session) -> str:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    client.cookies.set(COOKIE_NAME, token)
    return csrf_token_for_jti(decode_access_token(token)["jti"])


def _seed_repo(db: Session, *, github_repo_id: int = 650):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=60,
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
        github_repo_id=github_repo_id,
        name="demo",
        github_full_name="acme/demo",
        description=None,
        html_url="https://github.com/acme/demo",
        default_branch="main",
        private=False,
    )


def _seed_issue(
    db: Session,
    repo,
    number: int,
    *,
    title: str | None = None,
    status: str = "recorded",
    kind: str = "feature",
    labels: list[str] | None = None,
    github_state: str = "open",
    github_issue_id: int | None = None,
    github_updated_at: datetime = OLD_UPDATED_AT,
    github_issue_type: str | None = None,
):
    issue = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=github_issue_id or (5000 + number),
        number=number,
        title=title or f"issue-{number}",
        body="old body",
        html_url=f"https://github.com/acme/demo/issues/{number}",
        author_login="old-dev",
        github_state=github_state,
        label_names=labels if labels is not None else ["功能迭代"],
        github_updated_at=github_updated_at,
        action="opened",
        github_issue_type=github_issue_type,
        github_issue_type_set=True,
    )
    issue.status = status
    issue.kind = kind
    db.commit()
    db.refresh(issue)
    return issue


def _remote(
    number: int,
    *,
    issue_id: int | None = None,
    title: str | None = None,
    state: str = "open",
    labels: list | None = None,
    issue_type=_TYPE_ABSENT,
    updated_at: datetime = NEW_UPDATED_AT,
    pull_request: bool = False,
) -> dict:
    data = {
        "id": issue_id or (5000 + number),
        "number": number,
        "title": title or f"remote-{number}",
        "body": f"body-{number}",
        "html_url": f"https://github.com/acme/demo/issues/{number}",
        "state": state,
        "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
        "user": {"login": "new-dev"},
        "labels": labels if labels is not None else [{"name": "功能迭代"}],
    }
    if issue_type is not _TYPE_ABSENT:
        data["type"] = issue_type
    if pull_request:
        data["pull_request"] = {"url": "https://api.github.com/repos/acme/demo/pulls/77"}
    return data


class FakeSyncClient:
    def __init__(self, *, pages=None, prs=None):
        self.pages = pages or {}
        self.prs = prs or {}
        self.page_calls: list[dict] = []
        self.pr_calls: list[int] = []
        self.closed = False

    def list_repository_issues(self, owner, repo, **kwargs):
        self.page_calls.append({"owner": owner, "repo": repo, **kwargs})
        value = self.pages.get(kwargs.get("page"))
        if isinstance(value, Exception):
            raise value
        return value if value is not None else []

    def get_pull_request(self, owner, repo, number):
        self.pr_calls.append(number)
        value = self.prs.get(number)
        if isinstance(value, Exception):
            raise value
        return value or {}

    def close(self):
        self.closed = True


def _use_client(monkeypatch, fake: FakeSyncClient) -> FakeSyncClient:
    monkeypatch.setattr("app.api.v1.issues.GitHubClient", lambda: fake)
    return fake


def test_sync_writes_metadata_soft_deletes_and_refreshes_pr(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo = _seed_repo(db)
    issue1 = _seed_issue(db, repo, 1, title="old-1", github_issue_type="Old")
    issue2 = _seed_issue(db, repo, 2, title="old-2")
    issue3 = _seed_issue(db, repo, 3, title="old-3")
    issue4 = _seed_issue(
        db, repo, 4, title="old-4", status="pending_codegen", github_issue_type="Old"
    )
    issue5 = _seed_issue(db, repo, 5, title="old-5")
    issue9 = _seed_issue(db, repo, 9, title="old-9", status="pr_opened")
    issue5.deleted_at = OLD_UPDATED_AT
    issue9.pr_number = 42
    issue9.pr_state = "open"
    issue9.pr_state_updated_at = OLD_UPDATED_AT
    db.commit()
    job = job_crud.enqueue(db, issue_id=issue3.id, repository_id=repo.id, action="write_doc")

    remote = [
        _remote(
            1,
            title="new-1",
            labels=["功能迭代", {"name": "bug"}, {"name": "功能迭代"}, ""],
            issue_type={"id": 1, "name": "Bug"},
        ),
        _remote(3, title="new-3", state="closed"),
        _remote(4, title="new-4", labels=["人工介入"], issue_type=None),
        _remote(5, title="should-not-revive"),
        _remote(6, title="new-6", issue_type={"id": 1, "name": "Bug"}),
        _remote(9, title="new-9"),
        _remote(77, pull_request=True),
    ]
    merged_at = NEW_UPDATED_AT
    fake = _use_client(
        monkeypatch,
        FakeSyncClient(
            pages={1: remote},
            prs={
                42: {
                    "number": 42,
                    "state": "closed",
                    "merged": True,
                    "merged_at": merged_at.isoformat().replace("+00:00", "Z"),
                    "updated_at": merged_at.isoformat().replace("+00:00", "Z"),
                    "html_url": "https://github.com/acme/demo/pull/42",
                }
            },
        ),
    )

    next_url = f"/repos/{repo.id}/issues?kind=feature&status=recorded&github_state=open&page=2"
    resp = client.post(
        f"/repos/{repo.id}/issues/sync",
        data={"csrf_token": csrf, "next": next_url},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = unquote(resp.headers["location"])
    assert location.startswith(next_url)
    assert "flash=ok" in location
    assert "同步完成" in location
    assert "检查 6 条" in location
    assert "新增 1 条" in location
    assert "软删 1 条" in location
    assert "PR 刷新 1 条" in location
    assert fake.closed is True
    assert fake.page_calls[0]["state"] == "all"
    assert fake.page_calls[0]["sort"] == "created"
    assert fake.page_calls[0]["direction"] == "asc"
    assert fake.pr_calls == [42]

    db.refresh(issue1)
    assert issue1.title == "new-1"
    assert issue1.body == "body-1"
    assert issue1.author_login == "new-dev"
    assert issue1.github_issue_type == "Bug"
    assert issue1.label_names == ["功能迭代", "bug"]
    assert issue1.github_updated_at == NEW_UPDATED_AT

    db.refresh(issue2)
    assert issue2.deleted_at is not None
    assert issue2.status == "recorded"
    assert issue2.kind == "feature"
    assert issue2.github_state == "open"
    assert issue2.title == "old-2"

    db.refresh(issue3)
    assert issue3.github_state == "closed"
    db.refresh(job)
    assert job.status == "cancelled"

    db.refresh(issue4)
    assert issue4.status == "pending_codegen"
    assert issue4.kind == "feature"
    assert issue4.label_names == ["人工介入"]
    assert issue4.github_issue_type is None

    db.refresh(issue5)
    assert issue5.deleted_at == OLD_UPDATED_AT
    assert issue5.title == "old-5"

    db.refresh(issue9)
    assert issue9.pr_state == "merged"
    assert issue9.pr_merged_at == merged_at
    assert issue9.pr_url == "https://github.com/acme/demo/pull/42"

    created = issue_crud.get_by_repo_number(db, repo.id, 6)
    assert created is not None
    assert created.kind == "feature"
    assert created.status == "recorded"
    assert created.github_issue_type == "Bug"
    assert created.label_names == ["功能迭代"]

    listing = client.get(f"/repos/{repo.id}/issues?github_state=open")
    assert f'href="/issues/{issue2.id}"' not in listing.text
    assert f'href="/issues/{issue1.id}"' in listing.text


def test_sync_reads_every_page_and_skips_pr_items(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo = _seed_repo(db, github_repo_id=651)
    monkeypatch.setattr("app.services.issue_sync.PER_PAGE", 2)
    fake = _use_client(
        monkeypatch,
        FakeSyncClient(
            pages={
                1: [_remote(1), _remote(77, pull_request=True)],
                2: [_remote(2)],
            }
        ),
    )

    resp = client.post(
        f"/repos/{repo.id}/issues/sync",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert [call["page"] for call in fake.page_calls] == [1, 2]
    assert issue_crud.get_by_repo_number(db, repo.id, 1) is not None
    assert issue_crud.get_by_repo_number(db, repo.id, 2) is not None
    assert issue_crud.get_by_repo_number(db, repo.id, 77) is None
    assert "检查 2 条" in unquote(resp.headers["location"])


def test_sync_read_failure_writes_nothing(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo = _seed_repo(db, github_repo_id=652)
    local = _seed_issue(db, repo, 1, title="local-1")
    monkeypatch.setattr("app.services.issue_sync.PER_PAGE", 2)
    _use_client(
        monkeypatch,
        FakeSyncClient(
            pages={
                1: [_remote(1, title="new-1"), _remote(2)],
                2: GitHubAPIError("rate limited", status_code=429),
            }
        ),
    )

    resp = client.post(
        f"/repos/{repo.id}/issues/sync",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = unquote(resp.headers["location"])
    assert "flash=error" in location
    assert "限流" in location
    assert "未写入任何变更" in location

    db.refresh(local)
    assert local.title == "local-1"
    assert local.deleted_at is None
    assert issue_crud.get_by_repo_number(db, repo.id, 2) is None


def test_sync_identity_mismatch_is_not_overwritten(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo = _seed_repo(db, github_repo_id=653)
    local = _seed_issue(db, repo, 1, title="local-1", github_issue_id=111)
    _use_client(
        monkeypatch,
        FakeSyncClient(pages={1: [_remote(1, issue_id=999, title="remote-1")]}),
    )

    resp = client.post(
        f"/repos/{repo.id}/issues/sync",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    location = unquote(resp.headers["location"])
    assert resp.status_code == 303
    assert "flash=error" in location
    assert "ID 与本地不一致" in location
    db.refresh(local)
    assert local.title == "local-1"
    assert local.deleted_at is None


def test_sync_pr_404_and_429_failures(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo = _seed_repo(db, github_repo_id=654)
    issue1 = _seed_issue(db, repo, 1)
    issue2 = _seed_issue(db, repo, 2)
    issue3 = _seed_issue(db, repo, 3)
    for issue, pr_number in ((issue1, 41), (issue2, 42), (issue3, 43)):
        issue.pr_number = pr_number
        issue.pr_state = "open"
        issue.pr_state_updated_at = OLD_UPDATED_AT
    db.commit()
    fake = _use_client(
        monkeypatch,
        FakeSyncClient(
            pages={1: [_remote(1), _remote(2), _remote(3)]},
            prs={
                41: GitHubAPIError("not found", status_code=404),
                42: GitHubAPIError("rate limited", status_code=429),
            },
        ),
    )

    resp = client.post(
        f"/repos/{repo.id}/issues/sync",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    location = unquote(resp.headers["location"])
    assert resp.status_code == 303
    assert "flash=error" in location
    assert "PR #41 已不存在" in location
    assert "PR 刷新因限流中止" in location
    assert fake.pr_calls == [41, 42]


def test_sync_pr_old_snapshot_does_not_roll_back(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo = _seed_repo(db, github_repo_id=655)
    issue = _seed_issue(db, repo, 1, status="pr_opened")
    issue.pr_number = 42
    issue.pr_state = "merged"
    issue.pr_state_updated_at = NEW_UPDATED_AT
    db.commit()
    _use_client(
        monkeypatch,
        FakeSyncClient(
            pages={1: [_remote(1)]},
            prs={
                42: {
                    "number": 42,
                    "state": "open",
                    "updated_at": OLD_UPDATED_AT.isoformat().replace("+00:00", "Z"),
                }
            },
        ),
    )

    resp = client.post(
        f"/repos/{repo.id}/issues/sync",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(issue)
    assert issue.pr_state == "merged"
    assert issue.pr_state_updated_at == NEW_UPDATED_AT


def test_sync_lock_blocks_without_github_calls(
    client: TestClient, db: Session, monkeypatch, engine
) -> None:
    csrf = _login(client, db)
    repo = _seed_repo(db, github_repo_id=656)
    fake = FakeSyncClient(pages={1: [_remote(1)]})
    _use_client(monkeypatch, fake)

    key = f"github_workflow:issue-sync:{repo.id}"
    with engine.connect() as lock_conn:
        lock_conn.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": key})
        try:
            resp = client.post(
                f"/repos/{repo.id}/issues/sync",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
        finally:
            lock_conn.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key}
            )
            lock_conn.commit()

    location = unquote(resp.headers["location"])
    assert resp.status_code == 303
    assert "flash=error" in location
    assert "该仓库正在同步" in location
    assert fake.page_calls == []


def test_sync_requires_csrf_login_and_post(client: TestClient, db: Session) -> None:
    repo = _seed_repo(db, github_repo_id=657)

    resp = client.post(f"/repos/{repo.id}/issues/sync", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    csrf = _login(client, db)
    resp = client.post(
        f"/repos/{repo.id}/issues/sync",
        data={"csrf_token": csrf + "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    resp = client.get(f"/repos/{repo.id}/issues/sync", follow_redirects=False)
    assert resp.status_code == 405


def test_sync_keeps_filters_and_rejects_open_redirect(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo = _seed_repo(db, github_repo_id=658)
    _seed_issue(db, repo, 1)
    _use_client(monkeypatch, FakeSyncClient(pages={1: [_remote(1)]}))

    next_url = (
        f"/repos/{repo.id}/issues?kind=feature&status=recorded"
        "&github_state=open&page=2&flash=ok&msg=old"
    )
    resp = client.post(
        f"/repos/{repo.id}/issues/sync",
        data={"csrf_token": csrf, "next": next_url},
        follow_redirects=False,
    )
    location = resp.headers["location"]
    assert "kind=feature" in location
    assert "status=recorded" in location
    assert "github_state=open" in location
    assert "page=2" in location
    assert "msg=old" not in location
    assert location.count("flash=") == 1

    resp = client.post(
        f"/repos/{repo.id}/issues/sync",
        data={"csrf_token": csrf, "next": "https://evil.example/repos/1/issues"},
        follow_redirects=False,
    )
    assert resp.headers["location"].startswith(f"/repos/{repo.id}/issues?flash=")
