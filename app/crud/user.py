from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.settings import get_settings
from app.models.user import User


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def count_users(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(User)) or 0)


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    email: str | None = None,
    full_name: str | None = None,
) -> User:
    user = User(
        username=username,
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
        disabled=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_admin_user(db: Session) -> User | None:
    if count_users(db) > 0:
        return None
    settings = get_settings()
    if not settings.app_admin_user or not settings.app_admin_password:
        return None
    return create_user(
        db,
        username=settings.app_admin_user,
        password=settings.app_admin_password,
    )
