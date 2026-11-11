"""initial schema

Revision ID: 20261111_0001
Revises:
Create Date: 2026-11-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261111_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "github_workflow"


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("disabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("username"),
        schema=SCHEMA,
    )

    op.create_table(
        "company",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("github_account_id", sa.BigInteger(), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("login", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("html_url", sa.String(length=512), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("github_account_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "repository",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.company.id"), nullable=False),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("github_full_name", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("html_url", sa.String(length=512), nullable=True),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("local_path", sa.String(length=1024), nullable=True),
        sa.Column("doc_dir", sa.String(length=255), nullable=False, server_default="docs"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("github_repo_id"),
        sa.UniqueConstraint("local_path"),
        schema=SCHEMA,
    )
    op.create_index("ix_repository_company_id", "repository", ["company_id"], schema=SCHEMA)

    op.create_table(
        "issue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.repository.id"), nullable=False),
        sa.Column("github_issue_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("iteration_no", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("html_url", sa.String(length=512), nullable=False),
        sa.Column("author_login", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("github_state", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("label_names", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("design_doc_path", sa.String(length=512), nullable=True),
        sa.Column("design_doc_text", sa.Text(), nullable=True),
        sa.Column("design_source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("worktree_path", sa.String(length=1024), nullable=True),
        sa.Column("base_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("doc_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("code_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("codegen_phase", sa.String(length=64), nullable=False, server_default="none"),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(length=512), nullable=True),
        sa.Column("failed_action", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("github_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("repository_id", "number", name="uq_issue_repo_number"),
        sa.UniqueConstraint("repository_id", "iteration_no", name="uq_issue_repo_iteration"),
        schema=SCHEMA,
    )
    op.create_index("ix_issue_repository_id", "issue", ["repository_id"], schema=SCHEMA)
    op.create_index("ix_issue_github_issue_id", "issue", ["github_issue_id"], schema=SCHEMA)

    op.create_table(
        "job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.issue.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.repository.id"), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("agent", sa.String(length=64), nullable=True),
        sa.Column("log_path", sa.String(length=1024), nullable=True),
        sa.Column("log_excerpt", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_job_issue_id", "job", ["issue_id"], schema=SCHEMA)
    op.create_index("ix_job_repository_id", "job", ["repository_id"], schema=SCHEMA)
    op.execute(
        sa.text(
            f"CREATE UNIQUE INDEX uq_job_repo_running ON {SCHEMA}.job (repository_id) "
            "WHERE status = 'running'"
        )
    )

    op.create_table(
        "webhook_delivery",
        sa.Column("delivery_id", sa.String(length=128), primary_key=True),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_webhook_delivery_repository_id", "webhook_delivery", ["repository_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_table("webhook_delivery", schema=SCHEMA)
    op.drop_table("job", schema=SCHEMA)
    op.drop_table("issue", schema=SCHEMA)
    op.drop_table("repository", schema=SCHEMA)
    op.drop_table("company", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
