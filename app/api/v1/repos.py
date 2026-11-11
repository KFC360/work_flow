from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.security import csrf_token_for_jti
from app.core.settings import PROJECT_ROOT
from app.crud import company as company_crud
from app.crud import job as job_crud
from app.crud import repository as repository_crud
from app.database.connect import get_db
from app.dependencies.auth import require_csrf, require_page_user
from app.models.user import User
from app.services.git_repo import GitError, validate_doc_dir, validate_local_path
from app.services.github_api import GitHubAPIError, GitHubClient
from app.services.ingest import sync_owner_and_repo

router = APIRouter(tags=["repos"])
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


def _ctx(user: User, **extra):
    jti = getattr(user, "_token_jti", "")
    base = {"user": user, "csrf_token": csrf_token_for_jti(jti) if jti else "", "nav": "companies"}
    base.update(extra)
    return base


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
    company = company_crud.get(db, repo.company_id)
    return templates.TemplateResponse(
        request,
        "repo.html",
        _ctx(
            user,
            repo=repo,
            company=company,
            local_path=repo.local_path or "",
            doc_dir=repo.doc_dir or "docs",
            field_errors={},
            form_disabled=job_crud.has_active_for_repo(db, repo.id),
            origin_mismatch=False,
            flash=request.query_params.get("flash"),
            msg=request.query_params.get("msg"),
            breadcrumbs=[
                ("公司", "/"),
                (company.name if company else "公司", f"/companies/{repo.company_id}"),
                (repo.github_full_name, None),
            ],
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
        company = company_crud.get(db, repo.company_id)
        return templates.TemplateResponse(
            request,
            "repo.html",
            _ctx(
                user,
                repo=repo,
                company=company,
                local_path=local_path,
                doc_dir=doc_dir,
                field_errors=errors,
                form_disabled=False,
                origin_mismatch=False,
                breadcrumbs=[
                    ("公司", "/"),
                    (company.name if company else "公司", f"/companies/{repo.company_id}"),
                    (repo.github_full_name, None),
                ],
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
