from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.settings import PROJECT_ROOT, get_settings
from app.crud import job as job_crud
from app.models.issue import Issue
from app.models.job import Job
from app.models.repository import Repository
from app.services.agent import AgentError, read_log_excerpt, run_agent
from app.services.agent_test_db import (
    AgentTestDbError,
    agent_env_for_test_db,
    create_job_database,
    drop_job_database,
)
from app.services.config_agent import read_agent
from app.services.foundation import read_foundation_from_worktree
from app.services.git_repo import (
    ISSUE_TRAILER,
    GitError,
    branch_exists_local,
    branch_exists_remote,
    commit_has_issue_trailer,
    find_tip_commit_with_trailer,
    is_clean,
    parent_sha,
    porcelain_untracked_covers,
    reset_hard,
    rev_parse,
    run_git,
)
from app.services.github_api import GitHubClient
from app.services.issues import design_doc_relpath
from app.services.prompts import codegen_prompt, write_doc_prompt
from app.services.worker_heartbeat import write_heartbeat


def _agent_progress(db: Session, job: Job, issue: Issue, log_path: Path):
    def _cb() -> None:
        job.log_excerpt = read_log_excerpt(log_path, max_bytes=16 * 1024)
        db.commit()
        write_heartbeat(job_id=job.id, issue_id=issue.id, action=job.action)

    return _cb


def _fail_issue(db: Session, issue: Issue, job: Job, *, action: str, error: str) -> None:
    issue.status = "failed"
    issue.failed_action = action
    issue.last_error = error
    job.status = "failed"
    job.error = error
    job.finished_at = datetime.now(timezone.utc)
    db.commit()


def _next_iteration(db: Session, repository_id: int) -> int:
    current = db.scalar(
        select(func.max(Issue.iteration_no)).where(Issue.repository_id == repository_id)
    )
    return int(current or 0) + 1


def run_write_doc(db: Session, job: Job) -> None:
    settings = get_settings()
    issue = db.get(Issue, job.issue_id)
    repo = db.get(Repository, job.repository_id)
    assert issue and repo and repo.local_path

    if issue.github_state != "open":
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        job.error = "Issue not open"
        db.commit()
        return

    agent = read_agent()
    if not agent:
        _fail_issue(db, issue, job, action="write_doc", error="未选代理")
        return
    job.agent = agent
    issue.status = "drafting"
    issue.last_error = None
    db.commit()

    worktree = Path(settings.worktree_root) / "write-doc" / str(job.id)
    log_path = PROJECT_ROOT / "logs" / "jobs" / f"{job.id}.log"
    job.log_path = str(log_path)
    db.commit()

    try:
        run_git(["fetch", "origin"], cwd=repo.local_path)
        worktree.parent.mkdir(parents=True, exist_ok=True)
        if worktree.exists():
            run_git(["worktree", "remove", "--force", str(worktree)], cwd=repo.local_path)
        run_git(
            ["worktree", "add", "--detach", str(worktree), f"origin/{repo.default_branch}"],
            cwd=repo.local_path,
        )

        if issue.design_doc_path:
            rel = issue.design_doc_path
            iteration_no = issue.iteration_no
        else:
            iteration_no = _next_iteration(db, repo.id)
            rel = design_doc_relpath(repo.doc_dir, iteration_no, issue.number)

        foundation = read_foundation_from_worktree(worktree, doc_dir=repo.doc_dir)
        prompt = write_doc_prompt(
            title=issue.title,
            body=issue.body,
            rel_path=rel,
            foundation=foundation,
        )
        code = run_agent(
            agent,
            prompt,
            cwd=worktree,
            timeout_sec=settings.doc_timeout_sec,
            log_path=log_path,
            on_progress=_agent_progress(db, job, issue, log_path),
        )
        job.log_excerpt = read_log_excerpt(log_path)
        job.exit_code = code
        if code != 0:
            raise AgentError(f"代理退出码 {code}", exit_code=code)

        target = worktree / rel
        if not target.exists() or not target.read_text(encoding="utf-8").strip():
            raise AgentError("设计文档缺失或为空")

        porcelain = run_git(["status", "--porcelain"], cwd=worktree)
        lines = [ln for ln in porcelain.splitlines() if ln.strip()]
        for ln in lines:
            if not ln.startswith("??"):
                raise AgentError("出现已跟踪文件的修改")
        if not porcelain_untracked_covers(porcelain, rel):
            raise AgentError("未找到预期文档路径")

        text = target.read_text(encoding="utf-8")
        issue.design_doc_text = text
        issue.design_source_updated_at = issue.github_updated_at
        if issue.design_doc_path is None:
            issue.iteration_no = iteration_no
            issue.design_doc_path = rel
        issue.status = "pending_codegen"
        issue.failed_action = None
        issue.last_error = None
        job.status = "succeeded"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except (AgentError, GitError) as exc:
        job.log_excerpt = read_log_excerpt(log_path)
        _fail_issue(db, issue, job, action="write_doc", error=str(exc))
    finally:
        try:
            if worktree.exists():
                run_git(["worktree", "remove", "--force", str(worktree)], cwd=repo.local_path)
        except GitError as exc:
            logger.warning(f"cleanup worktree failed: {exc}")


