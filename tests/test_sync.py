from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import repository as repository_crud
from app.crud import webhook_delivery as delivery_crud
from app.services.github_api import GitHubAPIError
from app.tasks.inbox import process_one_delivery


class FakeClient:
    def __init__(self, behavior: str = "ok"):
        self.behavior = behavior
        self.calls: list[str] = []

    def close(self) -> None:
        pass

    def get_repository(self, repo_id: int):
        self.calls.append(f"repo:{repo_id}")
        if self.behavior == "404":
            raise GitHubAPIError("not found", status_code=404)
        if self.behavior == "403":
            raise GitHubAPIError("forbidden", status_code=403)
        if self.behavior == "500":
            raise GitHubAPIError("server", status_code=500)
        return {
            "id": repo_id,
            "name": "demo",
            "full_name": "acme/demo",
            "description": "d",
            "html_url": "https://github.com/acme/demo",
            "default_branch": "main",
            "private": False,
            "language": "Python",
            "stargazers_count": 1234,
            "forks_count": 56,
            "open_issues_count": 7,
            "topics": ["fastapi", " fastapi ", "", "ops", 42],
            "license": {"spdx_id": "MIT", "name": "MIT License"},
            "archived": False,
            "disabled": False,
            "pushed_at": "2026-02-03T04:05:06Z",
            "homepage": " https://example.com ",
            "visibility": "public",
            "owner": {"id": 7, "login": "acme", "type": "Organization"},
        }

    def get_org(self, login: str):
        self.calls.append(f"org:{login}")
        return {
            "id": 7,
            "login": "acme",
            "name": "Acme Inc",
            "description": None,
            "avatar_url": None,
            "html_url": "https://github.com/acme",
        }

    def get_user(self, login: str):
        self.calls.append(f"user:{login}")
        return {"id": 8, "login": login, "name": login, "bio": None, "avatar_url": None, "html_url": f"https://github.com/{login}"}


def _queue(db: Session, delivery_id: str, payload: dict) -> None:
    delivery_crud.create_queued(
        db,
        delivery_id=delivery_id,
        event="issues",
        action=payload.get("action"),
        repository_id=payload["repository"]["id"],
        payload=payload,
    )


def test_inbox_sync_org_and_feature(db: Session) -> None:
    payload = {
        "action": "opened",
        "issue": {
            "id": 11,
            "number": 3,
            "title": "feat",
            "body": "body",
            "html_url": "https://github.com/acme/demo/issues/3",
            "state": "open",
            "updated_at": "2026-01-02T00:00:00Z",
            "user": {"login": "dev"},
            "labels": [{"name": "功能迭代"}],
        },
        "repository": {"id": 100},
    }
    _queue(db, "s1", payload)
    client = FakeClient()
    assert process_one_delivery(db, client) is True
    company = company_crud.get_by_github_account_id(db, 7)
    assert company is not None
    assert company.name == "Acme Inc"
    repo = repository_crud.get_by_github_repo_id(db, 100)
    assert repo is not None
    assert repo.local_path is None
    row = delivery_crud.get(db, "s1")
    assert row is not None
    assert row.status == "succeeded"


def test_inbox_403_failed(db: Session) -> None:
    payload = {
        "action": "opened",
        "issue": {
            "id": 1,
            "number": 1,
            "title": "t",
            "body": "",
            "html_url": "u",
            "state": "open",
            "user": {"login": "a"},
            "labels": [],
        },
        "repository": {"id": 200},
    }
    _queue(db, "f1", payload)
    process_one_delivery(db, FakeClient("403"))
    row = delivery_crud.get(db, "f1")
    assert row is not None
    assert row.status == "failed"


def test_inbox_404_ignored(db: Session) -> None:
    payload = {
        "action": "opened",
        "issue": {
            "id": 1,
            "number": 1,
            "title": "t",
            "body": "",
            "html_url": "u",
            "state": "open",
            "user": {"login": "a"},
            "labels": [],
        },
        "repository": {"id": 201},
    }
    _queue(db, "i1", payload)
    process_one_delivery(db, FakeClient("404"))
    row = delivery_crud.get(db, "i1")
    assert row is not None
    assert row.status == "ignored"


