from __future__ import annotations

from pathlib import Path

from app.services.foundation import (
    FOUNDATION_MAX_BYTES,
    foundation_relpath,
    read_foundation_from_origin,
    read_foundation_from_worktree,
)
from app.services.prompts import write_doc_prompt


def test_foundation_relpath() -> None:
    assert foundation_relpath("docs") == "docs/README.md"


def test_prompt_includes_foundation_when_present(tmp_path: Path) -> None:
    info = read_foundation_from_worktree(tmp_path, doc_dir="docs")
    assert info.exists is False
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("# foundation\n", encoding="utf-8")
    info = read_foundation_from_worktree(tmp_path, doc_dir="docs")
    prompt = write_doc_prompt(
        title="t",
        body="b",
        rel_path="docs/v0001-1/design.md",
        foundation=info,
    )
    assert "docs/README.md" in prompt
    assert "# foundation" in prompt
    assert "@documentation" in prompt
    assert "Web Search" in prompt
    assert "预授权" in prompt
    assert "不得向用户提问" in prompt


def test_codegen_prompt_mentions_ui_skill() -> None:
    from app.services.prompts import codegen_prompt

    prompt = codegen_prompt(
        design_doc_path="docs/v0001-1/design.md",
        design_doc_text="x",
        foundation=None,
    )
    assert "@ui-ux-pro-max" in prompt
    assert "Web Search" in prompt
    assert "预授权" in prompt


def test_prompt_requires_pending_when_missing(tmp_path: Path) -> None:
    info = read_foundation_from_worktree(tmp_path, doc_dir="docs")
    prompt = write_doc_prompt(title="t", body="b", rel_path="docs/v0001-1/design.md", foundation=info)
    assert "基石入口" in prompt
    assert "待确认" in prompt


def test_read_foundation_from_origin_uses_git_show(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    class Proc:
        def __init__(self, returncode: int, stdout: bytes):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = b""

    def fake_run(args, cwd=None, capture_output=True, check=False):
        calls.append(list(args))
        if args[:2] == ["git", "show"]:
            return Proc(0, b"base from origin\n")
        return Proc(1, b"")

    monkeypatch.setattr("app.services.foundation.subprocess.run", fake_run)
    info = read_foundation_from_origin(tmp_path, default_branch="main", doc_dir="docs")
    assert info.exists is True
    assert "base from origin" in info.text
    assert calls[0] == ["git", "show", "origin/main:docs/README.md"]

    def missing_run(args, cwd=None, capture_output=True, check=False):
        return Proc(128, b"")

    monkeypatch.setattr("app.services.foundation.subprocess.run", missing_run)
    missing = read_foundation_from_origin(tmp_path, default_branch="main", doc_dir="docs")
    assert missing.exists is False


def test_foundation_truncation(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    big = "a" * (FOUNDATION_MAX_BYTES + 100)
    (docs / "README.md").write_text(big, encoding="utf-8")
    info = read_foundation_from_worktree(tmp_path, doc_dir="docs")
    assert info.truncated is True
    assert len(info.text.encode("utf-8")) <= FOUNDATION_MAX_BYTES