def run_create_pr(db: Session, job: Job) -> None:
    issue = db.get(Issue, job.issue_id)
    repo = db.get(Repository, job.repository_id)
    assert issue and repo
    if issue.github_state != "open":
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return
    issue.status = "generating"
    db.commit()
    owner, name = repo.github_full_name.split("/", 1)
    client = GitHubClient()
    try:
        existing = client.find_open_pull_request(owner, name, issue.branch_name or f"issue/{issue.number}")
        if existing:
            issue.pr_number = existing.get("number")
            issue.pr_url = existing.get("html_url")
            issue.status = "pr_opened"
            issue.codegen_phase = "pr_opened"
            issue.failed_action = None
            job.status = "succeeded"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        pr = client.create_pull_request(
            owner,
            name,
            title=issue.title,
            head=issue.branch_name or f"issue/{issue.number}",
            base=repo.default_branch,
            body=f"Auto PR for #{issue.number}\n\n{issue.design_doc_path or ''}",
        )
        issue.pr_number = pr.get("number")
        issue.pr_url = pr.get("html_url")
        issue.status = "pr_opened"
        issue.codegen_phase = "pr_opened"
        issue.failed_action = None
        job.status = "succeeded"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        _fail_issue(db, issue, job, action="create_pr", error=str(exc))
    finally:
        client.close()


def _codegen_worktree_path(settings, repo: Repository, issue: Issue) -> Path:
    return Path(settings.worktree_root) / "codegen" / str(repo.id) / str(issue.id)


def _git_commit(
    cwd: Path,
    *,
    message: str,
    author_name: str,
    author_email: str,
) -> str:
    run_git(
        [
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "-m",
            message,
        ],
        cwd=cwd,
    )
    return rev_parse(cwd, "HEAD")


def _recover_codegen_phase_from_git(db: Session, issue: Issue, worktree: Path) -> None:
    """If commits exist with Issue trailer but DB phase lags, advance SHA/phase."""
    if not worktree.exists():
        return
    tip = find_tip_commit_with_trailer(worktree, issue.id)
    if tip is None:
        return
    # Prefer newest matching tip: if code commit missing but tip has trailer and parent is doc
    if issue.doc_commit_sha and tip != issue.doc_commit_sha:
        parent = parent_sha(worktree, tip)
        if parent == issue.doc_commit_sha or (
            issue.doc_commit_sha and commit_has_issue_trailer(worktree, tip, issue.id)
        ):
            if issue.codegen_phase in {
                "doc_committed",
                "agent_running",
                "changes_validated",
            }:
                # tip is likely the code commit after doc
                if parent == issue.doc_commit_sha:
                    issue.code_commit_sha = tip
                    issue.codegen_phase = "code_committed"
                    db.commit()
                    return
    if not issue.doc_commit_sha and commit_has_issue_trailer(worktree, tip, issue.id):
        # could be doc commit (first trailer commit)
        issue.doc_commit_sha = tip
        if issue.codegen_phase in {"none", "worktree_ready"}:
            issue.codegen_phase = "doc_committed"
            db.commit()


