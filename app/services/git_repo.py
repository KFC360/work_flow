from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    pass


@dataclass(frozen=True)
class OriginInfo:
    state: str  # none | match | mismatch | unavailable
    origin: str | None
    detail: str


ISSUE_TRAILER = "GitHub-Workflow-Issue-ID"


def run_git(args: list[str], *, cwd: str | Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or proc.stdout.strip() or "git failed")
    return proc.stdout.strip()


def parse_origin_full_name(url: str) -> str | None:
    url = url.strip()
    m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1)
    m = re.match(r"https://github\.com/(.+?)(?:\.git)?/?$", url)
    if m:
        return m.group(1)
    return None


def inspect_origin(local_path: str | Path | None, expected_full_name: str) -> OriginInfo:
    """Read-only origin check for the repo page. Never raises; never fetches."""
    if not local_path:
        return OriginInfo(state="none", origin=None, detail="")
    path = Path(local_path)
    try:
        resolved = path.resolve()
        if not resolved.is_dir():
            return OriginInfo(state="unavailable", origin=None, detail="路径不存在或不是目录")
        top = run_git(["rev-parse", "--show-toplevel"], cwd=resolved)
        if Path(top).resolve() != resolved:
            return OriginInfo(state="unavailable", origin=None, detail="路径不是 git 顶层目录")
        origin = run_git(["remote", "get-url", "origin"], cwd=resolved)
    except (GitError, OSError):
        return OriginInfo(state="unavailable", origin=None, detail="无法读取 origin")

    full = parse_origin_full_name(origin)
    if full is None:
        return OriginInfo(state="mismatch", origin=origin, detail="origin 不是可解析的 GitHub 地址")
    if full != expected_full_name:
        return OriginInfo(state="mismatch", origin=origin, detail=f"origin 指向 {full}")
    return OriginInfo(state="match", origin=origin, detail="")


def validate_local_path(local_path: str, expected_full_name: str) -> None:
    path = Path(local_path).resolve()
    if not path.is_dir():
        raise GitError("路径不是目录")
    top = run_git(["rev-parse", "--show-toplevel"], cwd=path)
    if Path(top).resolve() != path:
        raise GitError("路径必须是 git 顶层目录")
    origin = run_git(["remote", "get-url", "origin"], cwd=path)
    full = parse_origin_full_name(origin)
    if full != expected_full_name:
        raise GitError(f"origin 为 {full!r}，与 {expected_full_name!r} 不一致")


def validate_doc_dir(local_path: str, doc_dir: str) -> None:
    if not doc_dir or doc_dir.startswith("/") or ".." in Path(doc_dir).parts:
        raise GitError("文档目录必须是相对路径，且不能包含 ..")
    sample = f"{doc_dir.rstrip('/')}/v0001-1/design.md"
    proc = subprocess.run(
        ["git", "check-ignore", "-q", sample],
        cwd=local_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        raise GitError("文档示例路径会被 gitignore 忽略")


def rev_parse(cwd: Path | str, ref: str = "HEAD") -> str:
    return run_git(["rev-parse", ref], cwd=cwd)


def is_clean(cwd: Path | str) -> bool:
    return run_git(["status", "--porcelain"], cwd=cwd) == ""


def porcelain_path(line: str) -> str:
    """Extract path from a `git status --porcelain` line (untracked/rename-safe enough for ?? / A / M)."""
    raw = line.rstrip("\n")
    if len(raw) >= 3 and raw[2] == " ":
        path = raw[3:]
    else:
        path = raw.lstrip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip().strip('"').strip("/")


def porcelain_untracked_covers(porcelain: str, rel: str) -> bool:
    """True if porcelain lists rel itself or an untracked parent dir that contains it.

    Git often reports only `?? docs/v0001-9/` for a new nested file; matching the
    full file path alone would falsely fail write_doc validation.
    """
    rel_norm = rel.strip().strip("/")
    if not rel_norm:
        return False
    for ln in porcelain.splitlines():
        if not ln.strip():
            continue
        path = porcelain_path(ln)
        if not path:
            continue
        if path == rel_norm or rel_norm.startswith(path + "/") or path.startswith(rel_norm + "/"):
            return True
    return False


def branch_exists_local(cwd: Path | str, branch: str) -> bool:
    proc = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(cwd),
        check=False,
    )
    return proc.returncode == 0


def branch_exists_remote(cwd: Path | str, branch: str) -> bool:
    proc = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
        cwd=str(cwd),
        check=False,
    )
    return proc.returncode == 0


def commit_body(cwd: Path | str, sha: str) -> str:
    return run_git(["log", "-1", "--format=%B", sha], cwd=cwd)


def commit_has_issue_trailer(cwd: Path | str, sha: str, issue_id: int) -> bool:
    body = commit_body(cwd, sha)
    needle = f"{ISSUE_TRAILER}: {issue_id}"
    return needle in body.splitlines()


def find_tip_commit_with_trailer(cwd: Path | str, issue_id: int, max_walk: int = 20) -> str | None:
    """Walk HEAD~n looking for a commit with our Issue trailer."""
    try:
        head = rev_parse(cwd, "HEAD")
    except GitError:
        return None
    sha = head
    for _ in range(max_walk):
        if commit_has_issue_trailer(cwd, sha, issue_id):
            return sha
        try:
            sha = rev_parse(cwd, f"{sha}^")
        except GitError:
            break
    return None


def reset_hard(cwd: Path | str, sha: str) -> None:
    run_git(["reset", "--hard", sha], cwd=cwd)
    run_git(["clean", "-fd"], cwd=cwd)


def parent_sha(cwd: Path | str, sha: str) -> str | None:
    try:
        return rev_parse(cwd, f"{sha}^")
    except GitError:
        return None
