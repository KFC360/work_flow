from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import csrf_token_for_jti
from app.core.templating import build_templates
from app.crud import company as company_crud
from app.crud import design_feedback as feedback_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.database.connect import get_db
from app.dependencies.auth import require_csrf, require_fragment_user, require_page_user
from app.models.user import User
from app.services import design_review
from app.services.actions import KIND_LABELS, STATUS_LABELS, actions_for, display_status_label
from app.services.config_agent import read_agent
from app.services.foundation import foundation_relpath, read_foundation_from_origin
from app.services.github_api import GitHubAPIError, GitHubClient
from app.services.ingest import refresh_issue_from_github
from app.services import issue_sync
from app.services.issues import (
    KIND_FEATURE,
    KIND_SUPPORT,
    STATUS_RECORDED,
    STATUS_SUPPORT_OPEN,
    classify_labels,
)
from app.services.job_logs import read_job_log_tail, safe_job_log_path
from app.services.markdown_render import render_design_doc, render_issue_body
from app.services.worker_heartbeat import HeartbeatView, read_heartbeat

router = APIRouter(tags=["issues"])
templates = build_templates()
PAGE_SIZE = 50


def _ctx(user: User, **extra):
    jti = getattr(user, "_token_jti", "")
    base = {"user": user, "csrf_token": csrf_token_for_jti(jti) if jti else "", "nav": "companies"}
    base.update(extra)
    return base


def _issue_list_url(
    repo_id: int,
    *,
    kind: str | None,
    status: str | None,
    github_state: str | None,
    page: int,
    pr_state: str | None = None,
) -> str:
    params: list[tuple[str, str]] = []
    if kind:
        params.append(("kind", kind))
    if status:
        params.append(("status", status))
    if github_state:
        params.append(("github_state", github_state))
    if pr_state:
        params.append(("pr_state", pr_state))
    if page > 1:
        params.append(("page", str(page)))
    query = urlencode(params)
    return f"/repos/{repo_id}/issues" + (f"?{query}" if query else "")


def _log_context(latest):
    if latest is None:
        return "", False
    warning = bool(
        latest.log_path
        and safe_job_log_path(latest.log_path) is None
        and not latest.log_excerpt
    )
    if warning:
        return "", True
    return read_job_log_tail(latest.log_path) or (latest.log_excerpt or ""), False


def _worker_text(issue, heartbeat: HeartbeatView) -> str:
    if heartbeat.status == "idle":
        return "Worker 空闲"
    if heartbeat.status == "running":
        return "执行中（本 Issue）" if heartbeat.issue_id == issue.id else "执行中（其他 Issue）"
    return "无心跳，任务可能不会执行"


def _refresh_error_message(exc: Exception) -> str:
    if isinstance(exc, GitHubAPIError):
        if exc.status_code == 409:
            return "刷新失败：拉取到的 Issue 与本地记录不一致，未更新"
        if exc.status_code in (404, 410):
            return "刷新失败：GitHub 上找不到该 Issue，可能已删除或无权访问"
        if exc.status_code in (401, 403):
            return "刷新失败：GitHub 授权失败，请检查访问令牌"
        if exc.status_code == 429:
            return "刷新失败：GitHub 限流，请稍后再试"
    return "刷新失败：暂时无法连接 GitHub，请稍后重试"


def _safe_issue_list_next(repo_id: int, raw: str | None) -> str:
    """Keep the current list filters; drop stale flash params and reject redirects."""
    default = f"/repos/{repo_id}/issues"
    if not raw:
        return default
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc:
        return default
    prefix = f"/repos/{repo_id}/issues"
    if parts.path != prefix and not parts.path.startswith(prefix + "/"):
        return default
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key not in {"flash", "msg"}
        ]
    )
    return parts.path + (f"?{query}" if query else "")


def _try_sync_lock(db: Session, repo_id: int) -> bool:
    key = f"github_workflow:issue-sync:{repo_id}"
    return bool(
        db.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
            {"key": key},
        )
    )