def _ensure_worktree(
    db: Session,
    *,
    issue: Issue,
    repo: Repository,
    worktree: Path,
    branch: str,
) -> None:
    run_git(["fetch", "origin"], cwd=repo.local_path)
    owned = bool(issue.base_commit_sha or issue.doc_commit_sha or issue.code_commit_sha)
    remote_exists = branch_exists_remote(repo.local_path, branch)
    local_exists = branch_exists_local(repo.local_path, branch)

    if (remote_exists or local_exists) and not owned and not worktree.exists():
        raise AgentError(f"分支 {branch} 已存在且无法证明属于本 Issue，拒绝复用")

    worktree.parent.mkdir(parents=True, exist_ok=True)
    if worktree.exists():
        issue.worktree_path = str(worktree)
        if not issue.base_commit_sha:
            issue.base_commit_sha = rev_parse(worktree, "HEAD")
        if issue.codegen_phase in {"none", ""}:
            issue.codegen_phase = "worktree_ready"
        db.commit()
        return

    start_ref = f"origin/{repo.default_branch}"
    if owned and remote_exists:
        start_ref = f"origin/{branch}"
    elif owned and local_exists:
        start_ref = branch

    run_git(
        ["worktree", "add", "-B", branch, str(worktree), start_ref],
        cwd=repo.local_path,
    )
    issue.worktree_path = str(worktree)
    if not issue.base_commit_sha:
        issue.base_commit_sha = rev_parse(worktree, "HEAD")
    if issue.codegen_phase in {"none", ""}:
        issue.codegen_phase = "worktree_ready"
    db.commit()


def _phase_commit_doc(db: Session, issue: Issue, worktree: Path, settings) -> None:
    assert issue.design_doc_path and issue.design_doc_text
    doc_path = worktree / issue.design_doc_path
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(issue.design_doc_text, encoding="utf-8")
    run_git(["add", "--", issue.design_doc_path], cwd=worktree)
    if is_clean(worktree):
        # already committed
        head = rev_parse(worktree, "HEAD")
        if commit_has_issue_trailer(worktree, head, issue.id):
            issue.doc_commit_sha = head
            issue.codegen_phase = "doc_committed"
            db.commit()
            return
    msg = (
        f"docs: design for #{issue.number}\n\n"
        f"{ISSUE_TRAILER}: {issue.id}"
    )
    sha = _git_commit(
        worktree,
        message=msg,
        author_name=settings.git_author_name,
        author_email=settings.git_author_email,
    )
    issue.doc_commit_sha = sha
    issue.codegen_phase = "doc_committed"
    db.commit()


