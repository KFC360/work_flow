from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.issue import Issue
from app.models.repository import Repository


def get_by_github_account_id(db: Session, github_account_id: int) -> Company | None:
    return db.scalar(select(Company).where(Company.github_account_id == github_account_id))


def get(db: Session, company_id: int) -> Company | None:
    return db.get(Company, company_id)


def upsert_from_github(
    db: Session,
    *,
    github_account_id: int,
    account_type: str,
    login: str,
    name: str,
    description: str | None,
    avatar_url: str | None,
    html_url: str | None,
) -> Company:
    row = get_by_github_account_id(db, github_account_id)
    now = datetime.now(timezone.utc)
    if row is None:
        row = Company(
            github_account_id=github_account_id,
            account_type=account_type,
            login=login,
            name=name or login,
            description=description,
            avatar_url=avatar_url,
            html_url=html_url,
            synced_at=now,
            sync_error=None,
        )
        db.add(row)
    else:
        row.account_type = account_type
        row.login = login
        row.name = name or login
        row.description = description
        row.avatar_url = avatar_url
        row.html_url = html_url
        row.synced_at = now
        row.sync_error = None
    db.commit()
    db.refresh(row)
    return row


def list_companies(db: Session, *, offset: int = 0, limit: int = 50) -> list[Company]:
    stmt = select(Company).order_by(Company.name.asc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def count_companies(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Company)) or 0)


def repo_count(db: Session, company_id: int) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(Repository).where(Repository.company_id == company_id)
        )
        or 0
    )


def open_issue_count(db: Session, company_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(Issue)
        .join(Repository, Repository.id == Issue.repository_id)
        .where(
            Repository.company_id == company_id,
            Issue.github_state == "open",
            Issue.deleted_at.is_(None),
            Issue.status.notin_(["pr_opened"]),
        )
    )
    return int(db.scalar(stmt) or 0)