def _sync_error_message(exc: Exception) -> str:
    if isinstance(exc, issue_sync.IssueSyncError):
        return f"同步失败：{exc}"
    if isinstance(exc, GitHubAPIError):
        if exc.status_code in (401, 403):
            return "同步失败：GitHub 授权失败，请检查访问令牌"
        if exc.status_code in (404, 410):
            return "同步失败：GitHub 上找不到该仓库，可能已改名或无权限；请先重新同步仓库"
        if exc.status_code == 429:
            return "同步失败：GitHub 限流，请稍后重试；未写入任何变更"
        return "同步失败：无法连接 GitHub，未写入任何变更"
    return "同步失败：无法连接 GitHub，未写入任何变更"


@router.get("/repos/{repo_id}/issues", response_class=HTMLResponse)
def issue_list(
    repo_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_page_user)],
    kind: str | None = None,
    status: str | None = None,
    github_state: str | None = "open",
    pr_state: str | None = None,
    page: int = 1,
):
    repo = repository_crud.get(db, repo_id)
    if repo is None:
        return templates.TemplateResponse(
            request, "404.html", _ctx(user, message="未找到仓库"), status_code=404
        )
    company = company_crud.get(db, repo.company_id)
    page = max(page, 1)
    gh = github_state if github_state != "" else None
    pr_filter = pr_state if pr_state not in ("", "all") else None
    issues = issue_crud.list_for_repo(
        db,
        repo_id,
        kind=kind or None,
        status=status or None,
        github_state=gh,
        pr_state=pr_filter,
        offset=(page - 1) * PAGE_SIZE,
        limit=PAGE_SIZE,
    )
    total = issue_crud.count_for_repo(
        db,
        repo_id,
        kind=kind or None,
        status=status or None,
        github_state=gh,
        pr_state=pr_filter,
    )
    rows = [
        {
            "issue": i,
            "kind_label": KIND_LABELS.get(i.kind, i.kind),
            "status_label": display_status_label(i),
            "actions": actions_for(db, i, repo),
        }
        for i in issues
    ]
    status_options = list(STATUS_LABELS.items())
    status_options.append((issue_crud.UNFINISHED_STATUS, "未结束"))
    if status and status not in {value for value, _ in status_options}:
        status_options.append((status, status))
    has_filters = bool(kind or status or pr_filter) or (
        github_state not in (None, "", "open")
    )
    return templates.TemplateResponse(
        request,
        "issues.html",
        _ctx(
            user,
            repo=repo,
            company=company,
            rows=rows,
            total=total,
            kind=kind or "",
            status=status or "",
            status_options=status_options,
            has_filters=has_filters,
            github_state=github_state if github_state is not None else "open",
            pr_state=pr_filter or "",
            page=page,
            pagination={
                "page": page,
                "has_prev": page > 1,
                "has_next": page * PAGE_SIZE < total,
                "prev_url": _issue_list_url(
                    repo_id,
                    kind=kind,
                    status=status,
                    github_state=github_state,
                    pr_state=pr_filter,
                    page=page - 1,
                ),
                "next_url": _issue_list_url(
                    repo_id,
                    kind=kind,
                    status=status,
                    github_state=github_state,
                    pr_state=pr_filter,
                    page=page + 1,
                ),
            },
            flash=request.query_params.get("flash"),
            msg=request.query_params.get("msg"),
            breadcrumbs=[
                ("公司", "/"),
                (company.name if company else "公司", f"/companies/{repo.company_id}"),
                (repo.github_full_name, f"/repos/{repo.id}"),
                ("Issue", None),
            ],
        ),
    )


def _redirect_with_flash(url: str, flash: str, msg: str) -> RedirectResponse:
    separator = "&" if "?" in url else "?"
    return RedirectResponse(
        f"{url}{separator}flash={flash}&msg={quote(msg)}",
        status_code=303,
    )


def _design_issue_or_404(request: Request, db: Session, issue_id: int, user: User):
    issue = issue_crud.get(db, issue_id)
    if issue is None or issue.deleted_at is not None:
        return None, templates.TemplateResponse(
            request, "404.html", _ctx(user, message="未找到 Issue"), status_code=404
        )
    return issue, None


def _design_block_reason(db: Session, issue) -> str | None:
    if issue.kind != "feature":
        return "只有功能迭代可以审阅设计文档"
    if issue.github_state != "open":
        return "Issue 已关闭，不能审阅设计文档"
    if issue.status != "pending_codegen":
        return "当前状态不允许审阅设计文档"
    if job_crud.has_active_for_issue(db, issue.id):
        return "有进行中的编写 / 修订任务，完成后可再审阅"
    if not (issue.design_doc_text or "").strip():
        return "设计文档不存在或为空"
    return None


