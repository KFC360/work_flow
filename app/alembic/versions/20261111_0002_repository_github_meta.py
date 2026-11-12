"""repository github metadata

Revision ID: 20261111_0002
Revises: 20261111_0001
Create Date: 2026-11-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261111_0002"
down_revision: Union[str, None] = "20261111_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "github_workflow"


def upgrade() -> None:
    op.add_column("repository", sa.Column("language", sa.String(length=100), nullable=True), schema=SCHEMA)
    op.add_column("repository", sa.Column("stargazers_count", sa.Integer(), nullable=True), schema=SCHEMA)
    op.add_column("repository", sa.Column("forks_count", sa.Integer(), nullable=True), schema=SCHEMA)
    op.add_column("repository", sa.Column("open_issues_count", sa.Integer(), nullable=True), schema=SCHEMA)
    op.add_column(
        "repository",
        sa.Column("topics", postgresql.ARRAY(sa.String(length=255)), nullable=True),
        schema=SCHEMA,
    )
    op.add_column("repository", sa.Column("license_spdx", sa.String(length=64), nullable=True), schema=SCHEMA)
    op.add_column("repository", sa.Column("license_name", sa.String(length=255), nullable=True), schema=SCHEMA)
    op.add_column(
        "repository",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=SCHEMA,
    )
    op.add_column(
        "repository",
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=SCHEMA,
    )
    op.add_column(
        "repository",
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column("repository", sa.Column("homepage", sa.String(length=512), nullable=True), schema=SCHEMA)
    op.add_column("repository", sa.Column("visibility", sa.String(length=32), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("repository", "visibility", schema=SCHEMA)
    op.drop_column("repository", "homepage", schema=SCHEMA)
    op.drop_column("repository", "pushed_at", schema=SCHEMA)
    op.drop_column("repository", "disabled", schema=SCHEMA)
    op.drop_column("repository", "archived", schema=SCHEMA)
    op.drop_column("repository", "license_name", schema=SCHEMA)
    op.drop_column("repository", "license_spdx", schema=SCHEMA)
    op.drop_column("repository", "topics", schema=SCHEMA)
    op.drop_column("repository", "open_issues_count", schema=SCHEMA)
    op.drop_column("repository", "forks_count", schema=SCHEMA)
    op.drop_column("repository", "stargazers_count", schema=SCHEMA)
    op.drop_column("repository", "language", schema=SCHEMA)
