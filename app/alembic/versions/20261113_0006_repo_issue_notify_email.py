"""repository notify emails and issue notify timestamp

Revision ID: 20261113_0006
Revises: 20261112_0005
Create Date: 2026-11-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261113_0006"
down_revision: Union[str, None] = "20261112_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "github_workflow"


def upgrade() -> None:
    op.add_column(
        "repository",
        sa.Column(
            "notify_emails",
            postgresql.ARRAY(sa.String(length=320)),
            nullable=False,
            server_default="{}",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "issue",
        sa.Column("notify_email_sent_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("issue", "notify_email_sent_at", schema=SCHEMA)
    op.drop_column("repository", "notify_emails", schema=SCHEMA)
