from __future__ import annotations

import html as html_lib
import os
import re
import smtplib
import ssl
from collections.abc import Iterable
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import nh3
from loguru import logger

from app.services.app_config import (
    ALLOWED_SECURITY,
    has_header_break,
    is_valid_address,
    read_mail_config,
)

SMTP_TIMEOUT_SECONDS = 10

ALLOWED_TAGS = {
    "p",
    "br",
    "a",
    "strong",
    "b",
    "em",
    "i",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "hr",
    "blockquote",
}

ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}
LINK_REL = "noopener noreferrer"

CLEAN_CONTENT_TAGS = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "svg",
    "math",
    "form",
}

_BLOCK_TAG_RE = re.compile(
    r"(?i)</?(?:p|div|h[1-6]|li|ul|ol|blockquote|hr|br)\b[^>]*>"
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")


class MailError(Exception):
    """Mail configuration or send failure. The message is safe to display."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MailConfigError(MailError):
    pass


class MailSendError(MailError):
    pass


def get_smtp_password() -> str:
    return os.getenv("SMTP_PASSWORD", "").strip()


def password_configured() -> bool:
    return bool(get_smtp_password())


def sanitize_html(html_body: str) -> str:
    return nh3.clean(
        html_body,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        url_relative="deny",
        link_rel=LINK_REL,
        clean_content_tags=CLEAN_CONTENT_TAGS,
    )


def html_to_text(html_body: str) -> str:
    text = _BLOCK_TAG_RE.sub("\n", html_body)
    text = _TAG_RE.sub("", text)
    text = html_lib.unescape(text)
    text = _SPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _normalize_recipients(to: str | Iterable[str]) -> list[str]:
    chunks: list[str] = []
    if isinstance(to, str):
        chunks.append(to)
    else:
        for item in to:
            if not isinstance(item, str):
                raise MailConfigError("invalid_recipient", "地址或邮件头非法")
            chunks.append(item)

    recipients: list[str] = []
    for chunk in chunks:
        if has_header_break(chunk):
            raise MailConfigError("invalid_recipient", "地址或邮件头非法")
        for part in chunk.split(","):
            part = part.strip()
            if not part:
                continue
            _name, address = parseaddr(part)
            if not address or "@" not in address or has_header_break(address):
                raise MailConfigError("invalid_recipient", "地址或邮件头非法")
            recipients.append(address)
    if not recipients:
        raise MailConfigError("missing_recipient", "缺少收件人")
    return recipients


def _build_message(
    *,
    recipients: list[str],
    subject: str,
    html_body: str,
    text_fallback: str | None,
    from_address: str,
    from_name: str,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((from_name, from_address))
    message["To"] = ", ".join(recipients)
    text = text_fallback.strip() if text_fallback and text_fallback.strip() else ""
    if not text:
        text = html_to_text(html_body)
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")
    return message


def send_mail(
    to: str | Iterable[str],
    subject: str,
    html_body: str,
    *,
    text_fallback: str | None = None,
) -> None:
    """Send one mail using config.yaml and the SMTP_PASSWORD environment variable."""
    config = read_mail_config()
    if not config.enabled:
        raise MailConfigError("disabled", "邮件发件未启用")
    if not config.smtp_host:
        raise MailConfigError("missing_host", "未配置 SMTP 主机")
    if config.smtp_port == 0:
        raise MailConfigError("missing_port", "未配置或非法的 SMTP 端口")
    if not (1 <= config.smtp_port <= 65535):
        raise MailConfigError("invalid_port", "未配置或非法的 SMTP 端口")
    if config.security not in ALLOWED_SECURITY:
        raise MailConfigError("invalid_security", "加密方式无效")
    if not config.from_address:
        raise MailConfigError("missing_from", "发件人地址缺失或无效")
    if not is_valid_address(config.from_address):
        raise MailConfigError("invalid_from", "发件人地址缺失或无效")

    password = get_smtp_password()
    if not password:
        raise MailConfigError("missing_password", "未配置环境变量 SMTP_PASSWORD")

    recipients = _normalize_recipients(to)

    subject = (subject or "").strip()
    if not subject or not (html_body or "").strip():
        raise MailConfigError("empty_message", "邮件主题或正文为空")
    if has_header_break(subject) or has_header_break(config.from_name):
        raise MailConfigError("invalid_header", "地址或邮件头非法")

    try:
        cleaned_html = sanitize_html(html_body)
    except Exception as exc:  # noqa: BLE001 - never send unsanitized HTML
        logger.warning(f"mail html sanitize failed: {type(exc).__name__}")
        raise MailSendError("sanitize_error", "邮件内容消毒失败") from exc

    message = _build_message(
        recipients=recipients,
        subject=subject,
        html_body=cleaned_html,
        text_fallback=text_fallback,
        from_address=config.from_address,
        from_name=config.from_name,
    )

    try:
        context = ssl.create_default_context()
        if config.security == "ssl":
            client = smtplib.SMTP_SSL(
                config.smtp_host,
                config.smtp_port,
                timeout=SMTP_TIMEOUT_SECONDS,
                context=context,
            )
        else:
            client = smtplib.SMTP(
                config.smtp_host,
                config.smtp_port,
                timeout=SMTP_TIMEOUT_SECONDS,
            )
        with client as smtp:
            if config.security == "starttls":
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            if config.username:
                smtp.login(config.username, password)
            smtp.send_message(
                message,
                from_addr=config.from_address,
                to_addrs=recipients,
            )
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "mail send failed: {} code={}",
            type(exc).__name__,
            getattr(exc, "smtp_code", "-"),
        )
        raise MailSendError(
            "smtp_error", f"发送失败：{type(exc).__name__}（详见日志）"
        ) from exc

    logger.info("mail sent to {} recipient(s)", len(recipients))
