from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger
from sqlalchemy.orm import Session

from app.core.security import csrf_token_for_jti
from app.core.templating import build_templates
from app.database.connect import get_db
from app.dependencies.auth import require_csrf, require_page_user
from app.models.user import User
from app.services.app_config import (
    ALLOWED_AGENTS,
    MailConfig,
    read_app_config,
    read_mail_config,
    validate_mail_config,
    write_app_config,
)
from app.services.mail import MailError, password_configured, send_mail
from app.services.worker_heartbeat import HEARTBEAT_PATH, read_heartbeat

router = APIRouter(tags=["settings"])
templates = build_templates()


def _redirect(flash: str, msg: str) -> RedirectResponse:
    return RedirectResponse(
        f"/settings?flash={flash}&msg={quote(msg)}",
        status_code=303,
    )


def _mail_form(config: MailConfig) -> dict[str, object]:
    return {
        "enabled": config.enabled,
        "smtp_host": config.smtp_host,
        "smtp_port": str(config.smtp_port or 587),
        "security": config.security or "starttls",
        "username": config.username,
        "from_address": config.from_address,
        "from_name": config.from_name,
        "default_to": config.default_to,
    }


def _parse_port(raw: str) -> tuple[int, str | None]:
    text = (raw or "").strip()
    if not text:
        return 0, None
    if not text.isdigit():
        return 0, "SMTP 端口须为 1–65535 的整数"
    port = int(text)
    if not (1 <= port <= 65535):
        return port, "SMTP 端口须为 1–65535 的整数"
    return port, None


def _mail_from_form(
    *,
    enabled: bool,
    smtp_host: str,
    smtp_port: int,
    security: str,
    username: str,
    from_address: str,
    from_name: str,
    default_to: str,
) -> MailConfig:
    return MailConfig(
        enabled=enabled,
        smtp_host=smtp_host.strip(),
        smtp_port=smtp_port,
        security=security.strip().lower(),
        username=username.strip(),
        from_address=from_address.strip(),
        from_name=from_name.strip(),
        default_to=default_to.strip(),
    )


def _mail_config_errors(config: MailConfig) -> list[str]:
    if not config.enabled:
        return []
    return list(validate_mail_config(config).values())


def _mail_warnings(config: MailConfig) -> list[str]:
    warnings: list[str] = []
    if config.enabled and not password_configured():
        warnings.append("SMTP 密码未配置，保存后仍无法发信。")
    if config.security == "none":
        warnings.append("不加密连接会明文传输邮件内容与认证信息。")
    return warnings


def _render_settings(
    request: Request,
    user: User,
    *,
    agent_value: str,
    mail_form: dict[str, object],
    field_errors: dict[str, str] | None = None,
    mail_config_errors: list[str] | None = None,
    mail_warnings: list[str] | None = None,
    status_code: int = 200,
):
    jti = getattr(user, "_token_jti", "")
    heartbeat = read_heartbeat()
    config_warning = read_app_config().warning
    saved_mail = read_mail_config()
    errors = field_errors or {}
    first_error = next(iter(errors), "")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "csrf_token": csrf_token_for_jti(jti) if jti else "",
            "agent": agent_value,
            "mail_form": mail_form,
            "field_errors": errors,
            "first_error": first_error,
            "config_warning": config_warning,
            "mail_config_errors": mail_config_errors or [],
            "mail_warnings": mail_warnings or [],
            "smtp_password_configured": password_configured(),
            "saved_default_to": saved_mail.default_to,
            "nav": "settings",
            "breadcrumbs": [("设置", None)],
            "flash": request.query_params.get("flash"),
            "msg": request.query_params.get("msg"),
            "worker_status": heartbeat.status,
            "worker_label": heartbeat.label,
            "worker_updated_at": heartbeat.updated_at,
            "worker_heartbeat_path": str(HEARTBEAT_PATH),
        },
        status_code=status_code,
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_page_user)],
):
    _ = db
    config = read_app_config()
    return _render_settings(
        request,
        user,
        agent_value=config.agent or "",
        mail_form=_mail_form(config.mail),
        mail_config_errors=_mail_config_errors(config.mail),
        mail_warnings=_mail_warnings(config.mail),
    )


@router.post("/settings")
def settings_save(
    request: Request,
    user: Annotated[User, Depends(require_csrf)],
    agent: str = Form(""),
    mail_enabled: str = Form(""),
    mail_smtp_host: str = Form(""),
    mail_smtp_port: str = Form(""),
    mail_security: str = Form(""),
    mail_username: str = Form(""),
    mail_from_address: str = Form(""),
    mail_from_name: str = Form(""),
    mail_default_to: str = Form(""),
):
    _ = user
    agent_value = (agent or "").strip()
    enabled = (mail_enabled or "").strip().lower() in {"1", "true", "yes", "on"}
    port, port_error = _parse_port(mail_smtp_port)
    mail = _mail_from_form(
        enabled=enabled,
        smtp_host=mail_smtp_host,
        smtp_port=port,
        security=mail_security,
        username=mail_username,
        from_address=mail_from_address,
        from_name=mail_from_name,
        default_to=mail_default_to,
    )

    errors: dict[str, str] = {}
    if agent_value not in ALLOWED_AGENTS:
        errors["agent"] = "请选择代理（opencode 或 claude）"
    if port_error:
        errors["mail_smtp_port"] = port_error
    for key, message in validate_mail_config(mail).items():
        errors.setdefault(key, message)

    mail_form = _mail_form(mail)
    mail_form["smtp_port"] = (mail_smtp_port or "").strip()
    mail_form["security"] = (mail_security or "").strip().lower() or "starttls"

    if errors:
        return _render_settings(
            request,
            user,
            agent_value=agent_value,
            mail_form=mail_form,
            field_errors=errors,
            mail_warnings=_mail_warnings(mail),
        )

    try:
        write_app_config(agent_value, mail)
    except Exception as exc:  # noqa: BLE001 - keep the page usable, no secrets
        logger.warning(
            "settings save failed: {} ({})",
            type(exc).__name__,
            "config.yaml",
        )
        return _redirect("error", "保存失败，请检查 config.yaml 是否可写")

    return _redirect("ok", "已保存")


@router.post("/settings/mail/test")
def settings_mail_test(
    user: Annotated[User, Depends(require_csrf)],
    to: str = Form(""),
):
    _ = user
    target = (to or "").strip() or read_mail_config().default_to
    if not target:
        return _redirect("error", "请填写收件地址或配置默认收件人")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    html_body = (
        "<h2>GitHub 工作流测试邮件</h2>"
        "<p>收到此邮件说明 SMTP 配置可用。</p>"
        f"<p>发送时间（UTC）：{now}</p>"
    )
    try:
        send_mail(target, "GitHub 工作流测试邮件", html_body)
    except MailError as exc:
        message = exc.message
        if not message.startswith("发送失败"):
            message = f"发送失败：{message}"
        return _redirect("error", message)

    return _redirect("ok", "测试邮件已发送")
