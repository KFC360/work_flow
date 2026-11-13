from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import DB_SCHEMA
from app.database.connect import Base

SOURCE_COMMENT = "comment"
SOURCE_EVENT = "event"


class IssueMessage(Base):
    __tablename__ = "issue_message"
    __table_args__ = (
        Index("ix_issue_message_issue_occurred", "issue_id", "occurred_at"),
        Index(
            "uq_issue_message_comment_not_null",
            "issue_id",
            "github_comment_id",
            unique=True,
            postgresql_where=text("github_comment_id IS NOT NULL"),
        ),
        Index(
            "uq_issue_message_event_key_not_null",
            "issue_id",
            "event_key",
            unique=True,
            postgresql_where=text("event_key IS NOT NULL"),
        ),
        {"schema": DB_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DB_SCHEMA}.issue.id"), nullable=False, index=True
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    github_comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    author_login: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    github_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
