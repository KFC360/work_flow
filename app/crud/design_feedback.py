from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.design_feedback import DesignFeedback

HUMAN_COMMENT = "human_comment"
REVISE_REQUEST = "revise_request"
PENDING_CONFIRM = "pending_confirm"
PENDING_REJECT = "pending_reject"
HUMAN_EDIT = "human_edit"
APPROVE = "approve"
UNAPPROVE = "unapprove"

ALL_KINDS = {
    HUMAN_COMMENT,
    REVISE_REQUEST,
    PENDING_CONFIRM,
    PENDING_REJECT,
    HUMAN_EDIT,
    APPROVE,
    UNAPPROVE,
}

HISTORY_KINDS = [HUMAN_COMMENT, REVISE_REQUEST, HUMAN_EDIT, APPROVE, UNAPPROVE]
UNRESOLVED_KINDS = [HUMAN_COMMENT, REVISE_REQUEST]
DECISION_KINDS = [PENDING_CONFIRM, PENDING_REJECT]


def create(
    db: Session,
    *,
    issue_id: int,
    author_user_id: int,
    author_username: str,
    kind: str,
    body: str = "",
    pending_item_key: str | None = None,
    pending_item_title: str | None = None,
    doc_sha256: str | None = None,
    job_id: int | None = None,
    commit: bool = True,
) -> DesignFeedback:
    row = DesignFeedback(
        issue_id=issue_id,
        author_user_id=author_user_id,
        author_username=author_username,
        kind=kind,
        body=body or "",
        pending_item_key=pending_item_key,
        pending_item_title=pending_item_title,
        doc_sha256=doc_sha256,
        job_id=job_id,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def list_history(
    db: Session, issue_id: int, *, limit: int = 100
) -> list[DesignFeedback]:
    """Recent human-facing actions; pending-item decisions live on the items."""
    stmt = (
        select(DesignFeedback)
        .where(
            DesignFeedback.issue_id == issue_id,
            DesignFeedback.kind.in_(HISTORY_KINDS),
        )
        .order_by(DesignFeedback.created_at.desc(), DesignFeedback.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def latest_decisions(
    db: Session, issue_id: int, doc_sha256: str
) -> dict[str, DesignFeedback]:
    """Latest confirm/reject decision per pending item for one doc version."""
    rows = list(
        db.scalars(
            select(DesignFeedback)
            .where(
                DesignFeedback.issue_id == issue_id,
                DesignFeedback.doc_sha256 == doc_sha256,
                DesignFeedback.kind.in_(DECISION_KINDS),
                DesignFeedback.pending_item_key.is_not(None),
            )
            .order_by(DesignFeedback.created_at.asc(), DesignFeedback.id.asc())
        )
    )
    latest: dict[str, DesignFeedback] = {}
    for row in rows:
        if row.pending_item_key:
            latest[row.pending_item_key] = row
    return latest


def unresolved_comments(db: Session, issue_id: int) -> list[DesignFeedback]:
    stmt = (
        select(DesignFeedback)
        .where(
            DesignFeedback.issue_id == issue_id,
            DesignFeedback.kind.in_(UNRESOLVED_KINDS),
            DesignFeedback.resolved_at.is_(None),
        )
        .order_by(DesignFeedback.created_at.asc(), DesignFeedback.id.asc())
    )
    return list(db.scalars(stmt))


def mark_resolved(
    db: Session,
    feedbacks: list[DesignFeedback],
    *,
    job_id: int,
    commit: bool = True,
) -> None:
    now = datetime.now(timezone.utc)
    for row in feedbacks:
        if row.resolved_at is None:
            row.resolved_at = now
        row.job_id = job_id
    if commit:
        db.commit()
    else:
        db.flush()