def _phase_run_agent(db: Session, issue: Issue, job: Job, worktree: Path, settings) -> None:
    assert issue.doc_commit_sha
    head = rev_parse(worktree, "HEAD")
    if head != issue.doc_commit_sha or not is_clean(worktree):
        # retry after agent interrupt: reset to doc commit
        reset_hard(worktree, issue.doc_commit_sha)
    if rev_parse(worktree, "HEAD") != issue.doc_commit_sha:
        raise AgentError("无法回到 doc_commit_sha")

    issue.codegen_phase = "agent_running"
    db.commit()

    agent = job.agent or read_agent()
    if not agent:
        raise AgentError("未选代理")
    repo = db.get(Repository, issue.repository_id)
    doc_dir = repo.doc_dir if repo is not None else "docs"
    foundation = read_foundation_from_worktree(worktree, doc_dir=doc_dir)
    prompt = codegen_prompt(
        design_doc_path=issue.design_doc_path or "",
        design_doc_text=issue.design_doc_text or "",
        foundation=foundation,
    )
    log_path = Path(job.log_path) if job.log_path else PROJECT_ROOT / "logs" / "jobs" / f"{job.id}.log"
    env_extra: dict[str, str] | None = None
    test_db_job_id: int | None = None
    log_preamble = ""
    if settings.agent_test_db_enabled:
        try:
            created = create_job_database(settings.database_url, job.id)
            test_db_job_id = job.id
            env_extra = agent_env_for_test_db(created.url)
            log_preamble = f"# agent test database: {created.name}\n"
        except AgentTestDbError as exc:
            log_preamble = (
                f"# agent test database unavailable ({exc}); "
                "running without DATABASE_URL (pytest against prod blocked)\n"
            )
            logger.warning(f"agent test db create failed for job {job.id}: {exc}")
    try:
        code = run_agent(
            agent,
            prompt,
            cwd=worktree,
            timeout_sec=settings.code_timeout_sec,
            log_path=log_path,
            on_progress=_agent_progress(db, job, issue, log_path),
            env_extra=env_extra,
            log_preamble=log_preamble or None,
        )
    finally:
        if test_db_job_id is not None:
            drop_job_database(settings.database_url, test_db_job_id)
    job.log_excerpt = read_log_excerpt(log_path)
    job.exit_code = code
    db.commit()
    if code != 0:
        raise AgentError(f"代理退出码 {code}", exit_code=code)

    porcelain = run_git(["status", "--porcelain"], cwd=worktree)
    if not porcelain.strip():
        raise AgentError("代理未产生代码改动")

    sensitive_names = {".env", "id_rsa", "id_ed25519", "credentials.json"}
    for ln in porcelain.splitlines():
        path = ln[3:].strip() if len(ln) > 3 else ""
        name = Path(path).name
        if name in sensitive_names or path.endswith(".pem") or "credentials" in name.lower():
            raise AgentError(f"拒绝敏感路径: {path}")
        if issue.design_doc_path and (
            path == issue.design_doc_path or path.endswith("/" + issue.design_doc_path)
        ):
            raise AgentError("不允许再次修改设计文档")

    # design doc content must still match
    doc_file = worktree / (issue.design_doc_path or "")
    if not doc_file.exists() or doc_file.read_text(encoding="utf-8") != issue.design_doc_text:
        raise AgentError("设计文档内容被篡改")

    issue.codegen_phase = "changes_validated"
    db.commit()


def _phase_commit_code(db: Session, issue: Issue, worktree: Path, settings) -> None:
    # recover: code commit already present
    head = rev_parse(worktree, "HEAD")
    if (
        issue.doc_commit_sha
        and head != issue.doc_commit_sha
        and commit_has_issue_trailer(worktree, head, issue.id)
        and parent_sha(worktree, head) == issue.doc_commit_sha
    ):
        issue.code_commit_sha = head
        issue.codegen_phase = "code_committed"
        db.commit()
        return

    porcelain = run_git(["status", "--porcelain"], cwd=worktree)
    if not porcelain.strip() and issue.code_commit_sha:
        issue.codegen_phase = "code_committed"
        db.commit()
        return
    if not porcelain.strip():
        raise AgentError("无代码改动可提交")

    run_git(["add", "-A"], cwd=worktree)
    msg = (
        f"feat: #{issue.number} {issue.title}\n\n"
        f"{ISSUE_TRAILER}: {issue.id}"
    )
    sha = _git_commit(
        worktree,
        message=msg,
        author_name=settings.git_author_name,
        author_email=settings.git_author_email,
    )
    issue.code_commit_sha = sha
    issue.codegen_phase = "code_committed"
    db.commit()


