from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import (
    COOKIE_NAME,
    create_access_token,
    csrf_token_for_jti,
    decode_access_token,
)
from app.crud import company as company_crud
from app.crud import design_feedback as feedback_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.crud import user as user_crud
from app.services.design_review import doc_sha256, parse_pending_items
from app.tasks.jobs import run_generate_code, run_revise_doc
from tests.conftest_git import init_bare_and_clone


def _login(client: TestClient, db: Session) -> str:
    user_crud.ensure_admin_user(db)
    token = create_access_token("admin")
    client.cookies.set(COOKIE_NAME, token)
    return csrf_token_for_jti(decode_access_token(token)["jti"])


def _seed(
    db: Session,
    *,
    number: int = 20,
    status: str = "pending_codegen",
    text: str = "# 设计\n\n## 7. 待确认\n\n- 第一项\n- 第二项\n",
    local_path: Path | None = None,
    number_offset: int = 0,
):
    company = company_crud.upsert_from_github(
        db,
        github_account_id=7000 + number + number_offset,
        account_type="Organization",
        login=f"acme{number}{number_offset}",
        name="Acme",
        description=None,
        avatar_url=None,
        html_url=None,
    )
    repo = repository_crud.upsert_from_github(
        db,
        company_id=company.id,
        github_repo_id=8000 + number + number_offset,
        name="demo",
        github_full_name=f"acme{number}{number_offset}/demo",
        description=None,
        html_url="https://github.com/acme/demo",
        default_branch="main",
        private=False,
    )
    if local_path is not None:
        repo.local_path = str(local_path)
    repo.doc_dir = "docs"
    db.commit()
    issue = issue_crud.upsert_from_webhook(
        db,
        repository_id=repo.id,
        github_issue_id=9000 + number + number_offset,
        number=number,
        title="设计审阅",
        body="details",
        html_url=f"https://github.com/acme/demo/issues/{number}",
        author_login="dev",
        github_state="open",
        label_names=["功能迭代"],
        github_updated_at=datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc),
        action="opened",
    )
    issue.kind = "feature"
    issue.status = status
    if text:
        issue.iteration_no = 1
        issue.design_doc_path = f"docs/v0001-{number}/design.md"
        issue.design_doc_text = text
    db.commit()
    db.refresh(issue)
    return repo, issue


def _feedback_rows(db: Session, issue_id: int) -> list:
    return list(
        feedback_crud.list_history(db, issue_id, limit=100)
    )


def test_parse_pending_numbered_list_and_headings() -> None:
    numbered = parse_pending_items(
        "# 文档\n\n## 7. 待确认\n\n1. 第一条\n2. 第二条\n\n## 下一节\n"
    )
    assert numbered.section_found is True
    assert numbered.structured is True
    assert [item.title for item in numbered.items] == ["第一条", "第二条"]

    headings = parse_pending_items(
        "# 文档\n\n## 待确认\n\n### **子项 A**\n\n说明\n\n### [子项 B](https://example.com)\n"
    )
    assert headings.structured is True
    assert [item.title for item in headings.items] == ["子项 A", "子项 B"]
    assert headings.items[0].key != headings.items[1].key


def test_parse_pending_ignores_fenced_code_and_degrades() -> None:
    fenced = parse_pending_items(
        "# 文档\n\n```markdown\n## 待确认\n- 不应识别\n```\n\n正文。\n"
    )
    assert fenced.section_found is False
    assert fenced.reason == "section_missing"

    empty = parse_pending_items("# 文档\n\n## 待确认\n\n只有说明文字。\n")
    assert empty.structured is False
    assert empty.reason == "section_empty"
    assert empty.needs_read_confirmation is True

    too_many = parse_pending_items(
        "## 待确认\n\n" + "\n".join(f"- 项 {i}" for i in range(51)) + "\n"
    )
    assert too_many.structured is False
    assert too_many.reason == "too_many"


def test_parse_duplicate_titles_get_distinct_keys() -> None:
    result = parse_pending_items("## 待确认\n\n- 同名\n- 同名\n")
    assert len(result.items) == 2
    assert len({item.key for item in result.items}) == 2


