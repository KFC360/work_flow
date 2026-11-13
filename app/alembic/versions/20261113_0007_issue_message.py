"""issue_message for comments and timeline events

Revision ID: 20261113_0007
Revises: 20261113_0006
Create Date: 2026-11-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_0007"
down_revision: Union[str, None] = "20261113_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "github_workflow"


def upgrade() -> None:
    op.create_table(
        "issue_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "issue_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.issue.id"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=True),
        sa.Column("event_key", sa.String(length=128), nullable=True),
        sa.Column("github_comment_id", sa.BigInteger(), nullable=True),
        sa.Column("author_login", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("github_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_issue_message_issue_id",
        "issue_message",
        ["issue_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_issue_message_issue_occurred",
        "issue_message",
        ["issue_id", "occurred_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_issue_message_comment_not_null",
        "issue_message",
        ["issue_id", "github_comment_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("github_comment_id IS NOT NULL"),
    )
    op.create_index(
        "uq_issue_message_event_key_not_null",
        "issue_message",
        ["issue_id", "event_key"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("event_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_issue_message_event_key_not_null",
        table_name="issue_message",
        schema=SCHEMA,
    )
    op.drop_index(
        "uq_issue_message_comment_not_null",
        table_name="issue_message",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_issue_message_issue_occurred",
        table_name="issue_message",
        schema=SCHEMA,
    )
    op.drop_index("ix_issue_message_issue_id", table_name="issue_message", schema=SCHEMA)
    op.drop_table("issue_message", schema=SCHEMA)