def _design_redirect(issue_id: int, flash: str, msg: str) -> RedirectResponse:
    return _redirect_with_flash(f"/issues/{issue_id}", flash, msg)


def _design_review_context(db: Session, issue, repo) -> dict:
    text = issue.design_doc_text or ""
    doc_hash = design_review.doc_sha256(text)
    parse = design_review.parse_pending_items(text)
    decisions = feedback_crud.latest_decisions(db, issue.id, doc_hash)
    items = design_review.pending_items_view(parse, decisions)
    remaining = design_review.pending_remaining(parse, decisions)
    has_active = job_crud.has_active_for_issue(db, issue.id)
    review_visible = bool(
        text.strip() and issue.status == "pending_codegen" and issue.deleted_at is None
    )
    can_edit = bool(
        review_visible
        and not has_active
        and issue.kind == "feature"
        and issue.github_state == "open"
    )
    return {
        "review_visible": review_visible,
        "review_has_active": has_active,
        "review_can_edit": can_edit,
        "review_can_approve": bool(can_edit and not issue.doc_approved_at),
        "review_path_available": bool(repo.local_path),
        "review_agent_available": bool(read_agent()),
        "doc_sha256": doc_hash,
        "pending_parse": parse,
        "pending_items": items,
        "pending_remaining": remaining,
        "pending_all_done": bool(
            parse.structured and parse.items and remaining == 0
        ),
        "pending_needs_read_confirmation": parse.needs_read_confirmation,
        "pending_reason_label": parse.reason_label,
        "feedback_views": design_review.feedback_views(db, issue),
    }


def _stale_design_doc(issue) -> bool:
    return bool(
        issue.design_source_updated_at
        and issue.github_updated_at
        and issue.github_updated_at > issue.design_source_updated_at
    )


@router.post("/repos/{repo_id}/issues/sync")
def sync_repo_issues(
    repo_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
    next_url: Annotated[str, Form(alias="next")] = "",
):
    repo = repository_crud.get(db, repo_id)
    if repo is None:
        return templates.TemplateResponse(
            request, "404.html", _ctx(user, message="未找到仓库"), status_code=404
        )
    target = _safe_issue_list_next(repo_id, next_url)
    if not _try_sync_lock(db, repo.id):
        db.commit()
        return _redirect_with_flash(target, "error", "该仓库正在同步，请稍后再试")

    client = GitHubClient()
    try:
        result = issue_sync.sync_repository_issues(
            db,
            client,
            repo,
            deadline=time.monotonic() + issue_sync.SYNC_TIMEOUT_SECONDS,
        )
    except SQLAlchemyError:
        db.rollback()
        return _redirect_with_flash(target, "error", "同步失败：写入数据库失败，已回滚")
    except (issue_sync.IssueSyncError, GitHubAPIError, httpx.HTTPError) as exc:
        # These failures happen before the write phase, so there is nothing to
        # roll back; committing the empty transaction releases the advisory lock.
        db.commit()
        return _redirect_with_flash(target, "error", _sync_error_message(exc))
    finally:
        client.close()

    flash = "error" if result.failures else "ok"
    return _redirect_with_flash(target, flash, issue_sync.summary_text(result))


