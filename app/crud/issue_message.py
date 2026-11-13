from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.issue_message import SOURCE_COMMENT, SOURCE_EVENT, IssueMessage


def list_for_issue(db: Session, issue_id: int) -> list[IssueMessage]:
    stmt = (
        select(IssueMessage)
        .where(IssueMessage.issue_id == issue_id)
        .order_by(IssueMessage.occurred_at.asc(), IssueMessage.id.asc())
    )
    return list(db.scalars(stmt))


def get_by_comment_id(
    db: Session, issue_id: int, github_comment_id: int
) -> IssueMessage | None:
    stmt = select(IssueMessage).where(
        IssueMessage.issue_id == issue_id,
        IssueMessage.github_comment_id == github_comment_id,
    )
    return db.scalars(stmt).first()


def get_by_event_key(db: Session, issue_id: int, event_key: str) -> IssueMessage | None:
    stmt = select(IssueMessage).where(
        IssueMessage.issue_id == issue_id,
        IssueMessage.event_key == event_key,
    )
    return db.scalars(stmt).first()


def upsert_comment(
    db: Session,
    *,
    issue_id: int,
    github_comment_id: int,
    author_login: str,
    body: str,
    occurred_at: datetime,
    github_updated_at: datetime | None,
    deleted: bool = False,
    commit: bool = True,
) -> IssueMessage:
    row = get_by_comment_id(db, issue_id, github_comment_id)
    now = datetime.now(timezone.utc)
    if row is None:
        row = IssueMessage(
            issue_id=issue_id,
            source_kind=SOURCE_COMMENT,
            github_comment_id=github_comment_id,
            author_login=author_login or "",
            body=body or "",
            occurred_at=occurred_at,
            github_updated_at=github_updated_at,
            deleted_at=now if deleted else None,
        )
        db.add(row)
    else:
        row.author_login = author_login or ""
        row.body = body or ""
        row.occurred_at = occurred_at
        row.github_updated_at = github_updated_at
        if deleted:
            row.deleted_at = row.deleted_at or now
        else:
            row.deleted_at = None
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def soft_delete_comment(
    db: Session,
    *,
    issue_id: int,
    github_comment_id: int,
    commit: bool = True,
) -> IssueMessage | None:
    row = get_by_comment_id(db, issue_id, github_comment_id)
    if row is None:
        return None
    if row.deleted_at is None:
        row.deleted_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def upsert_event(
    db: Session,
    *,
    issue_id: int,
    event_type: str,
    event_key: str,
    author_login: str,
    body: str,
    occurred_at: datetime,
    commit: bool = True,
) -> IssueMessage:
    row = get_by_event_key(db, issue_id, event_key)
    if row is None:
        row = IssueMessage(
            issue_id=issue_id,
            source_kind=SOURCE_EVENT,
            event_type=event_type,
            event_key=event_key,
            author_login=author_login or "",
            body=body or "",
            occurred_at=occurred_at,
        )
        db.add(row)
    else:
        row.author_login = author_login or row.author_login
        row.body = body or row.body
        row.occurred_at = occurred_at
        row.event_type = event_type
        row.deleted_at = None
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row
