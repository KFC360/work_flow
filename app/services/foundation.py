from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

FOUNDATION_MAX_BYTES = 32 * 1024


@dataclass(frozen=True)
class FoundationInfo:
    rel_path: str
    exists: bool
    text: str
    truncated: bool


def foundation_relpath(doc_dir: str) -> str:
    return f"{doc_dir.rstrip('/')}/README.md"


def read_foundation_from_origin(
    local_path: str | Path,
    *,
    default_branch: str,
    doc_dir: str,
    max_bytes: int = FOUNDATION_MAX_BYTES,
) -> FoundationInfo:
    """Read foundation from local origin/{default_branch} without fetch."""
    rel = foundation_relpath(doc_dir)
    ref_path = f"origin/{default_branch}:{rel}"
    proc = subprocess.run(
        ["git", "show", ref_path],
        cwd=str(local_path),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return FoundationInfo(rel_path=rel, exists=False, text="", truncated=False)
    raw = proc.stdout
    truncated = len(raw) > max_bytes
    chunk = raw[:max_bytes] if truncated else raw
    text = chunk.decode("utf-8", errors="replace")
    return FoundationInfo(rel_path=rel, exists=True, text=text, truncated=truncated)


def read_foundation_from_worktree(
    worktree: Path,
    *,
    doc_dir: str,
    max_bytes: int = FOUNDATION_MAX_BYTES,
) -> FoundationInfo:
    rel = foundation_relpath(doc_dir)
    path = worktree / rel
    if not path.is_file():
        return FoundationInfo(rel_path=rel, exists=False, text="", truncated=False)
    raw = path.read_bytes()
    truncated = len(raw) > max_bytes
    chunk = raw[:max_bytes] if truncated else raw
    text = chunk.decode("utf-8", errors="replace")
    return FoundationInfo(rel_path=rel, exists=True, text=text, truncated=truncated)
