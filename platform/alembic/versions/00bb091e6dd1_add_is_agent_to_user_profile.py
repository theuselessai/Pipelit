"""add_is_agent_to_user_profile

Revision ID: 00bb091e6dd1
Revises: a1b2c3d4e5f6
Create Date: 2026-02-05 21:46:47.923820

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00bb091e6dd1'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Disable FK enforcement to prevent CASCADE during batch alter
    op.execute("PRAGMA foreign_keys = OFF")

    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.add_column(sa.Column('is_agent', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('created_by_agent_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_user_profiles_created_by_agent_id',
            'user_profiles',
            ['created_by_agent_id'],
            ['id'],
            ondelete='SET NULL',
        )

    op.execute("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    """Downgrade schema."""
    # Disable FK enforcement to prevent CASCADE during batch alter
    op.execute("PRAGMA foreign_keys = OFF")

    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.drop_constraint('fk_user_profiles_created_by_agent_id', type_='foreignkey')
        batch_op.drop_column('created_by_agent_id')
        batch_op.drop_column('is_agent')

    op.execute("PRAGMA foreign_keys = ON")