@router.get("/issues/{issue_id}", response_class=HTMLResponse)
def issue_detail(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_page_user)],
):
    issue = issue_crud.get(db, issue_id)
    if issue is None or issue.deleted_at is not None:
        return templates.TemplateResponse(
            request, "404.html", _ctx(user, message="未找到 Issue"), status_code=404
        )
    repo = repository_crud.get(db, issue.repository_id)
    assert repo is not None
    company = company_crud.get(db, repo.company_id)
    expected_kind, _ = classify_labels(list(issue.label_names or []))
    label_mismatch = expected_kind != issue.kind and issue.kind != "pending"
    stale_doc = bool(
        issue.design_source_updated_at
        and issue.github_updated_at
        and issue.github_updated_at > issue.design_source_updated_at
    )
    latest = job_crud.latest_for_issue(db, issue.id)
    foundation_missing = False
    if repo.local_path:
        try:
            foundation_missing = not read_foundation_from_origin(
                repo.local_path,
                default_branch=repo.default_branch,
                doc_dir=repo.doc_dir,
            ).exists
        except OSError:
            foundation_missing = True
    heartbeat = read_heartbeat()
    log_text, log_warning = _log_context(latest)
    worker_text = _worker_text(issue, heartbeat)
    issue_body_html = render_issue_body(issue.body)
    issue_has_body = bool(issue.body and issue.body.strip())
    design_doc_html = render_design_doc(issue.design_doc_text)
    has_design_doc = bool(
        issue.design_doc_path
        and issue.design_doc_text
        and issue.design_doc_text.strip()
    )
    review_context = _design_review_context(db, issue, repo)
    return templates.TemplateResponse(
        request,
        "issue_detail.html",
        _ctx(
            user,
            issue=issue,
            repo=repo,
            company=company,
            issue_body_html=issue_body_html,
            issue_has_body=issue_has_body,
            design_doc_html=design_doc_html,
            has_design_doc=has_design_doc,
            actions=actions_for(db, issue, repo),
            kind_label=KIND_LABELS.get(issue.kind, issue.kind),
            status_label=STATUS_LABELS.get(issue.status, issue.status),
            latest_job=latest,
            stale_doc=stale_doc,
            label_mismatch=label_mismatch,
            foundation_missing=foundation_missing,
            foundation_path=foundation_relpath(repo.doc_dir),
            worker_status=heartbeat.status,
            worker_text=worker_text,
            worker_label=worker_text,
            worker_related=heartbeat.status == "running" and heartbeat.issue_id == issue.id,
            worker_updated_at=heartbeat.updated_at if heartbeat.status in {"idle", "running"} else None,
            log_text=log_text,
            log_warning=log_warning,
            polling=issue.status in {"drafting", "generating"},
            flash=request.query_params.get("flash"),
            msg=request.query_params.get("msg"),
            breadcrumbs=[
                ("公司", "/"),
                (company.name if company else "公司", f"/companies/{repo.company_id}"),
                (repo.github_full_name, f"/repos/{repo.id}"),
                (f"#{issue.number} {issue.title}", None),
            ],
            **review_context,
        ),
    )


@router.get("/issues/{issue_id}/status-fragment", response_class=HTMLResponse)
def issue_status_fragment(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_fragment_user)],
):
    _ = user
    issue = issue_crud.get(db, issue_id)
    if issue is None or issue.deleted_at is not None:
        return HTMLResponse("not found", status_code=404)
    latest = job_crud.latest_for_issue(db, issue.id)
    heartbeat = read_heartbeat()
    log_text, log_warning = _log_context(latest)
    worker_text = _worker_text(issue, heartbeat)
    return templates.TemplateResponse(
        request,
        "partials/issue_live.html",
        {
            "issue": issue,
            "latest_job": latest,
            "worker_status": heartbeat.status,
            "worker_text": worker_text,
            "worker_label": worker_text,
            "log_text": log_text,
            "log_warning": log_warning,
            "polling": issue.status in {"drafting", "generating"},
        },
    )


@router.post("/issues/{issue_id}/refresh")
def refresh_issue(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
):
    issue = issue_crud.get(db, issue_id)
    if issue is None or issue.deleted_at is not None:
        return templates.TemplateResponse(
            request, "404.html", _ctx(user, message="未找到 Issue"), status_code=404
        )
    repo = repository_crud.get(db, issue.repository_id)
    if repo is None:
        return templates.TemplateResponse(
            request, "404.html", _ctx(user, message="未找到仓库"), status_code=404
        )

    client = GitHubClient()
    try:
        refresh_issue_from_github(db, client, issue, repo)
    except (GitHubAPIError, httpx.HTTPError, ValueError) as exc:
        return RedirectResponse(
            f"/issues/{issue_id}?flash=error&msg={quote(_refresh_error_message(exc))}",
            status_code=303,
        )
    finally:
        client.close()
    return RedirectResponse(
        f"/issues/{issue_id}?flash=ok&msg={quote('已刷新')}", status_code=303
    )


