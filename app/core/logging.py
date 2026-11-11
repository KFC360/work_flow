from __future__ import annotations

import re
import sys

from loguru import logger

from app.core.settings import get_settings

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(access_token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(bearer\s+)\S+"),
]


def _scrub(message: str) -> str:
    settings = get_settings()
    secrets = [
        settings.github_webhook_secret,
        settings.github_token,
        settings.jwt_secret_key,
        settings.app_admin_password,
    ]
    scrubbed = message
    for secret in secrets:
        if secret:
            scrubbed = scrubbed.replace(secret, "***")
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub(r"\1***", scrubbed)
    return scrubbed


def setup_logging() -> None:
    logger.remove()

    def sink(message: object) -> None:
        record = message.record  # type: ignore[attr-defined]
        text = _scrub(str(record["message"]))
        sys.stderr.write(f"{record['time']:%Y-%m-%d %H:%M:%S} | {record['level'].name} | {text}\n")

    logger.add(sink, level="INFO")
