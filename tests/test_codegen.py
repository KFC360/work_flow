from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.services.git_repo import ISSUE_TRAILER, commit_has_issue_trailer, rev_parse, run_git
from app.services.prompts import codegen_prompt
from app.tasks.jobs import run_create_pr, run_generate_code
from tests.conftest_git import git, init_bare_and_clone


def test_codegen_prompt_includes_path() -> None:
    text = codegen_prompt(design_doc_path="docs/v0001-1/design.md", design_doc_text="# x")
    assert "docs/v0001-1/design.md" in text
    assert "不要提交" in text


def _seed_feature_ready(db: Session, clone: Path, *, number: int = 7):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=1000 + number,
        account_type="User",
        login=f"u{number}",
        name=f"u{number}",
        description=None,
        avatar_url=None,
        html_url=None,
    )
    repo = repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=2000 + number,
        name=f"r{number}",
        github_full_name=f"u{number}/r{number}",
        description=None,
        html_url=None,
        default_branch="main",
        private=False,
    )
    repo.local_path = str(clone)
    repo.doc_dir = "docs"
    db.commit()
    issue = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=3000 + number,
        number=number,
        title="Add hello",
        body="implement hello",
        html_url="https://example/issues/7",
        author_login="dev",
        github_state="open",
        label_names=["功能迭代"],
        github_updated_at=None,
        action="opened",
    )
    issue.status = "pending_codegen"
    issue.kind = "feature"
    issue.design_doc_path = f"docs/v0001-{number}/design.md"
    issue.design_doc_text = "# design\n\nok\n"
    issue.iteration_no = 1
    issue.codegen_phase = "none"
    issue.branch_name = f"issue/{number}"
    db.commit()
    db.refresh(issue)
    return repo, issue


def _settings_stub(tmp_path: Path, monkeypatch):
    wt = tmp_path / "worktrees"
    wt.mkdir(exist_ok=True)

    class S:
        worktree_root = wt
        code_timeout_sec = 60
        doc_timeout_sec = 60
        git_author_name = "t"
        git_author_email = "t@t"

    monkeypatch.setattr("app.tasks.jobs.get_settings", lambda: S())
    monkeypatch.setattr("app.tasks.jobs.read_agent", lambda: "claude")
    return wt


def _agent_writes_src(rel: str = "src/hello.py", content: str = "print('hi')\n"):
    def fake_agent(agent, prompt, *, cwd, timeout_sec, log_path):
        path = Path(cwd) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("agent ok\n", encoding="utf-8")
        return 0

    return fake_agent


def test_happy_path_phases_and_shas(db: Session, tmp_path: Path, monkeypatch) -> None:
    _bare, clone = init_bare_and_clone(tmp_path / "happy")
    wt_root = _settings_stub(tmp_path / "happy", monkeypatch)
    monkeypatch.setattr("app.tasks.jobs.run_agent", _agent_writes_src())
    repo, issue = _seed_feature_ready(db, clone, number=11)
    job = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="generate_code")
    job.status = "running"
    db.commit()

    run_generate_code(db, job)
    db.refresh(issue)
    db.refresh(job)

    assert job.status == "succeeded"
    assert issue.status == "generated"
    assert issue.codegen_phase == "pushed"
    assert issue.base_commit_sha
    assert issue.doc_commit_sha
    assert issue.code_commit_sha
    assert issue.doc_commit_sha != issue.code_commit_sha
    worktree = wt_root / "codegen" / str(repo.id) / str(issue.id)
    assert commit_has_issue_trailer(worktree, issue.doc_commit_sha, issue.id)
    assert commit_has_issue_trailer(worktree, issue.code_commit_sha, issue.id)
    # branch pushed to origin
    assert git(clone, "ls-remote", "--heads", "origin", f"issue/{issue.number}")


