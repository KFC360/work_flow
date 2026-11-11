from __future__ import annotations

from pathlib import Path

from app.core.settings import PROJECT_ROOT
from app.services.agent import read_log_excerpt

JOBS_LOG_DIR = (PROJECT_ROOT / "logs" / "jobs").resolve()


def safe_job_log_path(log_path: str | None) -> Path | None:
    if not log_path:
        return None
    try:
        resolved = Path(log_path).resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(JOBS_LOG_DIR)
    except ValueError:
        return None
    if not resolved.is_file():
        return None
    return resolved


def read_job_log_tail(log_path: str | None, *, max_bytes: int = 16 * 1024) -> str:
    path = safe_job_log_path(log_path)
    if path is None:
        return ""
    return read_log_excerpt(path, max_bytes=max_bytes)
