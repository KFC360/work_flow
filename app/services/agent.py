from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from app.core.settings import get_settings


class AgentError(Exception):
    def __init__(self, message: str, exit_code: int | None = None):
        super().__init__(message)
        self.exit_code = exit_code


def build_command(agent: str, prompt: str) -> list[str]:
    settings = get_settings()
    if agent == "claude":
        if settings.claude_args.strip():
            return ["claude", *shlex.split(settings.claude_args), prompt]
        return [
            "claude",
            "-p",
            prompt,
            "--permission-mode",
            "acceptEdits",
            "--output-format",
            "text",
        ]
    if agent == "opencode":
        if settings.opencode_args.strip():
            return ["opencode", *shlex.split(settings.opencode_args), prompt]
        return ["opencode", "run", prompt]
    raise AgentError(f"unknown agent {agent}")


def run_agent(
    agent: str,
    prompt: str,
    *,
    cwd: Path,
    timeout_sec: int,
    log_path: Path,
) -> int:
    cmd = build_command(agent, prompt)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as logf:
        logf.write(f"$ {' '.join(cmd)}\n")
        logf.flush()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=timeout_sec,
                check=False,
                start_new_session=True,
                env=os.environ.copy(),
            )
        except FileNotFoundError as exc:
            raise AgentError(f"找不到命令 {cmd[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AgentError("代理超时", exit_code=None) from exc
    return proc.returncode


def read_log_excerpt(log_path: Path, max_bytes: int = 8 * 1024) -> str:
    if not log_path.exists():
        return ""
    data = log_path.read_bytes()
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace")
    return data[-max_bytes:].decode("utf-8", errors="replace")