def test_agent_interrupt_retry_resets_to_doc_sha(db: Session, tmp_path: Path, monkeypatch) -> None:
    _bare, clone = init_bare_and_clone(tmp_path / "interrupt")
    wt_root = _settings_stub(tmp_path / "interrupt", monkeypatch)
    repo, issue = _seed_feature_ready(db, clone, number=12)

    calls = {"n": 0}

    def flaky_agent(agent, prompt, *, cwd, timeout_sec, log_path):
        calls["n"] += 1
        path = Path(cwd) / "src" / "partial.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"partial-{calls['n']}\n", encoding="utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"call {calls['n']}\n", encoding="utf-8")
        if calls["n"] == 1:
            return 1
        return 0

    monkeypatch.setattr("app.tasks.jobs.run_agent", flaky_agent)

    job1 = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="generate_code")
    job1.status = "running"
    db.commit()
    run_generate_code(db, job1)
    db.refresh(issue)
    db.refresh(job1)
    assert job1.status == "failed"
    assert issue.codegen_phase == "agent_running"
    assert issue.doc_commit_sha
    doc_sha = issue.doc_commit_sha
    worktree = wt_root / "codegen" / str(repo.id) / str(issue.id)
    # dirty leftover from failed agent
    assert (worktree / "src" / "partial.py").exists()

    issue.status = "pending_codegen"
    issue.failed_action = None
    db.commit()
    job2 = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="generate_code")
    job2.status = "running"
    db.commit()
    run_generate_code(db, job2)
    db.refresh(issue)
    db.refresh(job2)

    assert job2.status == "succeeded"
    assert issue.codegen_phase == "pushed"
    assert issue.doc_commit_sha == doc_sha
    assert (worktree / "src" / "partial.py").read_text(encoding="utf-8") == "partial-2\n"
    assert calls["n"] == 2


def test_commit_before_db_recover_on_retry(db: Session, tmp_path: Path, monkeypatch) -> None:
    """Simulate: code commit exists with trailer, phase still changes_validated."""
    _bare, clone = init_bare_and_clone(tmp_path / "recover")
    wt_root = _settings_stub(tmp_path / "recover", monkeypatch)
    monkeypatch.setattr("app.tasks.jobs.run_agent", _agent_writes_src())
    repo, issue = _seed_feature_ready(db, clone, number=13)

    job1 = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="generate_code")
    job1.status = "running"
    db.commit()
    # run until we can stop after code commit by patching push to fail once mid-way —
    # instead: run full success then rewind DB phase to changes_validated keeping git commit
    run_generate_code(db, job1)
    db.refresh(issue)
    assert issue.codegen_phase == "pushed"
    code_sha = issue.code_commit_sha
    doc_sha = issue.doc_commit_sha
    worktree = wt_root / "codegen" / str(repo.id) / str(issue.id)

    # rewind DB as if crash after commit before phase write
    issue.codegen_phase = "changes_validated"
    issue.code_commit_sha = None
    issue.status = "failed"
    issue.failed_action = "generate_code"
    db.commit()

    # reset worktree HEAD to code commit (already there) and ensure clean
    run_git(["reset", "--hard", code_sha], cwd=worktree)

    job2 = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="generate_code")
    job2.status = "running"
    db.commit()

    # agent must NOT be called again if we recover from changes_validated + existing commit
    agent_calls = {"n": 0}

    def no_agent(*a, **k):
        agent_calls["n"] += 1
        raise AssertionError("agent should not run on commit recovery")

    monkeypatch.setattr("app.tasks.jobs.run_agent", no_agent)
    run_generate_code(db, job2)
    db.refresh(issue)
    db.refresh(job2)

    assert agent_calls["n"] == 0
    assert job2.status == "succeeded"
    assert issue.code_commit_sha == code_sha
    assert issue.doc_commit_sha == doc_sha
    assert issue.codegen_phase == "pushed"


