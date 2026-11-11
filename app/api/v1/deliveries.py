from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import csrf_token_for_jti
from app.core.templating import build_templates
from app.crud import repository as repository_crud
from app.crud import webhook_delivery as delivery_crud
from app.database.connect import get_db
from app.dependencies.auth import require_csrf, require_page_user
from app.models.user import User

router = APIRouter(tags=["deliveries"])
templates = build_templates()
PAGE_SIZE = 50


@router.get("/deliveries", response_class=HTMLResponse)
def deliveries_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_page_user)],
    status: str | None = None,
    page: int = 1,
):
    page = max(page, 1)
    status_filter = status if status and status != "全部" else None
    if status_filter == "all":
        status_filter = None
    total = delivery_crud.count_deliveries(db, status=status_filter)
    rows = delivery_crud.list_deliveries(
        db, status=status_filter, offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE
    )
    repo_names = repository_crud.full_names_by_github_ids(
        db, [r.repository_id for r in rows if r.repository_id is not None]
    )
    jti = getattr(user, "_token_jti", "")
    selected_status = status_filter or "all"
    return templates.TemplateResponse(
        request,
        "deliveries.html",
        {
            "user": user,
            "csrf_token": csrf_token_for_jti(jti) if jti else "",
            "rows": rows,
            "total": total,
            "repo_names": repo_names,
            "status": selected_status,
            "page": page,
            "pagination": {
                "page": page,
                "has_prev": page > 1,
                "has_next": page * PAGE_SIZE < total,
                "prev_url": f"/deliveries?status={selected_status}&page={page - 1}",
                "next_url": f"/deliveries?status={selected_status}&page={page + 1}",
            },
            "flash": request.query_params.get("flash"),
            "msg": request.query_params.get("msg"),
            "breadcrumbs": [("Webhook 投递", None)],
            "nav": "deliveries",
        },
    )


@router.post("/deliveries/{delivery_id}/retry")
def retry_delivery(
    delivery_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
):
    _ = user
    row = delivery_crud.requeue_failed(db, delivery_id)
    if row is None:
        return RedirectResponse(
            "/deliveries?flash=error&msg=%E6%97%A0%E6%B3%95%E9%87%8D%E8%AF%95",
            status_code=303,
        )
    return RedirectResponse(
        "/deliveries?flash=ok&msg=%E5%B7%B2%E9%87%8D%E6%96%B0%E6%8E%92%E9%98%9F",
        status_code=303,
    )
