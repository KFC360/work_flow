"""design review approval and feedback

Revision ID: 20261112_0005
Revises: 20261112_0004
Create Date: 2026-11-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0005"
down_revision: Union[str, None] = "20261112_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "github_workflow"


def upgrade() -> None:
    op.add_column(
        "issue",
        sa.Column("doc_approved_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )

    # Historical "doc written, code not generated" rows were implicitly
    # approved before this gate existed. New rows stay NULL until a human
    # approves them.
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.issue "
            "SET doc_approved_at = COALESCE(updated_at, now()) "
            "WHERE status = 'pending_codegen' "
            "AND design_doc_text IS NOT NULL "
            "AND btrim(design_doc_text) <> ''"
        )
    )

    op.create_table(
        "design_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=False),
        sa.Column("author_username", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("pending_item_key", sa.String(length=64), nullable=True),
        sa.Column("pending_item_title", sa.String(length=512), nullable=True),
        sa.Column("doc_sha256", sa.String(length=64), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"], [f"{SCHEMA}.issue.id"], name="fk_design_feedback_issue_id"
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            [f"{SCHEMA}.users.id"],
            name="fk_design_feedback_author_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], [f"{SCHEMA}.job.id"], name="fk_design_feedback_job_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_design_feedback"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_design_feedback_issue_id",
        "design_feedback",
        ["issue_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_design_feedback_issue_created",
        "design_feedback",
        ["issue_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_design_feedback_issue_doc_item",
        "design_feedback",
        ["issue_id", "doc_sha256", "pending_item_key"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_design_feedback_unresolved",
        "design_feedback",
        ["issue_id"],
        schema=SCHEMA,
        postgresql_where=sa.text(
            "kind IN ('human_comment', 'revise_request') AND resolved_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_design_feedback_unresolved", table_name="design_feedback", schema=SCHEMA)
    op.drop_index(
        "ix_design_feedback_issue_doc_item", table_name="design_feedback", schema=SCHEMA
    )
    op.drop_index(
        "ix_design_feedback_issue_created", table_name="design_feedback", schema=SCHEMA
    )
    op.drop_index("ix_design_feedback_issue_id", table_name="design_feedback", schema=SCHEMA)
    op.drop_table("design_feedback", schema=SCHEMA)
    op.drop_column("issue", "doc_approved_at", schema=SCHEMA)
