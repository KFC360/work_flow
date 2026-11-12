from __future__ import annotations

import time
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
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.database.connect import get_db
from app.dependencies.auth import require_csrf, require_fragment_user, require_page_user
from app.models.user import User
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
    if action in {"write_doc", "generate_code"} and not repo.local_path:
        return fail("路径未填")
    if action in {"write_doc", "generate_code"} and not read_agent():
        return fail("未选代理")
    if action == "write_doc" and issue.status not in {"recorded", "pending_codegen", "failed"}:
        return fail("状态不允许编写文档")
    if action == "write_doc" and issue.status == "pending_codegen" and issue.codegen_phase != "none":
        return fail("代码阶段已开始，不能重写文档")
    if action == "generate_code" and issue.status not in {"pending_codegen", "failed"}:
        return fail("状态不允许生成代码")
    if action == "create_pr" and issue.status not in {"generated", "failed"}:
        return fail("状态不允许创建 PR")
    if action not in {"write_doc", "generate_code", "create_pr"}:
        return fail("未知动作")

    job_crud.enqueue(db, issue_id=issue.id, repository_id=repo.id, action=action)
    return RedirectResponse(f"/issues/{issue_id}?flash=ok&msg={quote('已入队')}", status_code=303)
