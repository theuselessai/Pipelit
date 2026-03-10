"""change external_user_id from BigInteger to String

Revision ID: a3b01ecbbd73
Revises: 891805fc9d3c
Create Date: 2026-03-10 23:04:29.746856

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b01ecbbd73'
down_revision: Union[str, Sequence[str], None] = '891805fc9d3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change external_user_id from BigInteger to String(255).

    Allows non-numeric external IDs (e.g. 'cli-user' from generic gateway adapters)
    while preserving existing numeric Telegram user IDs as strings.
    """
    with op.batch_alter_table("user_profiles") as batch_op:
        batch_op.alter_column(
            "external_user_id",
            existing_type=sa.BigInteger(),
            type_=sa.String(length=255),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Revert external_user_id back to BigInteger."""
    with op.batch_alter_table("user_profiles") as batch_op:
        batch_op.alter_column(
            "external_user_id",
            existing_type=sa.String(length=255),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )
