from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.issue import Issue
from app.services.issues import classify_labels, kind_locked

# Display-only list filter value: not stored on issue.status, not part of the state machine.
UNFINISHED_STATUS = "unfinished"


@dataclass(frozen=True)
class RepoOpenSummary:
    feature_unfinished: int
    support_open: int
    failed: int


def _status_condition(status: str):
    if status == UNFINISHED_STATUS:
        return Issue.status != "pr_opened"
    return Issue.status == status


def _filters(
    *,
    kind: str | None = None,
    status: str | None = None,
    github_state: str | None = None,
):
    conditions = [Issue.deleted_at.is_(None)]
    if kind:
        conditions.append(Issue.kind == kind)
    if status:
        conditions.append(_status_condition(status))
    if github_state:
        conditions.append(Issue.github_state == github_state)
    return and_(*conditions)


def get(db: Session, issue_id: int) -> Issue | None:
    return db.get(Issue, issue_id)


def get_by_repo_number(db: Session, repository_id: int, number: int) -> Issue | None:
    return db.scalar(
        select(Issue).where(Issue.repository_id == repository_id, Issue.number == number)
    )


def upsert_from_webhook(
    db: Session,
    *,
    repository_id: int,
    github_issue_id: int,
    number: int,
    title: str,
    body: str,
    html_url: str,
    author_login: str,
    github_state: str,
    label_names: list[str],
    github_updated_at: datetime | None,
    action: str,
) -> Issue:
    row = get_by_repo_number(db, repository_id, number)
    kind, status = classify_labels(label_names)

    if action == "deleted":
        if row is None:
            row = Issue(
                repository_id=repository_id,
                github_issue_id=github_issue_id,
                number=number,
                title=title,
                body=body or "",
                html_url=html_url,
                author_login=author_login,
                github_state=github_state,
                kind=kind,
                status=status,
                label_names=label_names,
                github_updated_at=github_updated_at,
                deleted_at=datetime.now(timezone.utc),
            )
            db.add(row)
        else:
            row.deleted_at = datetime.now(timezone.utc)
            row.title = title
            row.body = body or ""
            row.label_names = label_names
            row.github_updated_at = github_updated_at
        db.commit()
        db.refresh(row)
        return row

    if row is None:
        row = Issue(
            repository_id=repository_id,
            github_issue_id=github_issue_id,
            number=number,
            title=title,
            body=body or "",
            html_url=html_url,
            author_login=author_login,
            github_state=github_state,
            kind=kind,
            status=status,
            label_names=label_names,
            github_updated_at=github_updated_at,
            branch_name=f"issue/{number}",
        )
        db.add(row)
    else:
        row.github_issue_id = github_issue_id
        row.title = title
        row.body = body or ""
        row.html_url = html_url
        row.author_login = author_login
        row.github_state = github_state
        row.label_names = label_names
        row.github_updated_at = github_updated_at
        row.deleted_at = None
        if not kind_locked(row.status):
            # only remap kind/status while still early
            if row.status in {
                "pending_classify",
                "recorded",
                "support_open",
            }:
                row.kind = kind
                if row.status in {"pending_classify", "recorded", "support_open"}:
                    row.status = status
    db.commit()
    db.refresh(row)
    return row


def list_for_repo(
    db: Session,
    repository_id: int,
    *,
    kind: str | None = None,
    status: str | None = None,
    github_state: str | None = "open",
    offset: int = 0,
    limit: int = 50,
) -> list[Issue]:
    stmt = select(Issue).where(
        Issue.repository_id == repository_id,
        _filters(kind=kind, status=status, github_state=github_state),
    )
    stmt = stmt.order_by(Issue.number.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def count_for_repo(
    db: Session,
    repository_id: int,
    *,
    kind: str | None = None,
    status: str | None = None,
    github_state: str | None = "open",
) -> int:
    stmt = (
        select(func.count())
        .select_from(Issue)
        .where(
            Issue.repository_id == repository_id,
            _filters(kind=kind, status=status, github_state=github_state),
        )
    )
    return int(db.scalar(stmt) or 0)


def repo_open_summary(db: Session, repository_id: int) -> RepoOpenSummary:
    """Counts for the repo card; same predicates as the Issue list filters."""
    row = db.execute(
        select(
            func.count()
            .filter(_filters(kind="feature", status=UNFINISHED_STATUS, github_state="open"))
            .label("feature_unfinished"),
            func.count()
            .filter(_filters(kind="support", status="support_open", github_state="open"))
            .label("support_open"),
            func.count()
            .filter(_filters(status="failed", github_state="open"))
            .label("failed"),
        )
        .select_from(Issue)
        .where(Issue.repository_id == repository_id)
    ).one()
    return RepoOpenSummary(
        feature_unfinished=int(row.feature_unfinished or 0),
        support_open=int(row.support_open or 0),
        failed=int(row.failed or 0),
    )


def set_kind(db: Session, issue: Issue, kind: str, status: str) -> Issue:
    issue.kind = kind
    issue.status = status
    db.commit()
    db.refresh(issue)
    return issue
