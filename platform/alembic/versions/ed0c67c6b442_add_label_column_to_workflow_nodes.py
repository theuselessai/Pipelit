"""Add label column to workflow_nodes.

Revision ID: ed0c67c6b442
Revises: 0d301d48b86a
Create Date: 2026-02-19
"""

import sqlalchemy as sa
from alembic import op

revision = "ed0c67c6b442"
down_revision = "0d301d48b86a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_nodes", sa.Column("label", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_nodes", "label")