@router.post("/issues/{issue_id}/classify/{target}")
def classify_issue(
    issue_id: int,
    target: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
):
    _ = user
    issue = issue_crud.get(db, issue_id)
    if issue is None:
        return RedirectResponse("/", status_code=303)
    if issue.status not in {"pending_classify", "recorded", "support_open"}:
        return RedirectResponse(
            f"/issues/{issue_id}?flash=error&msg={quote('当前状态不可分类')}",
            status_code=303,
        )
    if job_crud.has_active_for_issue(db, issue.id):
        return RedirectResponse(
            f"/issues/{issue_id}?flash=error&msg={quote('已有排队任务')}",
            status_code=303,
        )
    if target == "feature":
        issue_crud.set_kind(db, issue, KIND_FEATURE, STATUS_RECORDED)
    elif target == "support":
        issue_crud.set_kind(db, issue, KIND_SUPPORT, STATUS_SUPPORT_OPEN)
    else:
        return RedirectResponse(
            f"/issues/{issue_id}?flash=error&msg={quote('未知类型')}",
            status_code=303,
        )
    return RedirectResponse(f"/issues/{issue_id}?flash=ok&msg={quote('已分类')}", status_code=303)


@router.post("/issues/{issue_id}/enqueue/{action}")
def enqueue_job(
    issue_id: int,
    action: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
):
    _ = user
    issue = issue_crud.get(db, issue_id)
    if issue is None:
        return RedirectResponse("/", status_code=303)
    repo = repository_crud.get(db, issue.repository_id)
    assert repo is not None

    def fail(msg: str):
        return RedirectResponse(
            f"/issues/{issue_id}?flash=error&msg={quote(msg)}",
            status_code=303,
        )

    if issue.github_state != "open" or issue.kind != "feature":
        return fail("状态不允许入队")
    if job_crud.has_active_for_issue(db, issue.id):
        return fail("已有排队或执行中任务")
    if action in {"write_doc", "generate_code", "revise_doc"} and not repo.local_path:
        return fail("路径未填")
    if action in {"write_doc", "generate_code", "revise_doc"} and not read_agent():
        return fail("未选代理")
    if action == "write_doc" and issue.status not in {"recorded", "pending_codegen", "failed"}:
        return fail("状态不允许编写文档")
    if action == "write_doc" and issue.status == "pending_codegen" and issue.codegen_phase != "none":
        return fail("代码阶段已开始，不能重写文档")
    if action == "generate_code" and issue.status not in {"pending_codegen", "failed"}:
        return fail("状态不允许生成代码")
    if action == "generate_code" and not issue.doc_approved_at:
        return fail("请先批准设计文档")
    if action == "revise_doc":
        if issue.status != "failed" or issue.failed_action != "revise_doc":
            return fail("状态不允许重试修订")
        if not feedback_crud.unresolved_comments(db, issue.id):
            return fail("没有待处理意见")
    if action == "create_pr" and issue.status not in {"generated", "failed"}:
        return fail("状态不允许创建 PR")
    if action not in {"write_doc", "generate_code", "revise_doc", "create_pr"}:
        return fail("未知动作")

    job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action=action)
    return RedirectResponse(f"/issues/{issue_id}?flash=ok&msg={quote('已入队')}", status_code=303)


@router.post("/issues/{issue_id}/design/approve")
def approve_design(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
    doc_sha256: Annotated[str, Form()] = "",
    read_confirmed: Annotated[str, Form()] = "",
):
    issue, error = _design_issue_or_404(request, db, issue_id, user)
    if error is not None:
        return error
    block = _design_block_reason(db, issue)
    if block:
        return _design_redirect(issue_id, "error", block)
    current_hash = design_review.doc_sha256(issue.design_doc_text)
    if doc_sha256 != current_hash:
        return _design_redirect(issue_id, "error", "文档已更新，请刷新后重试")
    if issue.doc_approved_at is not None:
        return _design_redirect(issue_id, "ok", "当前文档已批准")

    check = design_review.check_pending_approval(
        db,
        issue,
        doc_hash=current_hash,
        read_confirmed=read_confirmed == "1",
    )
    if not check.allowed:
        return _design_redirect(issue_id, "error", check.message)

    issue.doc_approved_at = datetime.now(timezone.utc)
    feedback_crud.create(
        db,
        issue_id=issue.id,
        author_user_id=user.id,
        author_username=user.username,
        kind=feedback_crud.APPROVE,
        body="已通读待确认" if check.parse.needs_read_confirmation else "",
        doc_sha256=current_hash,
        commit=False,
    )
    db.commit()
    return _design_redirect(issue_id, "ok", "已批准设计文档")


