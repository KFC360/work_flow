from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.models.issue import Issue
from app.models.repository import Repository
from app.services.github_api import GitHubAPIError
from app.services.ingest import issue_type_name, label_names_from_payload
from app.services.pr_sync import apply_pull_request_snapshot, parse_dt

# Per_page drives both the request and the "last page" stop condition.
PER_PAGE = 100
SYNC_TIMEOUT_SECONDS = 180


class IssueSyncError(Exception):
    """A user-facing sync failure that must be surfaced in the flash message."""


@dataclass
class IssueSyncResult:
    checked: int = 0
    open_count: int = 0
    closed_count: int = 0
    created: int = 0
    updated: int = 0
    soft_deleted: int = 0
    skipped_deleted: int = 0
    skipped_recent: int = 0
    pr_refreshed: int = 0
    failures: list[str] = field(default_factory=list)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _valid_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _deadline_exceeded(deadline: float | None) -> bool:
    return deadline is not None and monotonic() >= deadline


def _split_full_name(repo: Repository) -> tuple[str, str]:
    owner, _, name = (repo.github_full_name or "").partition("/")
    if not owner or not name or "/" in name:
        raise IssueSyncError("仓库完整名无效，请先重新同步仓库")
    return owner, name


def _read_remote_issues(
    client, repo: Repository, result: IssueSyncResult, deadline: float | None
) -> tuple[list[dict[str, Any]], set[int]]:
    owner, name = _split_full_name(repo)
    remote: list[dict[str, Any]] = []
    seen: set[int] = set()
    page = 1
    while True:
        if _deadline_exceeded(deadline):
            raise IssueSyncError("超过 180 秒未完成，已中止；未写入任何变更")
        data = client.list_repository_issues(
            owner,
            name,
            state="all",
            page=page,
            per_page=PER_PAGE,
            sort="created",
            direction="asc",
        )
        if not isinstance(data, list):
            raise IssueSyncError("GitHub 返回了无法识别的 Issue 列表，未写入任何变更")
        for item in data:
            if not isinstance(item, dict):
                result.failures.append(f"第 {page} 页存在无法解析的条目，已跳过")
                continue
            number = _valid_int(item.get("number"))
            if "pull_request" in item:
                # PRs share the issues endpoint; remember the number but never store it.
                if number is not None:
                    seen.add(number)
                continue
            issue_id = _valid_int(item.get("id"))
            if issue_id is None or number is None:
                result.failures.append(f"第 {page} 页存在缺少编号的条目，已跳过")
                continue
            seen.add(number)
            remote.append(item)
            result.checked += 1
            if item.get("state") == "closed":
                result.closed_count += 1
            elif item.get("state") == "open":
                result.open_count += 1
        if len(data) < PER_PAGE:
            break
        page += 1
    return remote, seen


def _write_remote_issue(
    db: Session,
    repo: Repository,
    item: dict[str, Any],
    local: Issue | None,
    result: IssueSyncResult,
) -> None:
    issue_id = _valid_int(item.get("id"))
    number = _valid_int(item.get("number"))
    if issue_id is None or number is None:
        result.failures.append("存在缺少编号的条目，已跳过")
        return
    if local is not None and local.github_issue_id != issue_id:
        result.failures.append(f"#{number} 的 GitHub ID 与本地不一致，等待人工处理")
        return
    if local is not None and local.deleted_at is not None:
        result.skipped_deleted += 1
        return

    user = item.get("user") or {}
    was_closed = local is not None and local.github_state == "closed"
    row = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=issue_id,
        number=number,
        title=item.get("title") or "",
        body=item.get("body") or "",
        html_url=item.get("html_url") or "",
        author_login=user.get("login") or "",
        github_state=item.get("state") or "open",
        label_names=label_names_from_payload(item.get("labels")),
        github_updated_at=parse_dt(item.get("updated_at")),
        action="opened" if local is None else "edited",
        github_issue_type=issue_type_name(item.get("type")),
        github_issue_type_set=("type" in item),
        commit=False,
    )
    if local is None:
        result.created += 1
    else:
        result.updated += 1
    if not was_closed and row.github_state == "closed" and row.deleted_at is None:
        job_crud.cancel_queued_for_issue(db, row.id, commit=False)