def test_inbox_500_retry(db: Session) -> None:
    payload = {
        "action": "opened",
        "issue": {
            "id": 1,
            "number": 1,
            "title": "t",
            "body": "",
            "html_url": "u",
            "state": "open",
            "user": {"login": "a"},
            "labels": [],
        },
        "repository": {"id": 202},
    }
    _queue(db, "r1", payload)
    process_one_delivery(db, FakeClient("500"))
    row = delivery_crud.get(db, "r1")
    assert row is not None
    assert row.status == "retry"
    assert row.next_retry_at is not None


def test_rename_keeps_local_path(db: Session) -> None:
    payload = {
        "action": "opened",
        "issue": {
            "id": 1,
            "number": 1,
            "title": "t",
            "body": "",
            "html_url": "u",
            "state": "open",
            "user": {"login": "a"},
            "labels": [{"name": "功能迭代"}],
        },
        "repository": {"id": 300},
    }
    _queue(db, "n1", payload)
    process_one_delivery(db, FakeClient())
    repo = repository_crud.get_by_github_repo_id(db, 300)
    assert repo is not None
    repo.local_path = "/tmp/demo"
    repo.doc_dir = "docs"
    db.commit()

    class RenameClient(FakeClient):
        def get_repository(self, repo_id: int):
            data = super().get_repository(repo_id)
            data["full_name"] = "acme/demo-renamed"
            data["name"] = "demo-renamed"
            return data

    _queue(db, "n2", payload)
    process_one_delivery(db, RenameClient())
    repo2 = repository_crud.get_by_github_repo_id(db, 300)
    assert repo2 is not None
    assert repo2.github_full_name == "acme/demo-renamed"
    assert repo2.local_path == "/tmp/demo"


def _payload(repo_id: int) -> dict:
    return {
        "action": "opened",
        "issue": {
            "id": repo_id + 1,
            "number": 1,
            "title": "t",
            "body": "",
            "html_url": "u",
            "state": "open",
            "user": {"login": "a"},
            "labels": [{"name": "功能迭代"}],
        },
        "repository": {"id": repo_id},
    }


