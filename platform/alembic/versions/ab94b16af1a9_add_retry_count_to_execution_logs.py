"""add retry_count to execution_logs

Revision ID: ab94b16af1a9
Revises: 5f2bbd73be73
Create Date: 2026-02-13 10:25:24.856705

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab94b16af1a9'
down_revision: Union[str, Sequence[str], None] = '5f2bbd73be73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("execution_logs") as batch_op:
        batch_op.add_column(sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("execution_logs") as batch_op:
        batch_op.drop_column("retry_count")
