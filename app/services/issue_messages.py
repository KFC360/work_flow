from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.crud import issue as issue_crud
from app.crud import issue_message as message_crud
from app.crud import repository as repository_crud
from app.models.issue import Issue
from app.models.repository import Repository
from app.services.github_api import GitHubAPIError
from app.services.markdown_render import render_issue_body
from app.services.pr_sync import parse_dt

EVENT_LABELS = {
    "closed": "关闭了 Issue",
    "reopened": "重新打开了 Issue",
    "typed": "设置了 Issue 类型",
    "untyped": "移除了 Issue 类型",
    "pr_merged": "合并了关联 PR",
    "pr_closed": "关闭了关联 PR（未合并）",
}

COMMENT_PER_PAGE = 100


def _split_full_name(repo: Repository) -> tuple[str, str] | None:
    owner, _, name = (repo.github_full_name or "").partition("/")
    if not owner or not name or "/" in name:
        return None
    return owner, name


def _comment_times(item: dict[str, Any]) -> tuple[datetime, datetime | None]:
    created = parse_dt(item.get("created_at")) or datetime.now(timezone.utc)
    updated = parse_dt(item.get("updated_at"))
    return created, updated


def upsert_comment_payload(
    db: Session,
    issue: Issue,
    item: dict[str, Any],
    *,
    deleted: bool = False,
    commit: bool = False,
) -> None:
    comment_id = item.get("id")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool):
        return
    user = item.get("user") or {}
    occurred_at, updated_at = _comment_times(item)
    message_crud.upsert_comment(
        db,
        issue_id=issue.id,
        github_comment_id=comment_id,
        author_login=(user.get("login") if isinstance(user, dict) else None) or "",
        body=item.get("body") or "",
        occurred_at=occurred_at,
        github_updated_at=updated_at,
        deleted=deleted,
        commit=commit,
    )


def sync_issue_comments(
    db: Session,
    client,
    repo: Repository,
    issue: Issue,
    *,
    commit: bool = False,
) -> int:
    """Fetch all comments for one issue. Returns count written; errors propagate
    only as GitHubAPIError — callers may swallow to keep issue sync alive."""
    parts = _split_full_name(repo)
    if parts is None:
        return 0
    owner, name = parts
    written = 0
    page = 1
    while True:
        data = client.list_issue_comments(
            owner, name, issue.number, page=page, per_page=COMMENT_PER_PAGE
        )
        if not isinstance(data, list):
            break
        for item in data:
            if isinstance(item, dict):
                upsert_comment_payload(db, issue, item, deleted=False, commit=False)
                written += 1
        if len(data) < COMMENT_PER_PAGE:
            break
        page += 1
    if commit:
        db.commit()
    else:
        db.flush()
    return written


def sync_issue_comments_safe(
    db: Session,
    client,
    repo: Repository,
    issue: Issue,
    *,
    commit: bool = False,
) -> int:
    try:
        return sync_issue_comments(db, client, repo, issue, commit=commit)
    except GitHubAPIError as exc:
        logger.warning(
            f"issue #{issue.number} comments sync failed: {exc}"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 — keep parent sync alive
        logger.warning(f"issue #{issue.number} comments sync unexpected: {exc}")
        return 0


def record_issue_action_event(
    db: Session,
    issue: Issue,
    *,
    action: str,
    actor_login: str,
    extra: str = "",
    occurred_at: datetime | None = None,
    commit: bool = False,
) -> None:
    if action not in {"closed", "reopened", "typed", "untyped"}:
        return
    when = occurred_at or datetime.now(timezone.utc)
    label = EVENT_LABELS.get(action, action)
    body = label
    if extra:
        body = f"{label}：{extra}"
    # One row per action occurrence keyed by second — collapses exact duplicates.
    key = f"{action}:{when.astimezone(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    message_crud.upsert_event(
        db,
        issue_id=issue.id,
        event_type=action,
        event_key=key,
        author_login=actor_login or "",
        body=body,
        occurred_at=when,
        commit=commit,
    )


def record_pr_state_event(
    db: Session,
    issue: Issue,
    *,
    pr_number: int,
    pr_state: str,
    actor_login: str = "",
    occurred_at: datetime | None = None,
    commit: bool = False,
) -> None:
    if pr_state == "merged":
        event_type = "pr_merged"
        body = f"{EVENT_LABELS['pr_merged']} #{pr_number}"
    elif pr_state == "closed":
        event_type = "pr_closed"
        body = f"{EVENT_LABELS['pr_closed']} #{pr_number}"
    else:
        return
    when = occurred_at or datetime.now(timezone.utc)
    message_crud.upsert_event(
        db,
        issue_id=issue.id,
        event_type=event_type,
        event_key=f"{event_type}:{pr_number}",
        author_login=actor_login or "",
        body=body,
        occurred_at=when,
        commit=commit,
    )


def process_issue_comment_delivery(db: Session, payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Apply issue_comment webhook using local repo/issue rows only (no GitHub API)."""
    action = payload.get("action") or ""
    if action not in {"created", "edited", "deleted"}:
        return False, f"unsupported issue_comment action {action}"

    repo_meta = payload.get("repository") or {}
    github_repo_id = repo_meta.get("id")
    if not isinstance(github_repo_id, int) or isinstance(github_repo_id, bool):
        return False, "缺少仓库编号"

    repo = repository_crud.get_by_github_repo_id(db, github_repo_id)
    if repo is None:
        return False, "仓库未收录"

    issue_meta = payload.get("issue") or {}
    number = issue_meta.get("number")
    if not isinstance(number, int) or isinstance(number, bool):
        return False, "缺少 Issue 编号"
    if "pull_request" in issue_meta:
        return False, "忽略 PR 评论"

    issue = issue_crud.get_by_repo_number(db, repo.id, number)
    if issue is None or issue.deleted_at is not None:
        return False, "Issue 未收录"

    comment = payload.get("comment") or {}
    if action == "deleted":
        comment_id = comment.get("id")
        if not isinstance(comment_id, int) or isinstance(comment_id, bool):
            return False, "缺少评论编号"
        message_crud.soft_delete_comment(
            db, issue_id=issue.id, github_comment_id=comment_id, commit=False
        )
        # Ensure a row exists even if we never saw created (tombstone).
        if message_crud.get_by_comment_id(db, issue.id, comment_id) is None:
            user = comment.get("user") or {}
            occurred_at, updated_at = _comment_times(comment)
            message_crud.upsert_comment(
                db,
                issue_id=issue.id,
                github_comment_id=comment_id,
                author_login=(user.get("login") if isinstance(user, dict) else None) or "",
                body=comment.get("body") or "",
                occurred_at=occurred_at,
                github_updated_at=updated_at,
                deleted=True,
                commit=False,
            )
        db.flush()
        return True, None

    upsert_comment_payload(db, issue, comment, deleted=False, commit=False)
    db.flush()
    return True, None


def messages_for_detail(db: Session, issue_id: int) -> list[dict[str, Any]]:
    rows = message_crud.list_for_issue(db, issue_id)
    out: list[dict[str, Any]] = []
    for row in rows:
        html = None
        if row.source_kind == "comment" and row.deleted_at is None and row.body.strip():
            html = render_issue_body(row.body)
        out.append(
            {
                "row": row,
                "is_comment": row.source_kind == "comment",
                "is_deleted": row.deleted_at is not None,
                "body_html": html,
                "event_label": EVENT_LABELS.get(row.event_type or "", row.event_type or ""),
            }
        )
    return out