def test_sync_writes_repository_github_meta(db: Session) -> None:
    _queue(db, "meta1", _payload(400))
    process_one_delivery(db, FakeClient())
    repo = repository_crud.get_by_github_repo_id(db, 400)
    assert repo is not None
    assert repo.language == "Python"
    assert repo.stargazers_count == 1234
    assert repo.forks_count == 56
    assert repo.open_issues_count == 7
    assert repo.topics == ["fastapi", "ops"]
    assert repo.license_spdx == "MIT"
    assert repo.license_name == "MIT License"
    assert repo.archived is False
    assert repo.disabled is False
    assert repo.pushed_at == datetime(2026, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
    assert repo.homepage == "https://example.com"
    assert repo.visibility == "public"


def test_sync_normalizes_missing_and_unknown_values(db: Session) -> None:
    class NormalizeClient(FakeClient):
        def get_repository(self, repo_id: int):
            data = super().get_repository(repo_id)
            data.update(
                {
                    "language": "",
                    "stargazers_count": 0,
                    "forks_count": None,
                    "open_issues_count": "12",
                    "topics": None,
                    "license": {"spdx_id": "NOASSERTION", "name": "Other"},
                    "archived": True,
                    "disabled": True,
                    "pushed_at": "2026-01-02T03:04:05",
                    "homepage": "   ",
                    "visibility": "",
                }
            )
            return data

    _queue(db, "meta2", _payload(401))
    process_one_delivery(db, NormalizeClient())
    repo = repository_crud.get_by_github_repo_id(db, 401)
    assert repo is not None
    assert repo.language is None
    assert repo.stargazers_count == 0
    assert repo.forks_count is None
    assert repo.open_issues_count is None
    assert repo.topics == []
    assert repo.license_spdx is None
    assert repo.license_name == "Other"
    assert repo.archived is True
    assert repo.disabled is True
    assert repo.pushed_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert repo.homepage is None
    assert repo.visibility is None


def _issue_payload(
    repo_id: int,
    *,
    action: str,
    updated_at: str,
    labels: list | None = None,
    issue_type=...,
) -> dict:
    issue = {
        "id": repo_id + 1,
        "number": 1,
        "title": "t",
        "body": "b",
        "html_url": "u",
        "state": "open",
        "updated_at": updated_at,
        "user": {"login": "a"},
        "labels": labels if labels is not None else [{"name": "功能迭代"}],
    }
    if issue_type is not ...:
        issue["type"] = issue_type
    return {"action": action, "issue": issue, "repository": {"id": repo_id}}


def _get_issue(db: Session, github_repo_id: int):
    repo = repository_crud.get_by_github_repo_id(db, github_repo_id)
    assert repo is not None
    return issue_crud.get_by_repo_number(db, repo.id, 1)


def test_webhook_type_and_untyped(db: Session) -> None:
    _queue(
        db,
        "type1",
        _issue_payload(
            500,
            action="opened",
            updated_at="2026-01-01T00:00:00Z",
            issue_type={"id": 1, "name": "Bug"},
        ),
    )
    assert process_one_delivery(db, FakeClient()) is True
    issue = _get_issue(db, 500)
    assert issue is not None
    assert issue.github_issue_type == "Bug"

    _queue(
        db,
        "type2",
        _issue_payload(
            500,
            action="untyped",
            updated_at="2026-01-02T00:00:00Z",
            issue_type=None,
        ),
    )
    assert process_one_delivery(db, FakeClient()) is True
    db.refresh(issue)
    assert issue.github_issue_type is None


def test_typed_does_not_change_kind_and_missing_type_is_preserved(db: Session) -> None:
    _queue(
        db,
        "type3",
        _issue_payload(
            501,
            action="opened",
            updated_at="2026-01-01T00:00:00Z",
            issue_type={"id": 1, "name": "Bug"},
        ),
    )
    process_one_delivery(db, FakeClient())
    issue = _get_issue(db, 501)
    assert issue is not None
    assert issue.kind == "feature"
    assert issue.status == "recorded"

    _queue(
        db,
        "type4",
        _issue_payload(
            501,
            action="typed",
            updated_at="2026-01-02T00:00:00Z",
            issue_type={"id": 2, "name": "Task"},
        ),
    )
    process_one_delivery(db, FakeClient())
    db.refresh(issue)
    assert issue.github_issue_type == "Task"
    assert issue.kind == "feature"
    assert issue.status == "recorded"

    # A payload without the type key must not clear the stored value.
    _queue(
        db,
        "type5",
        _issue_payload(
            501,
            action="edited",
            updated_at="2026-01-03T00:00:00Z",
        ),
    )
    process_one_delivery(db, FakeClient())
    db.refresh(issue)
    assert issue.github_issue_type == "Task"


def test_webhook_labels_are_trimmed_and_deduped(db: Session) -> None:
    _queue(
        db,
        "labels1",
        _issue_payload(
            502,
            action="opened",
            updated_at="2026-01-01T00:00:00Z",
            labels=[
                {"name": "功能迭代"},
                " bug ",
                {"name": "   "},
                "bug",
                {"name": "功能迭代"},
                7,
            ],
        ),
    )
    process_one_delivery(db, FakeClient())
    issue = _get_issue(db, 502)
    assert issue is not None
    assert issue.label_names == ["功能迭代", "bug"]


def test_resync_updates_meta_and_keeps_local_config(db: Session) -> None:
    _queue(db, "meta3", _payload(402))
    process_one_delivery(db, FakeClient())
    repo = repository_crud.get_by_github_repo_id(db, 402)
    assert repo is not None
    repo.local_path = "/tmp/demo"
    repo.doc_dir = "docs"
    db.commit()

    class UpdatedClient(FakeClient):
        def get_repository(self, repo_id: int):
            data = super().get_repository(repo_id)
            data["stargazers_count"] = 9999
            data["topics"] = ["new-topic"]
            data["archived"] = True
            return data

    _queue(db, "meta4", _payload(402))
    process_one_delivery(db, UpdatedClient())
    repo2 = repository_crud.get_by_github_repo_id(db, 402)
    assert repo2 is not None
    assert repo2.stargazers_count == 9999
    assert repo2.topics == ["new-topic"]
    assert repo2.archived is True
    assert repo2.local_path == "/tmp/demo"
    assert repo2.doc_dir == "docs"