def test_push_failure_retry_only_pushes(db: Session, tmp_path: Path, monkeypatch) -> None:
    _bare, clone = init_bare_and_clone(tmp_path / "pushfail")
    _settings_stub(tmp_path / "pushfail", monkeypatch)
    monkeypatch.setattr("app.tasks.jobs.run_agent", _agent_writes_src())
    repo, issue = _seed_feature_ready(db, clone, number=14)

    pushes = {"n": 0}
    real_run_git = run_git

    def run_git_wrap(args, *, cwd=None):
        if args and args[0] == "push":
            pushes["n"] += 1
            if pushes["n"] == 1:
                from app.services.git_repo import GitError

                raise GitError("simulated push reject")
        return real_run_git(args, cwd=cwd)

    monkeypatch.setattr("app.tasks.jobs.run_git", run_git_wrap)

    job1 = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="generate_code")
    job1.status = "running"
    db.commit()
    run_generate_code(db, job1)
    db.refresh(issue)
    db.refresh(job1)
    assert job1.status == "failed"
    assert issue.codegen_phase == "code_committed"
    assert issue.code_commit_sha
    code_sha = issue.code_commit_sha

    agent_calls = {"n": 0}

    def counting_agent(*a, **k):
        agent_calls["n"] += 1
        return _agent_writes_src()(*a, **k)

    monkeypatch.setattr("app.tasks.jobs.run_agent", counting_agent)
    issue.status = "failed"
    db.commit()
    job2 = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="generate_code")
    job2.status = "running"
    db.commit()
    run_generate_code(db, job2)
    db.refresh(issue)
    db.refresh(job2)

    assert agent_calls["n"] == 0
    assert job2.status == "succeeded"
    assert issue.codegen_phase == "pushed"
    assert issue.code_commit_sha == code_sha
    assert pushes["n"] == 2


def test_conflict_branch_rejected(db: Session, tmp_path: Path, monkeypatch) -> None:
    _bare, clone = init_bare_and_clone(tmp_path / "conflict")
    _settings_stub(tmp_path / "conflict", monkeypatch)
    monkeypatch.setattr("app.tasks.jobs.run_agent", _agent_writes_src())
    repo, issue = _seed_feature_ready(db, clone, number=15)

    # create foreign branch on origin without our SHA ownership
    git(clone, "checkout", "-b", f"issue/{issue.number}")
    (clone / "foreign.txt").write_text("nope\n", encoding="utf-8")
    git(clone, "add", "foreign.txt")
    git(clone, "commit", "-m", "foreign")
    git(clone, "push", "-u", "origin", f"issue/{issue.number}")
    git(clone, "checkout", "main")

    job = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="generate_code")
    job.status = "running"
    db.commit()
    run_generate_code(db, job)
    db.refresh(issue)
    db.refresh(job)
    assert job.status == "failed"
    assert "无法证明属于本 Issue" in (job.error or "")
    assert issue.codegen_phase in {"none", "worktree_ready"} or issue.base_commit_sha is None


def test_sensitive_path_rejected(db: Session, tmp_path: Path, monkeypatch) -> None:
    _bare, clone = init_bare_and_clone(tmp_path / "sensitive")
    _settings_stub(tmp_path / "sensitive", monkeypatch)
    monkeypatch.setattr(
        "app.tasks.jobs.run_agent",
        _agent_writes_src(rel=".env", content="SECRET=1\n"),
    )
    repo, issue = _seed_feature_ready(db, clone, number=16)
    job = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="generate_code")
    job.status = "running"
    db.commit()
    run_generate_code(db, job)
    db.refresh(issue)
    db.refresh(job)
    assert job.status == "failed"
    assert "敏感路径" in (job.error or "")
    assert issue.status == "failed"
    assert issue.codegen_phase == "agent_running"
    # not pushed
    remote = git(clone, "ls-remote", "--heads", "origin", f"issue/{issue.number}")
    assert remote == ""


def test_existing_pr_adopted(db: Session, tmp_path: Path, monkeypatch) -> None:
    _bare, clone = init_bare_and_clone(tmp_path / "pr")
    repo, issue = _seed_feature_ready(db, clone, number=17)
    issue.status = "generated"
    issue.codegen_phase = "pushed"
    issue.branch_name = f"issue/{issue.number}"
    db.commit()

    class FakeClient:
        def find_open_pull_request(self, owner, repo_name, head):
            return {"number": 42, "html_url": "https://github.com/u/r/pull/42"}

        def create_pull_request(self, *a, **k):
            raise AssertionError("should not create")

        def close(self):
            pass

    monkeypatch.setattr("app.tasks.jobs.GitHubClient", FakeClient)
    job = job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="create_pr")
    job.status = "running"
    db.commit()
    run_create_pr(db, job)
    db.refresh(issue)
    db.refresh(job)
    assert job.status == "succeeded"
    assert issue.status == "pr_opened"
    assert issue.pr_number == 42
    assert issue.pr_url.endswith("/42")
