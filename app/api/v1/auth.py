from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.security import (
    COOKIE_NAME,
    create_access_token,
    csrf_token_for_jti,
    decode_access_token,
    verify_password,
)
from app.core.settings import PROJECT_ROOT, get_settings
from app.crud import user as user_crud
from app.database.connect import get_db
from app.dependencies.auth import get_optional_page_user, require_csrf
from app.models.user import User
from app.schemas.token import Token

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


def _set_auth_cookie(response: Response, token: str, request: Request) -> None:
    secure = request.url.scheme == "https"
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _authenticate(db: Session, username: str, password: str) -> tuple[User | None, str | None]:
    user_crud.ensure_admin_user(db)
    user = user_crud.get_by_username(db, username)
    if user is None or not verify_password(password, user.hashed_password):
        return None, "invalid"
    if user.disabled:
        return None, "disabled"
    return user, None


@router.post("/token", response_model=Token)
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
) -> Token:
    from fastapi import HTTPException

    user, err = _authenticate(db, form_data.username, form_data.password)
    if err == "disabled":
        raise HTTPException(status_code=400, detail="Inactive user")
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user.username)
    return Token(access_token=token, token_type="bearer")


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    user = get_optional_page_user(request, db)
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": None},
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    user, err = _authenticate(db, username, password)
    if err == "disabled":
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "账号已停用"},
            status_code=200,
        )
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "用户名或口令不正确"},
            status_code=200,
        )
    token = create_access_token(subject=user.username)
    response = RedirectResponse("/", status_code=303)
    _set_auth_cookie(response, token, request)
    return response


@router.post("/logout")
def logout(
    request: Request,
    user: Annotated[User, Depends(require_csrf)],
):
    _ = user
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


def template_csrf(user: User) -> str:
    jti = getattr(user, "_token_jti", None)
    if not isinstance(jti, str):
        # re-decode not available; callers must set _token_jti
        return ""
    return csrf_token_for_jti(jti)


def cookie_secure_default() -> bool:
    return False


# re-export helpers for templates context
__all__ = [
    "router",
    "template_csrf",
    "decode_access_token",
    "get_settings",
]
