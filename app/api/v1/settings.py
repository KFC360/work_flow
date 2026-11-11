from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.security import csrf_token_for_jti
from app.core.settings import PROJECT_ROOT
from app.database.connect import get_db
from app.dependencies.auth import require_csrf, require_page_user
from app.models.user import User
from app.services.config_agent import read_agent, write_agent

router = APIRouter(tags=["settings"])
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_page_user)],
):
    _ = db
    jti = getattr(user, "_token_jti", "")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "csrf_token": csrf_token_for_jti(jti) if jti else "",
            "agent": read_agent(),
            "nav": "settings",
            "breadcrumbs": [("设置", None)],
            "flash": request.query_params.get("flash"),
            "msg": request.query_params.get("msg"),
        },
    )


@router.post("/settings")
def settings_save(
    user: Annotated[User, Depends(require_csrf)],
    agent: Annotated[str, Form()],
):
    _ = user
    try:
        write_agent(agent)
    except ValueError:
        return RedirectResponse(
            f"/settings?flash=error&msg={quote('非法代理值')}",
            status_code=303,
        )
    return RedirectResponse(
        f"/settings?flash=ok&msg={quote('已保存')}",
        status_code=303,
    )