@router.post("/issues/{issue_id}/design/unapprove")
def unapprove_design(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
):
    issue, error = _design_issue_or_404(request, db, issue_id, user)
    if error is not None:
        return error
    block = _design_block_reason(db, issue)
    if block:
        return _design_redirect(issue_id, "error", block)
    if issue.doc_approved_at is None:
        return _design_redirect(issue_id, "ok", "当前文档未批准")

    current_hash = design_review.doc_sha256(issue.design_doc_text)
    issue.doc_approved_at = None
    feedback_crud.create(
        db,
        issue_id=issue.id,
        author_user_id=user.id,
        author_username=user.username,
        kind=feedback_crud.UNAPPROVE,
        doc_sha256=current_hash,
        commit=False,
    )
    db.commit()
    return _design_redirect(issue_id, "ok", "已取消批准")


@router.post("/issues/{issue_id}/design/feedback")
def design_feedback(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
    body: Annotated[str, Form()] = "",
    intent: Annotated[str, Form()] = "comment",
    doc_sha256: Annotated[str, Form()] = "",
):
    issue, error = _design_issue_or_404(request, db, issue_id, user)
    if error is not None:
        return error
    block = _design_block_reason(db, issue)
    if block:
        return _design_redirect(issue_id, "error", block)
    text = (body or "").strip()
    if not text:
        return _design_redirect(issue_id, "error", "请填写审阅意见")
    current_hash = design_review.doc_sha256(issue.design_doc_text)
    if doc_sha256 != current_hash:
        return _design_redirect(issue_id, "error", "文档已更新，请刷新后重试")
    if intent not in {"comment", "revise"}:
        return _design_redirect(issue_id, "error", "未知操作")

    if intent == "comment":
        feedback_crud.create(
            db,
            issue_id=issue.id,
            author_user_id=user.id,
            author_username=user.username,
            kind=feedback_crud.HUMAN_COMMENT,
            body=text,
            doc_sha256=current_hash,
        )
        return _design_redirect(issue_id, "ok", "意见已保存")

    repo = repository_crud.get(db, issue.repository_id)
    if repo is None or not repo.local_path:
        return _design_redirect(issue_id, "error", "路径未填")
    if not read_agent():
        return _design_redirect(issue_id, "error", "未选代理")

    try:
        feedback = feedback_crud.create(
            db,
            issue_id=issue.id,
            author_user_id=user.id,
            author_username=user.username,
            kind=feedback_crud.REVISE_REQUEST,
            body=text,
            doc_sha256=current_hash,
            commit=False,
        )
        job = job_crud.enqueue(
            db,
            issue_id=issue.id,
            repository_id=repo.id,
            action="revise_doc",
            commit=False,
        )
        feedback.job_id = job.id
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return _design_redirect(issue_id, "error", "入队失败，请稍后重试")
    return _design_redirect(issue_id, "ok", "已入队修订")


def _apply_pending_decision(
    *,
    decision: str,
    issue_id: int,
    request: Request,
    db: Session,
    user: User,
    doc_sha256: str,
    item_key: str,
    body: str,
) -> RedirectResponse:
    issue, error = _design_issue_or_404(request, db, issue_id, user)
    if error is not None:
        return error
    block = _design_block_reason(db, issue)
    if block:
        return _design_redirect(issue_id, "error", block)
    current_hash = design_review.doc_sha256(issue.design_doc_text)
    if doc_sha256 != current_hash:
        return _design_redirect(issue_id, "error", "文档已更新，请刷新后重试")
    parse = design_review.parse_pending_items(issue.design_doc_text)
    if not parse.structured or not parse.items:
        return _design_redirect(issue_id, "error", "当前文档没有可处理的待确认项")
    item = next((entry for entry in parse.items if entry.key == item_key), None)
    if item is None:
        return _design_redirect(issue_id, "error", "待确认项已变化，请刷新后重试")
    text = (body or "").strip()
    if decision == "reject" and not text:
        return _design_redirect(issue_id, "error", "驳回需要填写理由")

    kind = feedback_crud.PENDING_CONFIRM if decision == "confirm" else feedback_crud.PENDING_REJECT
    latest = feedback_crud.latest_decisions(db, issue.id, current_hash).get(item.key)
    if latest is not None and latest.kind == kind:
        return _design_redirect(issue_id, "ok", "已是该状态")
    feedback_crud.create(
        db,
        issue_id=issue.id,
        author_user_id=user.id,
        author_username=user.username,
        kind=kind,
        body=text,
        pending_item_key=item.key,
        pending_item_title=item.title,
        doc_sha256=current_hash,
    )
    message = "已确认" if decision == "confirm" else "已驳回"
    return _design_redirect(issue_id, "ok", message)


