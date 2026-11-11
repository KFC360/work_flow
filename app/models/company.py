from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import DB_SCHEMA
from app.database.connect import Base


class Company(Base):
    __tablename__ = "company"
    __table_args__ = {"schema": DB_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_account_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    login: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    html_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
