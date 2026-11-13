from __future__ import annotations

import html as html_lib
import re
from datetime import datetime, timezone
from email.utils import parseaddr

from loguru import logger
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models.issue import Issue
from app.models.repository import Repository
from app.services.app_config import is_valid_address, read_mail_config
from app.services.mail import MailError, get_smtp_password, send_mail

_SPLIT_RE = re.compile(r"[\s,;]+")


def parse_notify_emails(raw: str) -> tuple[list[str], str | None]:
    """Split comma/newline/semicolon separated emails. Return (emails, error)."""
    if raw is None:
        return [], None
    text = str(raw).strip()
    if not text:
        return [], None
    emails: list[str] = []
    seen: set[str] = set()
    for part in _SPLIT_RE.split(text):
        part = part.strip()
        if not part:
            continue
        if not is_valid_address(part):
            return [], f"非法邮箱：{part}"
        _name, address = parseaddr(part)
        address = address.strip()
        key = address.lower()
        if key in seen:
            continue
        seen.add(key)
        emails.append(address)
    return emails, None


def format_notify_emails(emails: list[str] | None) -> str:
    if not emails:
        return ""
    return "\n".join(emails)


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def build_new_issue_mail(repo: Repository, issue: Issue) -> tuple[str, str]:
    title = _truncate(issue.title or "(无标题)", 80)
    subject = f"[{repo.github_full_name}] 新 Issue #{issue.number}：{title}"
    safe_repo = html_lib.escape(repo.github_full_name or "")
    safe_title = html_lib.escape(issue.title or "(无标题)")
    safe_author = html_lib.escape(issue.author_login or "")
    safe_url = html_lib.escape(issue.html_url or "")
    parts = [
        f"<p>仓库 <strong>{safe_repo}</strong> 有新的 Issue 需要处理。</p>",
        f"<p><strong>#{issue.number}</strong> {safe_title}</p>",
        f"<p>作者：{safe_author or '—'}</p>",
    ]
    if issue.html_url:
        parts.append(f'<p><a href="{safe_url}">在 GitHub 打开</a></p>')
    base = get_settings().app_public_base_url
    if base:
        app_url = html_lib.escape(f"{base}/issues/{issue.id}")
        parts.append(f'<p><a href="{app_url}">在本系统打开</a></p>')
    return subject, "\n".join(parts)


def maybe_notify_new_issue(
    db: Session,
    repo: Repository,
    issue: Issue,
    *,
    created: bool,
    commit: bool = True,
) -> bool:
    """Send one notify mail for a newly inserted Issue. Never raises.

    Returns True when a mail was sent successfully. When ``commit`` is False
    (bulk sync), only flush the timestamp and let the caller commit.
    """
    if not created:
        return False
    if issue.deleted_at is not None:
        return False
    if issue.notify_email_sent_at is not None:
        return False
    recipients = list(repo.notify_emails or [])
    if not recipients:
        return False
    mail = read_mail_config()
    if not mail.enabled or not get_smtp_password():
        logger.info(
            "skip issue notify mail: mail disabled or password missing repo={} issue={}",
            repo.id,
            issue.id,
        )
        return False

    subject, html_body = build_new_issue_mail(repo, issue)
    try:
        send_mail(recipients, subject, html_body)
    except MailError as exc:
        logger.warning(
            "issue notify mail failed repo={} issue={} code={} msg={}",
            repo.id,
            issue.id,
            exc.code,
            exc.message,
        )
        return False
    except Exception as exc:  # noqa: BLE001 - never break ingest/sync
        logger.warning(
            "issue notify mail unexpected error repo={} issue={} err={}",
            repo.id,
            issue.id,
            type(exc).__name__,
        )
        return False

    issue.notify_email_sent_at = datetime.now(timezone.utc)
    try:
        if commit:
            db.commit()
            db.refresh(issue)
        else:
            db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "issue notify mail sent but failed to persist timestamp issue={} err={}",
            issue.id,
            type(exc).__name__,
        )
        if commit:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        return True
    logger.info(
        "issue notify mail sent repo={} issue={} recipients={}",
        repo.id,
        issue.id,
        len(recipients),
    )
    return True
