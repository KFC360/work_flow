from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.services.git_repo import porcelain_untracked_covers
from app.services.issues import design_doc_relpath
from app.tasks.jobs import run_write_doc


def test_design_path_format() -> None:
    from app.services.issues import codegen_branch_name

    assert design_doc_relpath("docs", 3, 13) == "docs/v0003-13/design.md"
    assert codegen_branch_name(2) == "dev_2"


def test_porcelain_covers_untracked_parent_dir() -> None:
    rel = "docs/v0001-9/design.md"
    assert porcelain_untracked_covers("?? docs/v0001-9/\n", rel)
    assert porcelain_untracked_covers("?? docs/v0001-9/design.md\n", rel)
    assert not porcelain_untracked_covers("?? other.md\n", rel)
    assert not porcelain_untracked_covers("", rel)


def test_write_doc_success(db: Session, tmp_path: Path, monkeypatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    # minimal git repo
    import subprocess

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo_dir, check=True)
    (repo_dir / "README").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(repo_dir)], cwd=repo_dir, check=True)

    company = company_crud.upsert_from_github(
        db,
        github_account_id=9,
        account_type="User",
        login="u",
        name="u",
        description=None,
        avatar_url=None,
        html_url=None,
    )
    repo = repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=9,
        name="r",
        github_full_name="u/r",
        description=None,
        html_url=None,
        default_branch="main",
        private=False,
    )
    repo.local_path = str(repo_dir)
    repo.doc_dir = "docs"
    db.commit()
    issue = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=9,
        number=9,
        title="Add feature",
        body="details",
        html_url="u",
        author_login="u",
        github_state="open",
        label_names=["功能迭代"],
        github_updated_at=None,
        action="opened",
    )
    job = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="write_doc")
    job.status = "running"
    db.commit()

    wt_root = tmp_path / "wt"
    wt_root.mkdir()
    monkeypatch.setattr(
        "app.tasks.jobs.get_settings",
        lambda: type(
            "S",
            (),
            {
                "worktree_root": wt_root,
                "doc_timeout_sec": 30,
                "git_author_name": "t",
                "git_author_email": "t@t",
            },
        )(),
    )
    monkeypatch.setattr("app.tasks.jobs.read_agent", lambda: "claude")

    def fake_agent(agent, prompt, *, cwd, timeout_sec, log_path, on_progress=None):
        assert "基石" in prompt or "docs/README.md" in prompt or "待确认" in prompt
        rel = "docs/v0001-9/design.md"
        path = Path(cwd) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# design\n\nbody\n", encoding="utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok\n", encoding="utf-8")
        if on_progress:
            on_progress()
        return 0

    monkeypatch.setattr("app.tasks.jobs.run_agent", fake_agent)
    # fetch origin may fail for local remote — stub git fetch
    real_run = __import__("app.services.git_repo", fromlist=["run_git"]).run_git

    def run_git_stub(args, *, cwd=None):
        if args[:1] == ["fetch"]:
            return ""
        if args[:2] == ["worktree", "add"]:
            # emulate detached worktree by copying files
            dest = Path(args[args.index("--detach") + 1] if "--detach" in args else args[2])
            dest.mkdir(parents=True, exist_ok=True)
            for p in Path(cwd).iterdir():
                if p.name == ".git":
                    continue
                target = dest / p.name
                if p.is_file():
                    target.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            # init git in worktree-like dir
            import subprocess

            subprocess.run(["git", "init"], cwd=dest, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=dest, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=dest, check=True)
            subprocess.run(["git", "add", "."], cwd=dest, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=dest, check=True, capture_output=True)
            return ""
        if args[:2] == ["worktree", "remove"]:
            import shutil

            path = Path(args[-1])
            if path.exists():
                shutil.rmtree(path)
            return ""
        return real_run(args, cwd=cwd)

    monkeypatch.setattr("app.tasks.jobs.run_git", run_git_stub)

    run_write_doc(db, job)
    db.refresh(issue)
    db.refresh(job)
    assert job.status == "succeeded"
    assert issue.status == "pending_codegen"
    assert issue.design_doc_text is not None
    assert issue.iteration_no == 1
    assert issue.design_doc_path == "docs/v0001-9/design.md"
