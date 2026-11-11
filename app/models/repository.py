from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import DB_SCHEMA
from app.database.connect import Base


class Repository(Base):
    __tablename__ = "repository"
    __table_args__ = {"schema": DB_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DB_SCHEMA}.company.id"), nullable=False, index=True
    )
    github_repo_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    github_full_name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    local_path: Mapped[str | None] = mapped_column(String(1024), unique=True, nullable=True)
    doc_dir: Mapped[str] = mapped_column(String(255), nullable=False, default="docs", server_default="docs")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stargazers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forks_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_issues_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topics: Mapped[list[str] | None] = mapped_column(ARRAY(String(255)), nullable=True)
    license_spdx: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    homepage: Mapped[str | None] = mapped_column(String(512), nullable=True)
    visibility: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
