from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.services.github_api import GitHubAPIError, GitHubClient
from app.services.issue_notify import maybe_notify_new_issue
from app.services.pr_sync import apply_pull_request_event

SUPPORTED_ISSUE_ACTIONS = {
    "opened",
    "edited",
    "labeled",
    "unlabeled",
    "closed",
    "reopened",
    "typed",
    "untyped",
    "deleted",
}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _issue_type_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _text(value.get("name"))
    if isinstance(value, str):
        return _text(value)
    return None


def issue_type_name(value: Any) -> str | None:
    """GitHub Issue type name; accepts the REST object or a plain string."""
    return _issue_type_name(value)


def label_names_from_payload(value: Any) -> list[str]:
    """Normalize GitHub labels: dict or string items, trimmed, deduped, in order."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            name = _text(item.get("name"))
        elif isinstance(item, str):
            name = _text(item)
        else:
            name = None
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _topic_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    topics: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        topic = item.strip()
        if not topic or topic in seen:
            continue
        seen.add(topic)
        topics.append(topic)
    return topics


def _license_fields(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    spdx = _text(value.get("spdx_id"))
    if spdx == "NOASSERTION":
        spdx = None
    return spdx, _text(value.get("name"))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def sync_owner_and_repo(db: Session, client: GitHubClient, github_repo_id: int):
    repo_data = client.get_repository(github_repo_id)
    owner = repo_data.get("owner") or {}
    owner_login = owner.get("login") or ""
    owner_type = owner.get("type") or "User"
    account_id = int(owner["id"])

    if owner_type == "Organization":
        org = client.get_org(owner_login)
        company = company_crud.upsert_from_github(
            db,
            github_account_id=account_id,
            account_type="Organization",
            login=org.get("login") or owner_login,
            name=org.get("name") or owner_login,
            description=org.get("description"),
            avatar_url=org.get("avatar_url"),
            html_url=org.get("html_url"),
        )
    else:
        user = client.get_user(owner_login)
        company = company_crud.upsert_from_github(
            db,
            github_account_id=account_id,
            account_type="User",
            login=user.get("login") or owner_login,
            name=user.get("name") or owner_login,
            description=user.get("bio"),
            avatar_url=user.get("avatar_url"),
            html_url=user.get("html_url"),
        )

    license_spdx, license_name = _license_fields(repo_data.get("license"))

    repo = repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=int(repo_data["id"]),
        name=repo_data.get("name") or "",
        github_full_name=repo_data.get("full_name") or "",
        description=repo_data.get("description"),
        html_url=repo_data.get("html_url"),
        default_branch=repo_data.get("default_branch") or "main",
        private=bool(repo_data.get("private")),
        language=_text(repo_data.get("language")),
        stargazers_count=_int_or_none(repo_data.get("stargazers_count")),
        forks_count=_int_or_none(repo_data.get("forks_count")),
        open_issues_count=_int_or_none(repo_data.get("open_issues_count")),
        topics=_topic_list(repo_data.get("topics")),
        license_spdx=license_spdx,
        license_name=license_name,
        archived=bool(repo_data.get("archived")),
        disabled=bool(repo_data.get("disabled")),
        pushed_at=_parse_dt(repo_data.get("pushed_at")),
        homepage=_text(repo_data.get("homepage")),
        visibility=_text(repo_data.get("visibility")),
    )
    return company, repo


def apply_issue_action(db: Session, repo_id: int, payload: dict[str, Any]) -> bool:
    """Apply one issues payload; return False when the action is unsupported."""
    action = payload.get("action") or ""
    if action not in SUPPORTED_ISSUE_ACTIONS:
        return False
    issue = payload.get("issue") or {}
    user = issue.get("user") or {}
    row, created = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo_id,
        github_issue_id=int(issue["id"]),
        number=int(issue["number"]),
        title=issue.get("title") or "",
        body=issue.get("body") or "",
        html_url=issue.get("html_url") or "",
        author_login=user.get("login") or "",
        github_state=issue.get("state") or "open",
        label_names=label_names_from_payload(issue.get("labels")),
        github_updated_at=_parse_dt(issue.get("updated_at")),
        action=action,
        github_issue_type=issue_type_name(issue.get("type")),
        github_issue_type_set=("type" in issue),
    )
    if action == "closed" and row.github_state == "closed" and row.deleted_at is None:
        # A stale closed event after a newer reopened must not cancel work.
        job_crud.cancel_queued_for_issue(db, row.id)
    repo = repository_crud.get(db, repo_id)
    if repo is not None:
        maybe_notify_new_issue(db, repo, row, created=created)
    return True


def refresh_issue_from_github(
    db: Session, client: GitHubClient, issue, repo
):
    """Fetch one Issue from GitHub and upsert its metadata via the webhook path.

    Only metadata is written. Local design-doc fields, PR fields, last_error and
    Jobs are left untouched. An identity mismatch fails closed and writes nothing.
    """
    full_name = repo.github_full_name or ""
    owner, _, name = full_name.partition("/")
    if not owner or not name:
        raise GitHubAPIError("invalid repository full name", status_code=409)

    payload = client.get_issue(owner, name, issue.number)
    if not isinstance(payload, dict):
        raise GitHubAPIError("issue identity mismatch", status_code=409)
    if (
        _int_or_none(payload.get("id")) != issue.github_issue_id
        or _int_or_none(payload.get("number")) != issue.number
    ):
        raise GitHubAPIError("issue identity mismatch", status_code=409)

    user = payload.get("user") or {}
    row, _created = issue_crud.upsert_from_webhook(
        db,
        repository_id=issue.repository_id,
        github_issue_id=payload["id"],
        number=payload["number"],
        title=payload.get("title") or "",
        body=payload.get("body") or "",
        html_url=payload.get("html_url") or "",
        author_login=user.get("login") or "",
        github_state=payload.get("state") or "open",
        label_names=label_names_from_payload(payload.get("labels")),
        github_updated_at=_parse_dt(payload.get("updated_at")),
        action="edited",
        github_issue_type=issue_type_name(payload.get("type")),
        github_issue_type_set=("type" in payload),
    )
    return row


def process_issue_delivery(
    db: Session, client: GitHubClient, payload: dict[str, Any]
) -> bool:
    """Sync company/repo, then apply an Issue action. False means ignored."""
    repo_meta = payload.get("repository") or {}
    github_repo_id = repo_meta.get("id")
    if github_repo_id is None:
        raise GitHubAPIError("missing repository.id", status_code=400)
    _, repo = sync_owner_and_repo(db, client, int(github_repo_id))
    return apply_issue_action(db, repo.id, payload)


def process_pull_request_delivery(
    db: Session, payload: dict[str, Any]
) -> tuple[bool, str | None]:
    """Apply a PR event using only local repository/Issue data (never GitHub API)."""
    return apply_pull_request_event(db, payload)


def process_delivery_payload(db: Session, client: GitHubClient, payload: dict[str, Any]) -> bool:
    """Backwards-compatible issues-entry point used by older callers."""
    return process_issue_delivery(db, client, payload)
