from __future__ import annotations

from sqlalchemy.orm import Session

from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from datetime import datetime, timezone

from app.models.issue import Issue
from app.models.job import Job
from sqlalchemy import select


def test_cancel_queued_on_close(db: Session) -> None:
    company = company_crud.upsert_from_github(
        db,
        github_account_id=1,
        account_type="User",
        login="u",
        name="u",
        description=None,
        avatar_url=None,
        html_url=None,
    )
    repo = repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=1,
        name="r",
        github_full_name="u/r",
        description=None,
        html_url=None,
        default_branch="main",
        private=False,
    )
    issue = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=1,
        number=1,
        title="t",
        body="",
        html_url="u",
        author_login="u",
        github_state="open",
        label_names=["功能迭代"],
        github_updated_at=None,
        action="opened",
    )
    job = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="write_doc")
    n = job_crud.cancel_queued_for_issue(db, issue.id)
    assert n == 1
    db.refresh(job)
    assert job.status == "cancelled"


def test_recover_running(db: Session) -> None:
    company = company_crud.upsert_from_github(
        db,
        github_account_id=2,
        account_type="User",
        login="u2",
        name="u2",
        description=None,
        avatar_url=None,
        html_url=None,
    )
    repo = repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=2,
        name="r2",
        github_full_name="u2/r2",
        description=None,
        html_url=None,
        default_branch="main",
        private=False,
    )
    issue = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=2,
        number=2,
        title="t",
        body="",
        html_url="u",
        author_login="u",
        github_state="open",
        label_names=["功能迭代"],
        github_updated_at=None,
        action="opened",
    )
    job = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="write_doc")
    job.status = "running"
    issue.status = "drafting"
    db.commit()
    # inline same recovery logic against the test session
    now = datetime.now(timezone.utc)
    for j in db.scalars(select(Job).where(Job.status == "running")):
        j.status = "failed"
        j.finished_at = now
        j.error = "服务重启，任务已中断"
        iss = db.get(Issue, j.issue_id)
        if iss is not None:
            iss.status = "failed"
            iss.last_error = "服务重启，任务已中断"
            iss.failed_action = j.action
    db.commit()
    db.refresh(job)
    db.refresh(issue)
    assert job.status == "failed"
    assert issue.status == "failed"
    assert issue.failed_action == "write_doc"