def _phase_push(db: Session, issue: Issue, worktree: Path, branch: str) -> None:
    assert issue.code_commit_sha
    head = rev_parse(worktree, "HEAD")
    if head != issue.code_commit_sha:
        # maybe already pushed and checked out differently — require match
        if commit_has_issue_trailer(worktree, head, issue.id):
            issue.code_commit_sha = head
            db.commit()
        else:
            raise AgentError("HEAD 与 code_commit_sha 不一致")
    run_git(["push", "-u", "origin", f"HEAD:refs/heads/{branch}"], cwd=worktree)
    issue.codegen_phase = "pushed"
    issue.status = "generated"
    issue.failed_action = None
    issue.last_error = None
    db.commit()


def run_generate_code(db: Session, job: Job) -> None:
    settings = get_settings()
    issue = db.get(Issue, job.issue_id)
    repo = db.get(Repository, job.repository_id)
    assert issue and repo and repo.local_path and issue.design_doc_text and issue.design_doc_path

    if issue.github_state != "open":
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return

    agent = read_agent()
    if not agent:
        _fail_issue(db, issue, job, action="generate_code", error="未选代理")
        return
    job.agent = agent
    issue.status = "generating"
    issue.branch_name = issue.branch_name or f"issue/{issue.number}"
    db.commit()

    branch = issue.branch_name
    worktree = _codegen_worktree_path(settings, repo, issue)
    log_path = PROJECT_ROOT / "logs" / "jobs" / f"{job.id}.log"
    job.log_path = str(log_path)
    db.commit()

    try:
        if worktree.exists():
            _recover_codegen_phase_from_git(db, issue, worktree)
            db.refresh(issue)

        phase = issue.codegen_phase or "none"

        if phase in {"none", "worktree_ready"}:
            if phase == "none":
                _ensure_worktree(db, issue=issue, repo=repo, worktree=worktree, branch=branch)
                db.refresh(issue)
            elif not worktree.exists():
                _ensure_worktree(db, issue=issue, repo=repo, worktree=worktree, branch=branch)
                db.refresh(issue)
            phase = issue.codegen_phase or "worktree_ready"

        if phase == "worktree_ready":
            _phase_commit_doc(db, issue, worktree, settings)
            db.refresh(issue)
            phase = issue.codegen_phase

        if phase in {"doc_committed", "agent_running"}:
            _phase_run_agent(db, issue, job, worktree, settings)
            db.refresh(issue)
            phase = issue.codegen_phase

        if phase == "changes_validated":
            _phase_commit_code(db, issue, worktree, settings)
            db.refresh(issue)
            phase = issue.codegen_phase

        if phase == "code_committed":
            _phase_push(db, issue, worktree, branch)
            db.refresh(issue)
            phase = issue.codegen_phase

        if phase == "pushed":
            issue.status = "generated"
            issue.failed_action = None
            issue.last_error = None
            job.status = "succeeded"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="create_pr")
            return

        if phase == "pr_opened":
            issue.status = "pr_opened"
            job.status = "succeeded"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        # if we fell through unexpectedly
        if issue.status == "generated" or phase == "pushed":
            job.status = "succeeded"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        else:
            raise AgentError(f"未知或未完成阶段: {phase}")
    except (AgentError, GitError) as exc:
        job.log_excerpt = read_log_excerpt(log_path)
        # keep agent_running on agent failure so retry resets to doc sha
        if issue.codegen_phase == "agent_running" and "代理" in str(exc):
            pass
        _fail_issue(db, issue, job, action="generate_code", error=str(exc))


def execute_job(db: Session, job: Job) -> None:
    issue = db.get(Issue, job.issue_id)
    if issue is None or issue.github_state != "open":
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        job.error = "Issue not open"
        db.commit()
        return
    if job.action == "write_doc":
        run_write_doc(db, job)
    elif job.action == "generate_code":
        run_generate_code(db, job)
    elif job.action == "create_pr":
        run_create_pr(db, job)
    else:
        _fail_issue(db, issue, job, action=job.action, error="unknown action")
