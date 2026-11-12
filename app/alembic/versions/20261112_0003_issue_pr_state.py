"""issue PR state and GitHub state timestamps

Revision ID: 20261112_0003
Revises: 20261111_0002
Create Date: 2026-11-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0003"
down_revision: Union[str, None] = "20261111_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "github_workflow"


def upgrade() -> None:
    op.add_column(
        "issue",
        sa.Column(
            "pr_state",
            sa.String(length=16),
            nullable=False,
            server_default="none",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "issue",
        sa.Column("pr_state_updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "issue",
        sa.Column("pr_merged_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "issue",
        sa.Column("github_state_updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )

    # Historical rows: only backfill the state timestamp. Do not guess pr_state
    # from pr_number; merged/closed PRs must stay "none" until a real event.
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.issue "
            "SET github_state_updated_at = COALESCE(github_updated_at, updated_at) "
            "WHERE github_state_updated_at IS NULL"
        )
    )

    op.create_index(
        "uq_issue_repo_pr_number",
        "issue",
        ["repository_id", "pr_number"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("pr_number IS NOT NULL"),
    )
    op.create_index(
        "ix_issue_repo_pr_state",
        "issue",
        ["repository_id", "pr_state"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_issue_repo_pr_state", table_name="issue", schema=SCHEMA)
    op.drop_index("uq_issue_repo_pr_number", table_name="issue", schema=SCHEMA)
    op.drop_column("issue", "github_state_updated_at", schema=SCHEMA)
    op.drop_column("issue", "pr_merged_at", schema=SCHEMA)
    op.drop_column("issue", "pr_state_updated_at", schema=SCHEMA)
    op.drop_column("issue", "pr_state", schema=SCHEMA)