def _soft_delete_missing(
    db: Session,
    local_rows: list[Issue],
    seen: set[int],
    started_at: datetime,
    result: IssueSyncResult,
) -> None:
    for row in local_rows:
        if row.number in seen or row.deleted_at is not None:
            continue
        if row.github_updated_at is not None:
            updated = _aware(row.github_updated_at)
            if updated is not None and updated > started_at:
                # A Webhook may have touched this row while we were reading.
                result.skipped_recent += 1
                continue
        row.deleted_at = started_at
        result.soft_deleted += 1
    db.flush()


def _refresh_pull_requests(
    client,
    repo: Repository,
    local_rows: list[Issue],
    result: IssueSyncResult,
    deadline: float | None,
) -> None:
    owner, name = _split_full_name(repo)
    by_pr: dict[int, list[Issue]] = {}
    for row in local_rows:
        if row.deleted_at is not None or row.pr_number is None:
            continue
        by_pr.setdefault(row.pr_number, []).append(row)

    for pr_number, rows in by_pr.items():
        if _deadline_exceeded(deadline):
            result.failures.append("PR 刷新超时中止")
            break
        try:
            pr = client.get_pull_request(owner, name, pr_number)
        except GitHubAPIError as exc:
            if exc.status_code in (401, 403):
                result.failures.append("PR 刷新因授权失败中止")
                break
            if exc.status_code == 429:
                result.failures.append("PR 刷新因限流中止")
                break
            if exc.status_code in (404, 410):
                result.failures.append(f"PR #{pr_number} 已不存在")
                continue
            result.failures.append(f"PR #{pr_number} 刷新失败")
            continue
        except httpx.HTTPError:
            result.failures.append(f"PR #{pr_number} 刷新失败")
            continue
        if not isinstance(pr, dict) or _valid_int(pr.get("number")) != pr_number:
            result.failures.append(f"PR #{pr_number} 的返回编号不一致")
            continue
        applied = False
        for row in rows:
            applied = apply_pull_request_snapshot(row, pr) or applied
        if applied:
            result.pr_refreshed += len(rows)


def sync_repository_issues(
    db: Session,
    client,
    repo: Repository,
    *,
    deadline: float | None = None,
) -> IssueSyncResult:
    """Reconcile all GitHub Issues for one repository.

    Reads every page before touching local rows. Any read failure propagates and
    leaves business data untouched. Writes are committed exactly once.
    """
    result = IssueSyncResult()
    started_at = datetime.now(timezone.utc)
    remote, seen = _read_remote_issues(client, repo, result, deadline)

    local_rows = issue_crud.list_all_for_repo(db, repo.id)
    by_number = {row.number: row for row in local_rows}
    for item in remote:
        number = _valid_int(item.get("number"))
        if number is None:
            continue
        _write_remote_issue(db, repo, item, by_number.get(number), result)

    _soft_delete_missing(db, local_rows, seen, started_at, result)
    _refresh_pull_requests(client, repo, local_rows, result, deadline)

    db.commit()
    return result


def summary_text(result: IssueSyncResult) -> str:
    counts = (
        f"检查 {result.checked} 条（open {result.open_count} / closed "
        f"{result.closed_count}），新增 {result.created} 条，更新 {result.updated} 条，"
        f"软删 {result.soft_deleted} 条，PR 刷新 {result.pr_refreshed} 条。"
    )
    if result.skipped_recent:
        counts += f"跳过同步期间更新 {result.skipped_recent} 条。"
    if result.skipped_deleted:
        counts += f"跳过已软删 {result.skipped_deleted} 条。"
    if result.failures:
        details = "；".join(result.failures[:5])
        if len(result.failures) > 5:
            details += f"；另有 {len(result.failures) - 5} 项"
        return f"同步完成，但有 {len(result.failures)} 项失败：{details}。{counts}"
    return f"同步完成：{counts}"
