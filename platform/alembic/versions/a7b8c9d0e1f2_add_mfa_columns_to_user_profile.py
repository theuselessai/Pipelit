"""add_mfa_columns_to_user_profile

Revision ID: a7b8c9d0e1f2
Revises: 5f6ac39287da
Create Date: 2026-02-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = '5f6ac39287da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add TOTP / MFA columns to user_profiles."""
    with op.batch_alter_table('user_profiles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('totp_secret', sa.String(500), nullable=True))
        batch_op.add_column(sa.Column('mfa_enabled', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('totp_last_used_at', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove TOTP / MFA columns from user_profiles."""
    with op.batch_alter_table('user_profiles', schema=None) as batch_op:
        batch_op.drop_column('totp_last_used_at')
        batch_op.drop_column('mfa_enabled')
        batch_op.drop_column('totp_secret')
