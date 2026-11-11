from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy.orm import Session

from app.crud import webhook_delivery as delivery_crud
from app.services.github_api import GitHubAPIError, GitHubClient
from app.services.ingest import process_delivery_payload


def _backoff_seconds(attempts: int, retry_after: int | None = None) -> int:
    if retry_after is not None:
        return max(retry_after, 1)
    return min(2 ** max(attempts, 1), 3600)


def process_one_delivery(db: Session, client: GitHubClient | None = None) -> bool:
    row = delivery_crud.claim_next(db)
    if row is None:
        return False
    owns = client is None
    client = client or GitHubClient()
    try:
        if row.event == "ping":
            delivery_crud.mark_succeeded(db, row)
            return True
        if row.event != "issues":
            delivery_crud.mark_ignored(db, row, error=f"unsupported event {row.event}")
            return True
        process_delivery_payload(db, client, row.payload)
        delivery_crud.mark_succeeded(db, row)
        return True
    except GitHubAPIError as exc:
        if exc.status_code in (401, 403):
            delivery_crud.mark_failed(db, row, error=str(exc))
        elif exc.status_code == 404:
            delivery_crud.mark_ignored(db, row, error=str(exc))
        elif exc.status_code in (429,) or (exc.status_code is not None and exc.status_code >= 500):
            delay = _backoff_seconds(row.attempts, exc.retry_after)
            delivery_crud.mark_retry(
                db,
                row,
                error=str(exc),
                next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
            )
        else:
            delay = _backoff_seconds(row.attempts)
            delivery_crud.mark_retry(
                db,
                row,
                error=str(exc),
                next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
            )
        logger.warning(f"delivery {row.delivery_id} error: {exc}")
        return True
    except Exception as exc:  # network etc.
        delay = _backoff_seconds(row.attempts)
        delivery_crud.mark_retry(
            db,
            row,
            error=str(exc),
            next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
        )
        logger.warning(f"delivery {row.delivery_id} unexpected: {exc}")
        return True
    finally:
        if owns:
            client.close()