@router.post("/issues/{issue_id}/design/pending/confirm")
def confirm_pending_item(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
    doc_sha256: Annotated[str, Form()] = "",
    item_key: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
):
    return _apply_pending_decision(
        decision="confirm",
        issue_id=issue_id,
        request=request,
        db=db,
        user=user,
        doc_sha256=doc_sha256,
        item_key=item_key,
        body=body,
    )


@router.post("/issues/{issue_id}/design/pending/reject")
def reject_pending_item(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
    doc_sha256: Annotated[str, Form()] = "",
    item_key: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
):
    return _apply_pending_decision(
        decision="reject",
        issue_id=issue_id,
        request=request,
        db=db,
        user=user,
        doc_sha256=doc_sha256,
        item_key=item_key,
        body=body,
    )


@router.get("/issues/{issue_id}/design/edit", response_class=HTMLResponse)
def design_edit(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_page_user)],
):
    issue, error = _design_issue_or_404(request, db, issue_id, user)
    if error is not None:
        return error
    block = _design_block_reason(db, issue)
    if block:
        return _design_redirect(issue_id, "error", block)
    repo = repository_crud.get(db, issue.repository_id)
    assert repo is not None
    company = company_crud.get(db, repo.company_id)
    return templates.TemplateResponse(
        request,
        "design_edit.html",
        _ctx(
            user,
            issue=issue,
            repo=repo,
            company=company,
            doc_text=issue.design_doc_text or "",
            field_error=None,
            stale_doc=_stale_design_doc(issue),
            breadcrumbs=[
                ("公司", "/"),
                (company.name if company else "公司", f"/companies/{repo.company_id}"),
                (repo.github_full_name, f"/repos/{repo.id}"),
                (f"#{issue.number} {issue.title}", f"/issues/{issue.id}"),
                ("编辑设计文档", None),
            ],
        ),
    )


@router.post("/issues/{issue_id}/design/edit", response_class=HTMLResponse)
def save_design_edit(
    issue_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
    design_doc_text: Annotated[str, Form()] = "",
):
    issue, error = _design_issue_or_404(request, db, issue_id, user)
    if error is not None:
        return error
    block = _design_block_reason(db, issue)
    if block:
        return _design_redirect(issue_id, "error", block)
    repo = repository_crud.get(db, issue.repository_id)
    assert repo is not None
    company = company_crud.get(db, repo.company_id)
    if not (design_doc_text or "").strip():
        return templates.TemplateResponse(
            request,
            "design_edit.html",
            _ctx(
                user,
                issue=issue,
                repo=repo,
                company=company,
                doc_text=design_doc_text,
                field_error="设计文档不能为空",
                stale_doc=_stale_design_doc(issue),
                breadcrumbs=[
                    ("公司", "/"),
                    (company.name if company else "公司", f"/companies/{repo.company_id}"),
                    (repo.github_full_name, f"/repos/{repo.id}"),
                    (f"#{issue.number} {issue.title}", f"/issues/{issue.id}"),
                    ("编辑设计文档", None),
                ],
            ),
            status_code=200,
        )

    issue.design_doc_text = design_doc_text
    issue.doc_approved_at = None
    feedback_crud.create(
        db,
        issue_id=issue.id,
        author_user_id=user.id,
        author_username=user.username,
        kind=feedback_crud.HUMAN_EDIT,
        body=f"人工编辑保存（{len(design_doc_text)} 字符）",
        doc_sha256=design_review.doc_sha256(design_doc_text),
        commit=False,
    )
    db.commit()
    return _design_redirect(issue_id, "ok", "已保存，需重新批准")
