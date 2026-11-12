from __future__ import annotations

import os
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path

import yaml
from loguru import logger

from app.core.settings import get_settings

ALLOWED_AGENTS = {"opencode", "claude"}
ALLOWED_SECURITY = {"ssl", "starttls", "none"}


@dataclass(frozen=True)
class MailConfig:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 0
    security: str = ""
    username: str = ""
    from_address: str = ""
    from_name: str = ""
    default_to: str = ""


@dataclass(frozen=True)
class AppConfig:
    agent: str | None
    mail: MailConfig
    warning: str | None


def _config_path() -> Path:
    return get_settings().config_yaml_path


def _read_top_level() -> tuple[dict, str | None]:
    path = _config_path()
    if not path.exists():
        return {}, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.warning(f"config.yaml parse failed: {path} ({type(exc).__name__})")
        return {}, "config.yaml 无法解析，保存将重建已知配置段。"
    except OSError as exc:
        logger.warning(f"config.yaml read failed: {path} ({type(exc).__name__})")
        return {}, "config.yaml 读取失败，保存将重建已知配置段。"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        logger.warning(f"config.yaml top level is not a mapping: {path}")
        return {}, "config.yaml 顶层不是映射，保存将重建已知配置段。"
    return data, None


def _parse_bool(value: object) -> bool:
    return value is True


def _parse_port(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return 0


def _parse_security(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().lower()
    return text if text in ALLOWED_SECURITY else ""


def _parse_string(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _mail_from_mapping(data: object) -> tuple[MailConfig, str | None]:
    if not isinstance(data, dict):
        if data is None:
            return MailConfig(), None
        logger.warning("config.yaml mail section is not a mapping")
        return MailConfig(), "mail 段格式不正确，保存将重建邮件配置。"
    raw_security = data.get("security")
    security = _parse_security(raw_security)
    warning = None
    if isinstance(raw_security, str) and raw_security.strip() and not security:
        warning = "邮件加密方式无效，请重新选择。"
    return (
        MailConfig(
            enabled=_parse_bool(data.get("enabled")),
            smtp_host=_parse_string(data.get("smtp_host")),
            smtp_port=_parse_port(data.get("smtp_port")),
            security=security,
            username=_parse_string(data.get("username")),
            from_address=_parse_string(data.get("from_address")),
            from_name=_parse_string(data.get("from_name")),
            default_to=_parse_string(data.get("default_to")),
        ),
        warning,
    )


def read_app_config() -> AppConfig:
    data, warning = _read_top_level()
    raw_agent = data.get("agent")
    agent = raw_agent if raw_agent in ALLOWED_AGENTS else None
    mail, mail_warning = _mail_from_mapping(data.get("mail"))
    return AppConfig(agent=agent, mail=mail, warning=warning or mail_warning)


def read_agent() -> str | None:
    return read_app_config().agent


def read_mail_config() -> MailConfig:
    return read_app_config().mail


def has_header_break(value: str) -> bool:
    return "\r" in value or "\n" in value


def is_valid_address(value: str) -> bool:
    if not value or has_header_break(value):
        return False
    _name, address = parseaddr(value)
    return bool(address) and "@" in address and not has_header_break(address)


def is_valid_recipient_list(value: str) -> bool:
    if not value:
        return True
    for part in value.split(","):
        if not part.strip() or not is_valid_address(part):
            return False
    return True


def validate_mail_config(mail: MailConfig) -> dict[str, str]:
    """Return field errors for the settings form.

    Missing required fields are only reported while mail is enabled. Syntax
    errors are reported for any non-empty value, even when disabled.
    """
    errors: dict[str, str] = {}
    if mail.enabled:
        if not mail.smtp_host:
            errors["mail_smtp_host"] = "SMTP 主机不能为空"
        if mail.smtp_port == 0:
            errors["mail_smtp_port"] = "SMTP 端口不能为空"
        if not mail.security:
            errors["mail_security"] = "加密方式不能为空"
        if not mail.from_address:
            errors["mail_from_address"] = "发件人地址不能为空"

    if mail.smtp_port and not (1 <= mail.smtp_port <= 65535):
        errors["mail_smtp_port"] = "SMTP 端口须为 1–65535 的整数"
    if mail.security and mail.security not in ALLOWED_SECURITY:
        errors["mail_security"] = "加密方式无效"
    if mail.smtp_host and (has_header_break(mail.smtp_host) or "/" in mail.smtp_host):
        errors["mail_smtp_host"] = "SMTP 主机不能包含协议、路径或换行"
    if mail.from_address and not is_valid_address(mail.from_address):
        errors["mail_from_address"] = "发件人地址格式无效"
    if mail.from_name and has_header_break(mail.from_name):
        errors["mail_from_name"] = "发件人显示名不能包含换行"
    if mail.default_to and not is_valid_recipient_list(mail.default_to):
        errors["mail_default_to"] = "默认收件人地址格式无效"
    return errors


def _mail_mapping(mail: MailConfig) -> dict[str, object]:
    return {
        "enabled": bool(mail.enabled),
        "smtp_host": mail.smtp_host,
        "smtp_port": int(mail.smtp_port),
        "security": mail.security,
        "username": mail.username,
        "from_address": mail.from_address,
        "from_name": mail.from_name,
        "default_to": mail.default_to,
    }


def write_app_config(agent: str, mail: MailConfig) -> None:
    if agent not in ALLOWED_AGENTS:
        raise ValueError("invalid agent")

    path = _config_path()
    data, _warning = _read_top_level()
    data["agent"] = agent
    data["mail"] = _mail_mapping(mail)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def write_agent(agent: str) -> None:
    write_app_config(agent, read_mail_config())
