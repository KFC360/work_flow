from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.crud import issue as issue_crud
from app.crud import repository as repository_crud
from app.models.issue import Issue

PR_STATE_NONE = "none"
PR_STATE_OPEN = "open"
PR_STATE_MERGED = "merged"
PR_STATE_CLOSED = "closed"

PR_STATES = {PR_STATE_NONE, PR_STATE_OPEN, PR_STATE_MERGED, PR_STATE_CLOSED}

SUPPORTED_PR_ACTIONS = {"opened", "reopened", "closed", "edited"}

PR_STATE_LABELS = {
    PR_STATE_OPEN: "开放",
    PR_STATE_MERGED: "已合并",
    PR_STATE_CLOSED: "已关闭（未合并）",
    PR_STATE_NONE: "状态未同步",
}


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def event_time(pr: dict[str, Any]) -> datetime | None:
    """Return the PR event time, falling back through GitHub's timestamps."""
    for key in ("updated_at", "merged_at", "closed_at", "created_at"):
        parsed = parse_dt(pr.get(key))
        if parsed is not None:
            return parsed
    return None


def _merged(pr: dict[str, Any]) -> bool:
    return bool(pr.get("merged")) or bool(pr.get("merged_at"))


def _derived_state(pr: dict[str, Any]) -> tuple[str, datetime | None]:
    if pr.get("state") == "open" and not _merged(pr):
        return PR_STATE_OPEN, None
    if _merged(pr):
        merged_at = parse_dt(pr.get("merged_at")) or event_time(pr)
        return PR_STATE_MERGED, merged_at
    return PR_STATE_CLOSED, None


def derive_state(pr: dict[str, Any], action: str) -> tuple[str, datetime | None]:
    """Map a pull_request action/payload to (pr_state, pr_merged_at)."""
    if action in {"opened", "reopened"}:
        return PR_STATE_OPEN, None
    if action == "closed":
        if _merged(pr):
            return PR_STATE_MERGED, parse_dt(pr.get("merged_at")) or event_time(pr)
        return PR_STATE_CLOSED, None
    # edited: trust the current payload, including an already-merged/closed PR.
    return _derived_state(pr)


def initial_state(pr: dict[str, Any]) -> tuple[str, datetime | None, datetime | None]:
    """Initial state for a PR just created (or adopted) through the API.

    Returns (pr_state, pr_merged_at, pr_state_updated_at). A missing state field
    conservatively becomes open so a later pull_request event can correct it.
    """
    if not isinstance(pr, dict) or not pr:
        return PR_STATE_OPEN, None, None
    if _merged(pr):
        state, merged_at = PR_STATE_MERGED, parse_dt(pr.get("merged_at")) or event_time(pr)
    elif pr.get("state"):
        state, merged_at = _derived_state(pr)
    else:
        # Missing state fields: conservatively wait for a pull_request event.
        state, merged_at = PR_STATE_OPEN, None
    if state == PR_STATE_OPEN:
        merged_at = None
    return state, merged_at, parse_dt(pr.get("updated_at"))


def apply_initial_state(issue: Issue, pr: dict[str, Any]) -> None:
    state, merged_at, updated_at = initial_state(pr)
    issue.pr_state = state
    issue.pr_state_updated_at = updated_at
    issue.pr_merged_at = merged_at


def _event_wins(current: datetime | None, incoming: datetime | None) -> bool:
    if incoming is None:
        return True
    if current is None:
        return True
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return incoming >= current


def apply_pull_request_event(db: Session, payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Apply one pull_request payload using local data only.

    Returns (handled, ignored_reason). ``handled`` is True for both applied and
    stale-but-valid events; ignored events have a human-readable reason.
    """
    action = payload.get("action") or ""
    if action not in SUPPORTED_PR_ACTIONS:
        return False, f"unsupported pull_request action {action}"

    repo_meta = payload.get("repository") or {}
    github_repo_id = repo_meta.get("id")
    if not isinstance(github_repo_id, int) or isinstance(github_repo_id, bool):
        return False, "缺少仓库编号"

    repo = repository_crud.get_by_github_repo_id(db, github_repo_id)
    if repo is None:
        return False, "仓库未收录"

    pr = payload.get("pull_request") or {}
    number = pr.get("number")
    if not isinstance(number, int) or isinstance(number, bool):
        return False, "缺少 PR 编号"

    base = pr.get("base") or {}
    base_repo = base.get("repo") or {}
    base_repo_id = base_repo.get("id")
    if isinstance(base_repo_id, int) and not isinstance(base_repo_id, bool):
        if base_repo_id != github_repo_id:
            return False, "跨仓库 PR"

    matches = issue_crud.list_by_pr_number(db, repo.id, number)
    if not matches:
        return False, "未匹配到 Issue"
    if len(matches) > 1:
        return False, "同一 PR 匹配到多个 Issue，等待人工处理"
    issue = matches[0]

    state, merged_at = derive_state(pr, action)
    incoming_time = event_time(pr)
    if not _event_wins(issue.pr_state_updated_at, incoming_time):
        # Late event: accept the delivery but do not roll the state backwards.
        return True, None

    issue.pr_state = state
    issue.pr_merged_at = merged_at
    if incoming_time is not None:
        issue.pr_state_updated_at = incoming_time
    pr_url = pr.get("html_url")
    if isinstance(pr_url, str) and pr_url.strip():
        issue.pr_url = pr_url.strip()
    db.flush()
    return True, None
