from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.exceptions import LoginRedirect
from app.core.security import COOKIE_NAME, decode_access_token, verify_csrf
from app.crud import user as user_crud
from app.database.connect import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token", auto_error=False)

DbDep = Annotated[Session, Depends(get_db)]


def _user_from_token(db: Session, token: str) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        jti = payload.get("jti")
        if not isinstance(username, str) or not isinstance(jti, str):
            raise credentials_exception
    except InvalidTokenError as exc:
        raise credentials_exception from exc
    user = user_crud.get_by_username(db, username)
    if user is None:
        raise credentials_exception
    user._token_jti = jti  # type: ignore[attr-defined]
    return user


def get_token_from_request(request: Request, bearer: str | None) -> str | None:
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie
    return bearer


def get_current_user(
    request: Request,
    db: DbDep,
    bearer: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    token = get_token_from_request(request, bearer)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _user_from_token(db, token)


def get_current_active_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


def get_optional_page_user(request: Request, db: DbDep) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        user = _user_from_token(db, token)
    except HTTPException:
        return None
    if user.disabled:
        return None
    return user


def require_page_user(request: Request, db: DbDep) -> User:
    user = get_optional_page_user(request, db)
    if user is None:
        raise LoginRedirect()
    return user


def require_csrf(
    user: Annotated[User, Depends(require_page_user)],
    csrf_token: Annotated[str | None, Form()] = None,
) -> User:
    jti = getattr(user, "_token_jti", None)
    if not isinstance(jti, str) or not verify_csrf(jti, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return user
