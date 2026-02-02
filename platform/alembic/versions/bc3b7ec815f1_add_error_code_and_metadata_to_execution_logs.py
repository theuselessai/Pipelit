"""Add error_code and metadata to execution_logs

Revision ID: bc3b7ec815f1
Revises: 95a44955aacc
Create Date: 2026-02-02
"""
from alembic import op
import sqlalchemy as sa

revision = "bc3b7ec815f1"
down_revision = "95a44955aacc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("execution_logs", sa.Column("error_code", sa.String(50), nullable=True))
    op.add_column("execution_logs", sa.Column("metadata", sa.JSON(), nullable=True, server_default="{}"))


def downgrade() -> None:
    op.drop_column("execution_logs", "metadata")
    op.drop_column("execution_logs", "error_code")