def test_approve_requires_pending_decisions_and_records_audit(
    client: TestClient, db: Session
) -> None:
    csrf = _login(client, db)
    repo, issue = _seed(db, number=21)
    parse = parse_pending_items(issue.design_doc_text)
    current = doc_sha256(issue.design_doc_text)

    resp = client.post(
        f"/issues/{issue.id}/design/approve",
        data={"csrf_token": csrf, "doc_sha256": current},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash=error" in resp.headers["location"]
    db.refresh(issue)
    assert issue.doc_approved_at is None

    first, second = parse.items
    resp = client.post(
        f"/issues/{issue.id}/design/pending/confirm",
        data={
            "csrf_token": csrf,
            "doc_sha256": current,
            "item_key": first.key,
            "body": "",
        },
        follow_redirects=False,
    )
    assert "flash=ok" in resp.headers["location"]
    # Repeat is idempotent and does not duplicate history.
    client.post(
        f"/issues/{issue.id}/design/pending/confirm",
        data={
            "csrf_token": csrf,
            "doc_sha256": current,
            "item_key": first.key,
            "body": "",
        },
        follow_redirects=False,
    )
    resp = client.post(
        f"/issues/{issue.id}/design/approve",
        data={"csrf_token": csrf, "doc_sha256": current},
        follow_redirects=False,
    )
    assert "flash=error" in resp.headers["location"]

    resp = client.post(
        f"/issues/{issue.id}/design/pending/reject",
        data={
            "csrf_token": csrf,
            "doc_sha256": current,
            "item_key": second.key,
            "body": "不需要",
        },
        follow_redirects=False,
    )
    assert "flash=ok" in resp.headers["location"]

    resp = client.post(
        f"/issues/{issue.id}/design/approve",
        data={"csrf_token": csrf, "doc_sha256": current},
        follow_redirects=False,
    )
    assert "flash=ok" in resp.headers["location"]
    db.refresh(issue)
    assert issue.doc_approved_at is not None
    history = _feedback_rows(db, issue.id)
    assert [row.kind for row in history].count("approve") == 1
    assert [row.kind for row in history].count("pending_confirm") == 0

    listing = client.get(f"/repos/{repo.id}/issues?github_state=open")
    assert "已批准" in listing.text

    resp = client.post(
        f"/issues/{issue.id}/design/unapprove",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert "flash=ok" in resp.headers["location"]
    db.refresh(issue)
    assert issue.doc_approved_at is None
    assert [row.kind for row in _feedback_rows(db, issue.id)].count("unapprove") == 1


def test_approve_unstructured_requires_read_confirmation(
    client: TestClient, db: Session
) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db, number=22, text="# 设计\n\n没有待确认。\n")
    current = doc_sha256(issue.design_doc_text)

    resp = client.post(
        f"/issues/{issue.id}/design/approve",
        data={"csrf_token": csrf, "doc_sha256": current},
        follow_redirects=False,
    )
    assert "flash=error" in resp.headers["location"]
    db.refresh(issue)
    assert issue.doc_approved_at is None

    resp = client.post(
        f"/issues/{issue.id}/design/approve",
        data={"csrf_token": csrf, "doc_sha256": current, "read_confirmed": "1"},
        follow_redirects=False,
    )
    assert "flash=ok" in resp.headers["location"]
    db.refresh(issue)
    assert issue.doc_approved_at is not None


def test_feedback_comment_and_revise_enqueue_same_transaction(
    client: TestClient, db: Session, tmp_path: Path, monkeypatch
) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db, number=23, local_path=tmp_path)
    monkeypatch.setattr("app.api.v1.issues.read_agent", lambda: "claude")
    current = doc_sha256(issue.design_doc_text)

    resp = client.post(
        f"/issues/{issue.id}/design/feedback",
        data={
            "csrf_token": csrf,
            "doc_sha256": current,
            "intent": "comment",
            "body": "请补充验收标准",
        },
        follow_redirects=False,
    )
    assert "flash=ok" in resp.headers["location"]
    comments = feedback_crud.unresolved_comments(db, issue.id)
    assert len(comments) == 1
    assert comments[0].kind == "human_comment"
    assert comments[0].job_id is None
    assert not job_crud.has_active_for_issue(db, issue.id)

    resp = client.post(
        f"/issues/{issue.id}/design/feedback",
        data={
            "csrf_token": csrf,
            "doc_sha256": current,
            "intent": "revise",
            "body": "按意见修订",
        },
        follow_redirects=False,
    )
    assert "flash=ok" in resp.headers["location"]
    db.refresh(issue)
    unresolved = feedback_crud.unresolved_comments(db, issue.id)
    request = [row for row in unresolved if row.kind == "revise_request"][0]
    assert request.job_id is not None
    job = job_crud.get(db, request.job_id)
    assert job is not None
    assert job.action == "revise_doc"
    assert job.status == "queued"


