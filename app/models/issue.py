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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import DB_SCHEMA
from app.database.connect import Base


class Issue(Base):
    __tablename__ = "issue"
    __table_args__ = (
        UniqueConstraint("repository_id", "number", name="uq_issue_repo_number"),
        UniqueConstraint("repository_id", "iteration_no", name="uq_issue_repo_iteration"),
        Index(
            "uq_issue_repo_pr_number",
            "repository_id",
            "pr_number",
            unique=True,
            postgresql_where=text("pr_number IS NOT NULL"),
        ),
        Index("ix_issue_repo_pr_state", "repository_id", "pr_state"),
        {"schema": DB_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{DB_SCHEMA}.repository.id"), nullable=False, index=True
    )
    github_issue_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    iteration_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    html_url: Mapped[str] = mapped_column(String(512), nullable=False)
    author_login: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    github_state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    label_names: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    design_doc_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    design_doc_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    design_source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    base_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    doc_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    codegen_phase: Mapped[str] = mapped_column(
        String(64), nullable=False, default="none", server_default="none"
    )
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pr_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none"
    )
    pr_state_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pr_merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    github_state_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
