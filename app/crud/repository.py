from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.issue import Issue
from app.models.repository import Repository


def get(db: Session, repo_id: int) -> Repository | None:
    return db.get(Repository, repo_id)


def get_by_github_repo_id(db: Session, github_repo_id: int) -> Repository | None:
    return db.scalar(select(Repository).where(Repository.github_repo_id == github_repo_id))


def upsert_from_github(
    db: Session,
    *,
    company_id: int,
    github_repo_id: int,
    name: str,
    github_full_name: str,
    description: str | None,
    html_url: str | None,
    default_branch: str,
    private: bool,
    language: str | None = None,
    stargazers_count: int | None = None,
    forks_count: int | None = None,
    open_issues_count: int | None = None,
    topics: list[str] | None = None,
    license_spdx: str | None = None,
    license_name: str | None = None,
    archived: bool = False,
    disabled: bool = False,
    pushed_at: datetime | None = None,
    homepage: str | None = None,
    visibility: str | None = None,
) -> Repository:
    row = get_by_github_repo_id(db, github_repo_id)
    now = datetime.now(timezone.utc)
    if row is None:
        row = Repository(company_id=company_id, github_repo_id=github_repo_id)
        db.add(row)
    row.company_id = company_id
    row.name = name
    row.github_full_name = github_full_name
    row.description = description
    row.html_url = html_url
    row.default_branch = default_branch or "main"
    row.private = private
    row.synced_at = now
    row.sync_error = None
    row.language = language
    row.stargazers_count = stargazers_count
    row.forks_count = forks_count
    row.open_issues_count = open_issues_count
    row.topics = topics
    row.license_spdx = license_spdx
    row.license_name = license_name
    row.archived = archived
    row.disabled = disabled
    row.pushed_at = pushed_at
    row.homepage = homepage
    row.visibility = visibility
    db.commit()
    db.refresh(row)
    return row


def list_by_company(db: Session, company_id: int, *, offset: int = 0, limit: int = 50) -> list[Repository]:
    stmt = (
        select(Repository)
        .where(Repository.company_id == company_id)
        .order_by(Repository.github_full_name.asc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(stmt))


def open_issue_count(db: Session, repository_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Issue)
            .where(
                Issue.repository_id == repository_id,
                Issue.github_state == "open",
                Issue.deleted_at.is_(None),
            )
        )
        or 0
    )


def full_names_by_github_ids(db: Session, github_ids: Iterable[int]) -> dict[int, str]:
    """Read-only projection for pages that only have GitHub repository ids."""
    ids = sorted({int(value) for value in github_ids if value is not None})
    if not ids:
        return {}
    rows = db.execute(
        select(Repository.github_repo_id, Repository.github_full_name).where(
            Repository.github_repo_id.in_(ids)
        )
    )
    return {int(github_id): full_name for github_id, full_name in rows}


def set_sync_error(db: Session, row: Repository, error: str) -> None:
    row.sync_error = error
    db.commit()