def test_feedback_revise_requires_path_agent_and_no_active_job(
    client: TestClient, db: Session, monkeypatch
) -> None:
    csrf = _login(client, db)
    repo, issue = _seed(db, number=24)
    current = doc_sha256(issue.design_doc_text)
    data = {
        "csrf_token": csrf,
        "doc_sha256": current,
        "intent": "revise",
        "body": "改",
    }
    resp = client.post(
        f"/issues/{issue.id}/design/feedback", data=data, follow_redirects=False
    )
    assert "路径未填" in unquote(resp.headers["location"])

    repo.local_path = "/tmp/fake"
    db.commit()
    resp = client.post(
        f"/issues/{issue.id}/design/feedback", data=data, follow_redirects=False
    )
    assert "未选代理" in unquote(resp.headers["location"])

    monkeypatch.setattr("app.api.v1.issues.read_agent", lambda: "claude")
    job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="write_doc")
    resp = client.post(
        f"/issues/{issue.id}/design/feedback", data=data, follow_redirects=False
    )
    assert "进行中" in unquote(resp.headers["location"])


def test_manual_edit_saves_clears_approval_and_ignores_empty(
    client: TestClient, db: Session
) -> None:
    csrf = _login(client, db)
    repo, issue = _seed(db, number=25)
    issue.doc_approved_at = datetime.now(timezone.utc)
    db.commit()
    old_path = issue.design_doc_path
    old_iteration = issue.iteration_no

    resp = client.get(f"/issues/{issue.id}/design/edit", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/issues/{issue.id}?edit=1#design-doc"

    resp = client.get(f"/issues/{issue.id}?edit=1")
    assert resp.status_code == 200
    assert "设计文档 Markdown" in resp.text
    assert 'id="design_doc_text"' in resp.text
    assert 'name="design_doc_text"' in resp.text
    assert 'maxlength="262144"' in resp.text
    assert "保存" in resp.text
    assert "取消" in resp.text
    assert issue.design_doc_text.splitlines()[0] in resp.text

    resp = client.get(f"/issues/{issue.id}")
    assert f'href="/issues/{issue.id}?edit=1#design-doc"' in resp.text
    assert 'id="design_doc_text"' not in resp.text

    resp = client.post(
        f"/issues/{issue.id}/design/edit",
        data={"csrf_token": csrf, "design_doc_text": "# 新文档\n\n更新内容\n"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(issue)
    assert issue.design_doc_text == "# 新文档\n\n更新内容\n"
    assert issue.doc_approved_at is None
    assert issue.design_doc_path == old_path
    assert issue.iteration_no == old_iteration
    assert [row.kind for row in _feedback_rows(db, issue.id)] == ["human_edit"]

    resp = client.post(
        f"/issues/{issue.id}/design/edit",
        data={"csrf_token": csrf, "design_doc_text": "   "},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "设计文档不能为空" in resp.text
    assert 'aria-invalid="true"' in resp.text
    assert "textarea-error" in resp.text
    db.refresh(issue)
    assert issue.design_doc_text == "# 新文档\n\n更新内容\n"

    detail = client.get(f"/issues/{issue.id}")
    assert "<h3>新文档</h3>" in detail.text


def test_manual_edit_rejects_overlong_document(
    client: TestClient, db: Session
) -> None:
    from app.services.design_review import MAX_DESIGN_DOC_CHARS

    csrf = _login(client, db)
    _repo, issue = _seed(db, number=35)
    old_text = issue.design_doc_text
    resp = client.post(
        f"/issues/{issue.id}/design/edit",
        data={
            "csrf_token": csrf,
            "design_doc_text": "x" * (MAX_DESIGN_DOC_CHARS + 1),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "设计文档不能超过" in resp.text
    db.refresh(issue)
    assert issue.design_doc_text == old_text


def test_manual_edit_rejected_with_active_job_or_other_status(
    client: TestClient, db: Session
) -> None:
    csrf = _login(client, db)
    repo, issue = _seed(db, number=26)
    job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action="write_doc")
    for url in (
        f"/issues/{issue.id}/design/edit",
        f"/issues/{issue.id}?edit=1",
    ):
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 303
        assert "进行中" in unquote(resp.headers["location"])
    resp = client.post(
        f"/issues/{issue.id}/design/edit",
        data={"csrf_token": csrf, "design_doc_text": "# 改"},
        follow_redirects=False,
    )
    assert resp.status_code == 409
    assert "进行中" in resp.text
    db.refresh(issue)
    assert issue.design_doc_text.startswith("# 设计")

    issue.status = "failed"
    issue.failed_action = "generate_code"
    db.commit()
    resp = client.get(f"/issues/{issue.id}?edit=1", follow_redirects=False)
    assert resp.status_code == 303
    assert "状态不允许" in unquote(resp.headers["location"])
    resp = client.post(
        f"/issues/{issue.id}/design/edit",
        data={"csrf_token": csrf, "design_doc_text": "# 改"},
        follow_redirects=False,
    )
    assert resp.status_code == 409


def test_design_edit_availability_matrix(
    client: TestClient, db: Session
) -> None:
    _login(client, db)
    _repo, issue = _seed(db, number=36)
    url = f"/issues/{issue.id}?edit=1"

    for status in ("generating", "generated", "pr_opened", "drafting"):
        issue.status = status
        db.commit()
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 303, status

    for failed_action in ("write_doc", "revise_doc"):
        issue.status = "failed"
        issue.failed_action = failed_action
        issue.codegen_phase = "none"
        db.commit()
        resp = client.get(url)
        assert resp.status_code == 200, failed_action

    issue.failed_action = "generate_code"
    db.commit()
    assert client.get(url, follow_redirects=False).status_code == 303

    issue.status = "pending_codegen"
    issue.failed_action = None
    issue.codegen_phase = "worktree_ready"
    db.commit()
    resp = client.get(url, follow_redirects=False)
    assert resp.status_code == 303
    assert "生成代码阶段" in unquote(resp.headers["location"])

    issue.codegen_phase = "none"
    issue.design_doc_text = "   "
    db.commit()
    resp = client.get(url, follow_redirects=False)
    assert resp.status_code == 303
    assert "为空" in unquote(resp.headers["location"])


def test_manual_edit_allowed_after_write_doc_failure(
    client: TestClient, db: Session
) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db, number=37, status="failed")
    issue.failed_action = "write_doc"
    issue.doc_approved_at = datetime.now(timezone.utc)
    db.commit()

    resp = client.post(
        f"/issues/{issue.id}/design/edit",
        data={"csrf_token": csrf, "design_doc_text": "# 人工修正\n"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(issue)
    assert issue.design_doc_text == "# 人工修正\n"
    assert issue.status == "failed"
    assert issue.failed_action == "write_doc"
    assert issue.doc_approved_at is None

    issue.codegen_phase = "worktree_ready"
    db.commit()
    resp = client.post(
        f"/issues/{issue.id}/design/edit",
        data={"csrf_token": csrf, "design_doc_text": "# 不应写入\n"},
        follow_redirects=False,
    )
    assert resp.status_code == 409
    assert "生成代码阶段" in resp.text
    db.refresh(issue)
    assert issue.design_doc_text == "# 人工修正\n"


def test_manual_edit_still_sanitizes_html(client: TestClient, db: Session) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db, number=27, text="# 旧")
    resp = client.post(
        f"/issues/{issue.id}/design/edit",
        data={
            "csrf_token": csrf,
            "design_doc_text": (
                "# 安全\n\n<script>alert('xss-doc')</script>"
                "[坏链接](javascript:alert(1))\n\n正常段落\n"
            ),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    detail = client.get(f"/issues/{issue.id}")
    assert "xss-doc" not in detail.text
    assert "javascript:" not in detail.text
    assert "正常段落" in detail.text


def test_generate_enqueue_requires_approval(client: TestClient, db: Session, tmp_path, monkeypatch) -> None:
    csrf = _login(client, db)
    repo, issue = _seed(db, number=28, local_path=tmp_path)
    monkeypatch.setattr("app.api.v1.issues.read_agent", lambda: "claude")
    monkeypatch.setattr("app.services.actions.read_agent", lambda: "claude")

    resp = client.post(
        f"/issues/{issue.id}/enqueue/generate_code",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert "请先批准设计文档" in unquote(resp.headers["location"])
    assert not job_crud.has_active_for_issue(db, issue.id)

    issue.doc_approved_at = datetime.now(timezone.utc)
    db.commit()
    resp = client.post(
        f"/issues/{issue.id}/enqueue/generate_code",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert "flash=ok" in resp.headers["location"]
    assert job_crud.has_active_for_issue(db, issue.id)


def test_worker_cancels_unapproved_generate_code(db: Session, tmp_path: Path) -> None:
    _repo, issue = _seed(db, number=29, local_path=tmp_path)
    job = job_crud.enqueue(
        db, issue_id=issue.id, repository_id=issue.repository_id, action="generate_code"
    )
    job.status = "running"
    db.commit()

    run_generate_code(db, job)
    db.refresh(issue)
    db.refresh(job)
    assert job.status == "cancelled"
    assert job.error == "设计文档未批准"
    assert issue.status == "pending_codegen"
    assert issue.doc_approved_at is None


def _revise_settings(tmp_path: Path, monkeypatch):
    wt = tmp_path / "worktrees"
    wt.mkdir(exist_ok=True)
    monkeypatch.setattr(
        "app.tasks.jobs.get_settings",
        lambda: type(
            "S",
            (),
            {
                "worktree_root": wt,
                "doc_timeout_sec": 30,
                "git_author_name": "t",
                "git_author_email": "t@t",
            },
        )(),
    )
    return wt


def test_revise_doc_success_writes_same_path_and_resolves_feedback(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    _bare, clone = init_bare_and_clone(tmp_path / "revise")
    wt = _revise_settings(tmp_path / "revise", monkeypatch)
    monkeypatch.setattr("app.tasks.jobs.read_agent", lambda: "claude")
    user = user_crud.ensure_admin_user(db)
    _repo, issue = _seed(db, number=30, local_path=clone, text="# 旧文档\n\n原文\n")
    issue.doc_approved_at = datetime.now(timezone.utc)
    db.commit()
    feedback = feedback_crud.create(
        db,
        issue_id=issue.id,
        author_user_id=user.id,
        author_username=user.username,
        kind=feedback_crud.REVISE_REQUEST,
        body="补充验收",
        doc_sha256=doc_sha256(issue.design_doc_text),
    )
    old_path = issue.design_doc_path
    old_iteration = issue.iteration_no
    job = job_crud.enqueue(
        db, issue_id=issue.id, repository_id=issue.repository_id, action="revise_doc"
    )
    job.status = "running"
    db.commit()

    def fake_agent(agent, prompt, *, cwd, timeout_sec, log_path, on_progress=None):
        path = Path(cwd) / old_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 新文档\n\n已补充验收\n", encoding="utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok\n", encoding="utf-8")
        if on_progress:
            on_progress()
        return 0

    monkeypatch.setattr("app.tasks.jobs.run_agent", fake_agent)
    run_revise_doc(db, job)
    db.refresh(issue)
    db.refresh(job)
    db.refresh(feedback)
    assert job.status == "succeeded"
    assert issue.status == "pending_codegen"
    assert issue.failed_action is None
    assert issue.design_doc_text == "# 新文档\n\n已补充验收\n"
    assert issue.design_doc_path == old_path
    assert issue.iteration_no == old_iteration
    assert issue.doc_approved_at is None
    assert feedback.resolved_at is not None
    assert feedback.job_id == job.id
    assert not (wt / "revise-doc" / str(job.id)).exists()


def test_revise_doc_rejects_unchanged_text_and_keeps_approval(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    _bare, clone = init_bare_and_clone(tmp_path / "revise-fail")
    _revise_settings(tmp_path / "revise-fail", monkeypatch)
    monkeypatch.setattr("app.tasks.jobs.read_agent", lambda: "claude")
    user = user_crud.ensure_admin_user(db)
    _repo, issue = _seed(db, number=31, local_path=clone, text="# 文档\n\n原文\n")
    approved_at = datetime.now(timezone.utc)
    issue.doc_approved_at = approved_at
    db.commit()
    feedback = feedback_crud.create(
        db,
        issue_id=issue.id,
        author_user_id=user.id,
        author_username=user.username,
        kind=feedback_crud.HUMAN_COMMENT,
        body="请修改",
        doc_sha256=doc_sha256(issue.design_doc_text),
    )
    old_text = issue.design_doc_text
    job = job_crud.enqueue(
        db, issue_id=issue.id, repository_id=issue.repository_id, action="revise_doc"
    )
    job.status = "running"
    db.commit()

    def fake_agent(agent, prompt, *, cwd, timeout_sec, log_path, on_progress=None):
        path = Path(cwd) / issue.design_doc_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(old_text, encoding="utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("same\n", encoding="utf-8")
        return 0

    monkeypatch.setattr("app.tasks.jobs.run_agent", fake_agent)
    run_revise_doc(db, job)
    db.refresh(issue)
    db.refresh(job)
    db.refresh(feedback)
    assert job.status == "failed"
    assert "修订结果与原文相同" in (job.error or "")
    assert issue.status == "failed"
    assert issue.failed_action == "revise_doc"
    assert issue.design_doc_text == old_text
    assert issue.doc_approved_at == approved_at
    assert feedback.resolved_at is None


def test_issue_metadata_update_keeps_approval(db: Session) -> None:
    _repo, issue = _seed(db, number=34)
    approved_at = datetime.now(timezone.utc)
    issue.doc_approved_at = approved_at
    db.commit()

    issue_crud.upsert_from_webhook(
        db,
        repository_id=issue.repository_id,
        github_issue_id=issue.github_issue_id,
        number=issue.number,
        title="更新后的标题",
        body="更新后的正文",
        html_url=issue.html_url,
        author_login=issue.author_login,
        github_state="open",
        label_names=["功能迭代"],
        github_updated_at=datetime(2026, 11, 13, 8, 0, tzinfo=timezone.utc),
        action="edited",
    )
    db.refresh(issue)
    assert issue.title == "更新后的标题"
    assert issue.doc_approved_at == approved_at


def test_list_and_actions_hide_generate_until_approved(
    client: TestClient, db: Session, tmp_path: Path, monkeypatch
) -> None:
    _login(client, db)
    repo, issue = _seed(db, number=33, local_path=tmp_path)
    monkeypatch.setattr("app.services.actions.read_agent", lambda: "claude")

    resp = client.get(f"/repos/{repo.id}/issues?github_state=open")
    text = resp.text
    assert "未批准" in text
    assert "审阅并批准" in text
    assert f"/issues/{issue.id}/enqueue/generate_code" not in text

    issue.doc_approved_at = datetime.now(timezone.utc)
    db.commit()
    resp = client.get(f"/repos/{repo.id}/issues?github_state=open")
    text = resp.text
    assert "已批准" in text
    assert f"/issues/{issue.id}/enqueue/generate_code" in text


def test_submit_confirmation_is_button_level_and_only_disables_submitter() -> None:
    root = Path(__file__).resolve().parents[1] / "app/templates"
    scripts = (root / "partials/app_scripts.html").read_text(encoding="utf-8")
    assert "event.submitter" in scripts
    assert "submitter.hasAttribute('data-gw-confirm')" in scripts
    assert "form.requestSubmit(submitter || undefined)" in scripts
    assert "form.querySelectorAll('button')" not in scripts

    detail = (root / "issue_detail.html").read_text(encoding="utf-8")
    assert 'data-gw-confirm' in detail
    assert 'name="intent" value="revise"' in detail
    assert 'id="read_confirmed"' in detail
    assert 'formaction="/issues/{{ issue.id }}/design/pending/reject"' in detail


def test_detail_has_review_card_edit_link_and_csrf(
    client: TestClient, db: Session, tmp_path: Path, monkeypatch
) -> None:
    csrf = _login(client, db)
    _repo, issue = _seed(db, number=32, local_path=tmp_path)
    monkeypatch.setattr("app.api.v1.issues.read_agent", lambda: "claude")
    resp = client.get(f"/issues/{issue.id}")
    text = resp.text
    assert 'id="design-review"' in text
    assert "审阅与批准" in text
    assert "批准设计文档" in text
    assert f'href="/issues/{issue.id}?edit=1#design-doc"' in text
    assert 'id="design-feedback-body"' in text
    assert "请代理修订" in text
    assert f'name="csrf_token" value="{csrf}"' in text
    assert 'name="doc_sha256"' in text
    assert "确认采纳" in text
    assert "驳回" in text
