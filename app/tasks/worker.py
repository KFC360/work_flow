from __future__ import annotations

import signal
import time
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from app.core.logging import setup_logging
from app.crud import job as job_crud
from app.database.connect import SessionLocal
from app.models.issue import Issue
from app.models.job import Job
from app.models.webhook_delivery import WebhookDelivery
from app.services.worker_heartbeat import IDLE_HEARTBEAT_INTERVAL_SEC, write_heartbeat
from app.tasks.inbox import process_one_delivery
from app.tasks.jobs import execute_job

_stop = False
_last_idle_heartbeat = 0.0


def _handle_signal(signum, frame) -> None:  # noqa: ARG001
    global _stop
    logger.info(f"received signal {signum}, stopping")
    _stop = True


def recover_on_startup() -> None:
    db = SessionLocal()
    try:
        running_jobs = list(db.scalars(select(Job).where(Job.status == "running")))
        now = datetime.now(timezone.utc)
        for job in running_jobs:
            job.status = "failed"
            job.finished_at = now
            job.error = "服务重启，任务已中断"
            issue = db.get(Issue, job.issue_id)
            if issue is not None:
                issue.status = "failed"
                issue.last_error = "服务重启，任务已中断"
                issue.failed_action = job.action
        deliveries = list(db.scalars(select(WebhookDelivery).where(WebhookDelivery.status == "running")))
        for d in deliveries:
            d.status = "retry"
            d.next_retry_at = now
            d.last_error = "服务重启，投递已中断"
        db.commit()
        logger.info(f"startup recovery: failed jobs={len(running_jobs)}, inbox retry={len(deliveries)}")
    finally:
        db.close()


def pipeline_once() -> bool:
    db = SessionLocal()
    try:
        # only one running at a time globally
        existing = db.scalar(select(Job.id).where(Job.status == "running"))
        if existing is not None:
            return False
        job = job_crud.claim_next_pipeline(db)
        if job is None:
            return False
        logger.info(f"pipeline running job={job.id} action={job.action}")
        execute_job(db, job)
        return True
    finally:
        db.close()


def main() -> None:
    setup_logging()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    recover_on_startup()
    logger.info("worker started (single process, inbox + pipeline)")
    global _last_idle_heartbeat
    write_heartbeat()
    _last_idle_heartbeat = time.monotonic()
    while not _stop:
        did_inbox = False
        did_pipe = False
        db = SessionLocal()
        try:
            did_inbox = process_one_delivery(db)
        finally:
            db.close()
        if not _stop:
            did_pipe = pipeline_once()
        now = time.monotonic()
        if not did_pipe and now - _last_idle_heartbeat >= IDLE_HEARTBEAT_INTERVAL_SEC:
            write_heartbeat()
            _last_idle_heartbeat = now
        if not did_inbox and not did_pipe:
            time.sleep(1.0)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
