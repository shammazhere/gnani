"""Add is_active column to workers table.

Revision ID: 002_add_worker_is_active
Revises: 001_initial_schema
Create Date: 2026-11-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_add_worker_is_active"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add is_active column with server-side default of TRUE
    # Using batch_alter_table for SQLite compatibility
    with op.batch_alter_table("workers") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("TRUE"),
            )
        )


def downgrade() -> None:
    # Remove is_active column using batch_alter_table for SQLite compatibility
    with op.batch_alter_table("workers") as batch_op:
        batch_op.drop_column("is_active")