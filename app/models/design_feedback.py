from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import DB_SCHEMA
from app.database.connect import Base


class DesignFeedback(Base):
    """One human action on an Issue design document.

    Pending-item decisions reuse this table: ``kind`` plus ``doc_sha256`` and
    ``pending_item_key`` identify the versioned decision. No database enum or
    check constraint is used so new kinds do not require a migration.
    """

    __tablename__ = "design_feedback"
    __table_args__ = (
        Index("ix_design_feedback_issue_created", "issue_id", "created_at"),
        Index(
            "ix_design_feedback_issue_doc_item",
            "issue_id",
            "doc_sha256",
            "pending_item_key",
        ),
        Index(
            "ix_design_feedback_unresolved",
            "issue_id",
            postgresql_where=text(
                "kind IN ('human_comment', 'revise_request') AND resolved_at IS NULL"
            ),
        ),
        {"schema": DB_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DB_SCHEMA}.issue.id"), nullable=False, index=True
    )
    author_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DB_SCHEMA}.users.id"), nullable=False
    )
    author_username: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    pending_item_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_item_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    doc_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(f"{DB_SCHEMA}.job.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
