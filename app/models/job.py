from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import DB_SCHEMA
from app.database.connect import Base


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        Index(
            "uq_job_repo_running",
            "repository_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        {"schema": DB_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DB_SCHEMA}.issue.id"), nullable=False, index=True
    )
    repository_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DB_SCHEMA}.repository.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    log_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
