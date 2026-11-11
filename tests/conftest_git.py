from __future__ import annotations

import subprocess
from pathlib import Path


def init_bare_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    """Create bare origin + working clone with main branch and origin remote."""
    bare = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(bare), str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=clone, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=clone, check=True)
    (clone / "README").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=clone, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=clone, check=True, capture_output=True)
    return bare, clone


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()
