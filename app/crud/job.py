from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job import Job


def get(db: Session, job_id: int) -> Job | None:
    return db.get(Job, job_id)


def has_active_for_issue(db: Session, issue_id: int) -> bool:
    row = db.scalar(
        select(Job.id).where(
            Job.issue_id == issue_id,
            Job.status.in_(["queued", "running"]),
        )
    )
    return row is not None


def has_active_for_repo(db: Session, repository_id: int) -> bool:
    row = db.scalar(
        select(Job.id).where(
            Job.repository_id == repository_id,
            Job.status.in_(["queued", "running"]),
        )
    )
    return row is not None


def enqueue(
    db: Session,
    *,
    issue_id: int,
    repository_id: int,
    action: str,
) -> Job:
    job = Job(
        issue_id=issue_id,
        repository_id=repository_id,
        action=action,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def cancel_queued_for_issue(db: Session, issue_id: int) -> int:
    rows = list(
        db.scalars(
            select(Job).where(Job.issue_id == issue_id, Job.status == "queued")
        )
    )
    now = datetime.now(timezone.utc)
    for job in rows:
        job.status = "cancelled"
        job.finished_at = now
        job.error = "Issue closed"
    db.commit()
    return len(rows)


def claim_next_pipeline(db: Session) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.status == "queued")
        .order_by(Job.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = db.scalar(stmt)
    if job is None:
        return None
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


def latest_for_issue(db: Session, issue_id: int) -> Job | None:
    return db.scalar(
        select(Job).where(Job.issue_id == issue_id).order_by(Job.created_at.desc()).limit(1)
    )


def fail_running_on_startup(db: Session) -> int:
    rows = list(db.scalars(select(Job).where(Job.status == "running")))
    now = datetime.now(timezone.utc)
    for job in rows:
        job.status = "failed"
        job.finished_at = now
        job.error = "服务重启，任务已中断"
    db.commit()
    return len(rows)
