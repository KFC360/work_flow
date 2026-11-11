from __future__ import annotations

import os
import select
import shlex
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from app.core.settings import get_settings
from app.services.worker_heartbeat import PROGRESS_HEARTBEAT_INTERVAL_SEC


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


def _agent_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("TERM", "dumb")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")
    return env


def _kill_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def run_agent(
    agent: str,
    prompt: str,
    *,
    cwd: Path,
    timeout_sec: int,
    log_path: Path,
    on_progress: Callable[[], None] | None = None,
    progress_interval_sec: float = PROGRESS_HEARTBEAT_INTERVAL_SEC,
) -> int:
    cmd = build_command(agent, prompt)
    # Match interactive shell: closed stdin + line-buffered stdout when possible.
    # Supervisor-spawned runs without a TTY previously hung with empty logs.
    if shutil.which("stdbuf"):
        cmd = ["stdbuf", "-oL", "-eL", *cmd]

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", buffering=1) as logf:
        logf.write(f"$ {' '.join(cmd)}\n")
        logf.flush()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=_agent_env(),
                bufsize=0,
            )
        except FileNotFoundError as exc:
            raise AgentError(f"找不到命令 {cmd[0]}") from exc

        assert proc.stdout is not None
        deadline = time.monotonic() + timeout_sec
        last_progress = time.monotonic()

        def maybe_progress(force: bool = False) -> None:
            nonlocal last_progress
            if on_progress is None:
                return
            now = time.monotonic()
            if force or now - last_progress >= progress_interval_sec:
                on_progress()
                last_progress = now

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_process_group(proc.pid)
                    raise AgentError("代理超时", exit_code=None)
                ready, _, _ = select.select([proc.stdout], [], [], min(1.0, max(remaining, 0.05)))
                maybe_progress()
                if ready:
                    chunk = proc.stdout.read(4096)
                    if not chunk:
                        break
                    logf.write(chunk.decode("utf-8", errors="replace"))
                    logf.flush()
                    maybe_progress()
                elif proc.poll() is not None:
                    # Process exited; drain any remaining buffered bytes.
                    while True:
                        chunk = proc.stdout.read(4096)
                        if not chunk:
                            break
                        logf.write(chunk.decode("utf-8", errors="replace"))
                        logf.flush()
                    break
        finally:
            if proc.poll() is None:
                _kill_process_group(proc.pid)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_process_group(proc.pid)
                proc.wait(timeout=5)
            maybe_progress(force=True)

        return proc.returncode if proc.returncode is not None else -1


def read_log_excerpt(log_path: Path, max_bytes: int = 8 * 1024) -> str:
    if not log_path.exists():
        return ""
    data = log_path.read_bytes()
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace")
    return data[-max_bytes:].decode("utf-8", errors="replace")
