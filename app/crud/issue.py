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
        # A feature is unfinished until its PR reaches a terminal state. The
        # synthetic legacy row with status=pr_opened and no PR number keeps the
        # old "already opened" meaning.
        return and_(
            Issue.kind == "feature",
            Issue.pr_state.notin_(["merged", "closed"]),
            ~and_(Issue.status == "pr_opened", Issue.pr_number.is_(None)),
        )
    return Issue.status == status


def _filters(
    *,
    kind: str | None = None,
    status: str | None = None,
    github_state: str | None = None,
    pr_state: str | None = None,
):
    conditions = [Issue.deleted_at.is_(None)]
    if kind:
        conditions.append(Issue.kind == kind)
    if status:
        conditions.append(_status_condition(status))
    if github_state:
        conditions.append(Issue.github_state == github_state)
    if pr_state and pr_state != "all":
        conditions.append(Issue.pr_state == pr_state)
    return and_(*conditions)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _event_wins(current: datetime | None, incoming: datetime | None) -> bool:
    if incoming is None:
        return True
    if current is None:
        return True
    return incoming >= _aware(current)


def get(db: Session, issue_id: int) -> Issue | None:
    return db.get(Issue, issue_id)


def get_by_repo_number(db: Session, repository_id: int, number: int) -> Issue | None:
    return db.scalar(
        select(Issue).where(Issue.repository_id == repository_id, Issue.number == number)
    )


def list_by_pr_number(db: Session, repository_id: int, pr_number: int) -> list[Issue]:
    stmt = select(Issue).where(
        Issue.repository_id == repository_id,
        Issue.pr_number == pr_number,
    )
    return list(db.scalars(stmt))


CONTENT_ACTIONS = {"opened", "edited", "labeled", "unlabeled", "typed", "untyped"}
STATE_ACTIONS = {
    "opened",
    "edited",
    "labeled",
    "unlabeled",
    "typed",
    "untyped",
    "closed",
    "reopened",
}
EARLY_STATUSES = {"pending_classify", "recorded", "support_open"}


def _finish(db: Session, row: Issue, *, commit: bool, created: bool) -> tuple[Issue, bool]:
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row, created


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
    github_issue_type: str | None = None,
    github_issue_type_set: bool = False,
    commit: bool = True,
) -> tuple[Issue, bool]:
    """Insert or update an Issue. Second return value is True when a new row was added."""
    row = get_by_repo_number(db, repository_id, number)
    kind, status = classify_labels(label_names)
    event_time = _aware(github_updated_at)

    if action == "deleted":
        created = False
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
                github_issue_type=github_issue_type,
                github_state_updated_at=event_time,
                deleted_at=event_time or datetime.now(timezone.utc),
            )
            db.add(row)
            created = True
        elif row.deleted_at is None and _event_wins(row.github_state_updated_at, event_time):
            # deleted_at is terminal: later events must not reveal the row again.
            row.deleted_at = event_time or datetime.now(timezone.utc)
            if event_time is not None:
                row.github_state_updated_at = event_time
        return _finish(db, row, commit=commit, created=created)

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
            github_issue_type=github_issue_type,
            github_updated_at=event_time,
            github_state_updated_at=event_time,
            branch_name=f"issue/{number}",
        )
        db.add(row)
        return _finish(db, row, commit=commit, created=True)
    if row.deleted_at is not None:
        # Soft-deleted rows are terminal; ignore late Issue events.
        return _finish(db, row, commit=commit, created=False)

    if action in CONTENT_ACTIONS and _event_wins(row.github_updated_at, event_time):
        row.github_issue_id = github_issue_id
        row.title = title
        row.body = body or ""
        row.html_url = html_url
        row.author_login = author_login
        row.label_names = label_names
        if github_issue_type_set:
            row.github_issue_type = github_issue_type
        if event_time is not None:
            row.github_updated_at = event_time
        if not kind_locked(row.status) and row.status in EARLY_STATUSES:
            # only remap kind/status while still early
            row.kind = kind
            row.status = status

    if action in STATE_ACTIONS and _event_wins(row.github_state_updated_at, event_time):
        if action == "closed":
            target_state = "closed"
        elif action == "reopened":
            target_state = "open"
        else:
            target_state = github_state
        row.github_state = target_state
        if event_time is not None:
            row.github_state_updated_at = event_time

    return _finish(db, row, commit=commit, created=False)


def list_all_for_repo(db: Session, repository_id: int) -> list[Issue]:
    """All local rows for a repo, including soft-deleted ones, by number."""
    stmt = (
        select(Issue)
        .where(Issue.repository_id == repository_id)
        .order_by(Issue.number.asc())
    )
    return list(db.scalars(stmt))


def list_for_repo(
    db: Session,
    repository_id: int,
    *,
    kind: str | None = None,
    status: str | None = None,
    github_state: str | None = "open",
    pr_state: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[Issue]:
    stmt = select(Issue).where(
        Issue.repository_id == repository_id,
        _filters(
            kind=kind,
            status=status,
            github_state=github_state,
            pr_state=pr_state,
        ),
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
    pr_state: str | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(Issue)
        .where(
            Issue.repository_id == repository_id,
            _filters(
                kind=kind,
                status=status,
                github_state=github_state,
                pr_state=pr_state,
            ),
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
