from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_SCHEMA = "github_workflow"

load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    database_url: str
    github_webhook_secret: str
    github_token: str
    git_author_name: str
    git_author_email: str
    app_admin_user: str
    app_admin_password: str
    jwt_secret_key: str
    access_token_expire_minutes: int
    doc_timeout_sec: int
    code_timeout_sec: int
    worktree_root: Path
    claude_args: str
    opencode_args: str
    config_yaml_path: Path


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=_env(
            "DATABASE_URL",
            "postgresql+psycopg://github_workflow:github_workflow@127.0.0.1:55438/github_workflow",
        ),
        github_webhook_secret=_env("GITHUB_WEBHOOK_SECRET"),
        github_token=_env("GITHUB_TOKEN"),
        git_author_name=_env("GIT_AUTHOR_NAME", "github-workflow"),
        git_author_email=_env("GIT_AUTHOR_EMAIL", "github-workflow@localhost"),
        app_admin_user=_env("APP_ADMIN_USER", "admin"),
        app_admin_password=_env("APP_ADMIN_PASSWORD"),
        jwt_secret_key=_env("JWT_SECRET_KEY", "change-me"),
        access_token_expire_minutes=_env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 30),
        doc_timeout_sec=_env_int("DOC_TIMEOUT_SEC", 900),
        code_timeout_sec=_env_int("CODE_TIMEOUT_SEC", 1800),
        worktree_root=Path(_env("WORKTREE_ROOT", "/var/lib/github-workflow/worktrees")),
        claude_args=_env("CLAUDE_ARGS"),
        opencode_args=_env("OPENCODE_ARGS"),
        config_yaml_path=PROJECT_ROOT / "config.yaml",
    )
