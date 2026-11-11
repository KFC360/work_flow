from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.exceptions import LoginRedirect
from app.core.security import csrf_token_for_jti
from app.core.templating import build_templates
from app.crud import company as company_crud
from app.crud import repository as repository_crud
from app.database.connect import get_db
from app.dependencies.auth import require_page_user
from app.models.user import User

router = APIRouter(tags=["companies"])
templates = build_templates()
PAGE_SIZE = 50


def _ctx(user: User, **extra):
    jti = getattr(user, "_token_jti", "")
    base = {
        "user": user,
        "csrf_token": csrf_token_for_jti(jti) if jti else "",
        "nav": "companies",
    }
    base.update(extra)
    return base


@router.get("/", response_class=HTMLResponse)
def company_list(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_page_user)],
    page: int = 1,
):
    page = max(page, 1)
    companies = company_crud.list_companies(db, offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE)
    total = company_crud.count_companies(db)
    rows = [
        {
            "company": c,
            "repo_count": company_crud.repo_count(db, c.id),
            "open_issues": company_crud.open_issue_count(db, c.id),
        }
        for c in companies
    ]
    return templates.TemplateResponse(
        request,
        "companies.html",
        _ctx(
            user,
            rows=rows,
            total=total,
            page=page,
            pagination={
                "page": page,
                "has_prev": page > 1,
                "has_next": page * PAGE_SIZE < total,
                "prev_url": f"/?page={page - 1}",
                "next_url": f"/?page={page + 1}",
            },
            flash=request.query_params.get("flash"),
            msg=request.query_params.get("msg"),
            breadcrumbs=None,
        ),
    )


@router.get("/companies/{company_id}", response_class=HTMLResponse)
def company_repos(
    company_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_page_user)],
    page: int = 1,
):
    company = company_crud.get(db, company_id)
    if company is None:
        return templates.TemplateResponse(
            request,
            "404.html",
            _ctx(user, message="未找到该公司", breadcrumbs=[("公司", "/"), ("未找到", None)]),
            status_code=404,
        )
    page = max(page, 1)
    repos = repository_crud.list_by_company(
        db, company_id, offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE
    )
    total = company_crud.repo_count(db, company_id)
    rows = [
        {
            "repo": r,
            "open_issues": repository_crud.open_issue_count(db, r.id),
        }
        for r in repos
    ]
    return templates.TemplateResponse(
        request,
        "repos.html",
        _ctx(
            user,
            company=company,
            rows=rows,
            total=total,
            page=page,
            pagination={
                "page": page,
                "has_prev": page > 1,
                "has_next": page * PAGE_SIZE < total,
                "prev_url": f"/companies/{company_id}?page={page - 1}",
                "next_url": f"/companies/{company_id}?page={page + 1}",
            },
            flash=request.query_params.get("flash"),
            msg=request.query_params.get("msg"),
            breadcrumbs=[("公司", "/"), (company.name, None)],
        ),
    )


# silence unused
_ = LoginRedirect
