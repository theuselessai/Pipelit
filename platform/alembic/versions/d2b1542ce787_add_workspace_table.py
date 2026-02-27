"""add_workspace_table

Revision ID: d2b1542ce787
Revises: ed0c67c6b442
Create Date: 2026-02-27 19:30:54.746239

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2b1542ce787'
down_revision: Union[str, Sequence[str], None] = 'ed0c67c6b442'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("allow_network", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("user_profile_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.ForeignKeyConstraint(["user_profile_id"], ["user_profiles.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("workspaces")
