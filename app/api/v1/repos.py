from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import csrf_token_for_jti
from app.core.templating import build_templates
from app.crud import company as company_crud
from app.crud import issue as issue_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.database.connect import get_db
from app.dependencies.auth import require_csrf, require_page_user
from app.models.repository import Repository
from app.models.user import User
from app.services.foundation import foundation_relpath, read_foundation_from_origin
from app.services.git_repo import (
    GitError,
    OriginInfo,
    inspect_origin,
    validate_doc_dir,
    validate_local_path,
)
from app.services.github_api import GitHubAPIError, GitHubClient
from app.services.ingest import sync_owner_and_repo

router = APIRouter(tags=["repos"])
templates = build_templates()


def _ctx(user: User, **extra):
    jti = getattr(user, "_token_jti", "")
    base = {"user": user, "csrf_token": csrf_token_for_jti(jti) if jti else "", "nav": "companies"}
    base.update(extra)
    return base


def _foundation_context(repo: Repository, origin: OriginInfo) -> dict[str, str]:
    """Read-only foundation check; mirrors the Issue detail rules and never fetches."""
    rel_path = foundation_relpath(repo.doc_dir or "docs")
    context = {
        "state": "no_path",
        "rel_path": rel_path,
        "ref": f"origin/{repo.default_branch}",
        "detail": "",
    }
    if not repo.local_path:
        return context
    if origin.state == "unavailable":
        context["state"] = "not_checked"
        context["detail"] = origin.detail
        return context
    try:
        info = read_foundation_from_origin(
            repo.local_path,
            default_branch=repo.default_branch,
            doc_dir=repo.doc_dir,
        )
    except OSError:
        context["state"] = "unavailable"
        return context
    context["state"] = "exists" if info.exists else "missing"
    return context


def _summary_links(repo_id: int) -> dict[str, str]:
    base = f"/repos/{repo_id}/issues"
    return {
        "unfinished": f"{base}?kind=feature&status=unfinished&github_state=open",
        "support": f"{base}?kind=support&status=support_open&github_state=open",
        "failed": f"{base}?status=failed&github_state=open",
    }


def _repo_page_context(
    db: Session,
    user: User,
    repo: Repository,
    *,
    local_path: str | None = None,
    doc_dir: str | None = None,
    field_errors: dict[str, str] | None = None,
    form_disabled: bool | None = None,
    flash: str | None = None,
    msg: str | None = None,
) -> dict:
    company = company_crud.get(db, repo.company_id)
    origin = inspect_origin(repo.local_path, repo.github_full_name)
    if local_path is None:
        local_path = repo.local_path or ""
    if doc_dir is None:
        doc_dir = repo.doc_dir or "docs"
    if form_disabled is None:
        form_disabled = job_crud.has_active_for_repo(db, repo.id)
    return _ctx(
        user,
        repo=repo,
        company=company,
        local_path=local_path,
        doc_dir=doc_dir,
        field_errors=field_errors or {},
        form_disabled=form_disabled,
        origin=origin,
        origin_mismatch=origin.state == "mismatch",
        foundation=_foundation_context(repo, origin),
        issue_summary=issue_crud.repo_open_summary(db, repo.id),
        summary_links=_summary_links(repo.id),
        flash=flash,
        msg=msg,
        breadcrumbs=[
            ("公司", "/"),
            (company.name if company else "公司", f"/companies/{repo.company_id}"),
            (repo.github_full_name, None),
        ],
    )


@router.get("/repos/{repo_id}", response_class=HTMLResponse)
def repo_page(
    repo_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_page_user)],
):
    repo = repository_crud.get(db, repo_id)
    if repo is None:
        return templates.TemplateResponse(
            request, "404.html", _ctx(user, message="未找到仓库"), status_code=404
        )
    return templates.TemplateResponse(
        request,
        "repo.html",
        _repo_page_context(
            db,
            user,
            repo,
            flash=request.query_params.get("flash"),
            msg=request.query_params.get("msg"),
        ),
    )


@router.post("/repos/{repo_id}")
def repo_save(
    repo_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
    local_path: Annotated[str, Form()] = "",
    doc_dir: Annotated[str, Form()] = "docs",
):
    repo = repository_crud.get(db, repo_id)
    if repo is None:
        return RedirectResponse("/", status_code=303)
    if job_crud.has_active_for_repo(db, repo.id):
        return RedirectResponse(
            f"/repos/{repo_id}?flash=error&msg={quote('有进行中的任务，暂不可改路径')}",
            status_code=303,
        )
    errors: dict[str, str] = {}
    local_path = local_path.strip()
    doc_dir = (doc_dir or "docs").strip()
    if local_path:
        try:
            validate_local_path(local_path, repo.github_full_name)
            validate_doc_dir(local_path, doc_dir)
        except GitError as exc:
            msg = str(exc)
            if "文档" in msg:
                errors["doc_dir"] = msg
            else:
                errors["local_path"] = msg
    else:
        try:
            if not doc_dir or doc_dir.startswith("/") or ".." in doc_dir:
                raise GitError("文档目录必须是相对路径，且不能包含 ..")
        except GitError as exc:
            errors["doc_dir"] = str(exc)

    if errors:
        return templates.TemplateResponse(
            request,
            "repo.html",
            _repo_page_context(
                db,
                user,
                repo,
                local_path=local_path,
                doc_dir=doc_dir,
                field_errors=errors,
                form_disabled=False,
            ),
            status_code=200,
        )

    repo.local_path = local_path or None
    repo.doc_dir = doc_dir or "docs"
    db.commit()
    return RedirectResponse(f"/repos/{repo_id}?flash=ok&msg={quote('已保存')}", status_code=303)


@router.post("/repos/{repo_id}/resync")
def repo_resync(
    repo_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
):
    _ = user
    repo = repository_crud.get(db, repo_id)
    if repo is None:
        return RedirectResponse("/", status_code=303)
    client = GitHubClient()
    try:
        sync_owner_and_repo(db, client, repo.github_repo_id)
        msg = quote("已同步")
        flash = "ok"
    except GitHubAPIError as exc:
        repository_crud.set_sync_error(db, repo, str(exc))
        msg = quote(str(exc))
        flash = "error"
    finally:
        client.close()
    return RedirectResponse(
        f"/companies/{repo.company_id}?flash={flash}&msg={msg}",
        status_code=303,
    )
