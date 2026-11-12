"""issue GitHub type name

Revision ID: 20261112_0004
Revises: 20261112_0003
Create Date: 2026-11-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0004"
down_revision: Union[str, None] = "20261112_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "github_workflow"


def upgrade() -> None:
    op.add_column(
        "issue",
        sa.Column("github_issue_type", sa.String(length=128), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("issue", "github_issue_type", schema=SCHEMA)
