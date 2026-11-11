from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.webhook_delivery import WebhookDelivery


def get(db: Session, delivery_id: str) -> WebhookDelivery | None:
    return db.get(WebhookDelivery, delivery_id)


def create_queued(
    db: Session,
    *,
    delivery_id: str,
    event: str,
    action: str | None,
    repository_id: int | None,
    payload: dict,
) -> WebhookDelivery | None:
    existing = get(db, delivery_id)
    if existing is not None:
        return None
    row = WebhookDelivery(
        delivery_id=delivery_id,
        event=event,
        action=action,
        repository_id=repository_id,
        payload=payload,
        status="queued",
        attempts=0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_deliveries(
    db: Session,
    *,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[WebhookDelivery]:
    stmt = select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc())
    if status:
        stmt = stmt.where(WebhookDelivery.status == status)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.scalars(stmt))


def count_deliveries(db: Session, *, status: str | None = None) -> int:
    from sqlalchemy import func

    stmt = select(func.count()).select_from(WebhookDelivery)
    if status:
        stmt = stmt.where(WebhookDelivery.status == status)
    return int(db.scalar(stmt) or 0)


def mark_retry(
    db: Session,
    row: WebhookDelivery,
    *,
    error: str,
    next_retry_at: datetime,
) -> None:
    row.status = "retry"
    row.last_error = error
    row.next_retry_at = next_retry_at
    row.finished_at = None
    db.commit()


def mark_failed(db: Session, row: WebhookDelivery, *, error: str) -> None:
    row.status = "failed"
    row.last_error = error
    row.finished_at = datetime.now(timezone.utc)
    row.next_retry_at = None
    db.commit()


def mark_ignored(db: Session, row: WebhookDelivery, *, error: str | None = None) -> None:
    row.status = "ignored"
    row.last_error = error
    row.finished_at = datetime.now(timezone.utc)
    row.next_retry_at = None
    db.commit()


def mark_succeeded(db: Session, row: WebhookDelivery) -> None:
    row.status = "succeeded"
    row.last_error = None
    row.finished_at = datetime.now(timezone.utc)
    row.next_retry_at = None
    db.commit()


def requeue_failed(db: Session, delivery_id: str) -> WebhookDelivery | None:
    row = get(db, delivery_id)
    if row is None or row.status != "failed":
        return None
    row.status = "queued"
    row.next_retry_at = None
    row.last_error = None
    row.finished_at = None
    db.commit()
    db.refresh(row)
    return row


def claim_next(db: Session) -> WebhookDelivery | None:
    now = datetime.now(timezone.utc)
    stmt = (
        select(WebhookDelivery)
        .where(
            (WebhookDelivery.status == "queued")
            | (
                (WebhookDelivery.status == "retry")
                & (WebhookDelivery.next_retry_at.is_not(None))
                & (WebhookDelivery.next_retry_at <= now)
            )
        )
        .order_by(WebhookDelivery.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    row = db.scalar(stmt)
    if row is None:
        return None
    row.status = "running"
    row.started_at = now
    row.attempts = (row.attempts or 0) + 1
    db.commit()
    db.refresh(row)
    return row
