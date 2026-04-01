"""add backend_route to component_configs

Revision ID: 758cd1ca2aad
Revises: c5d6e7f8a9b0
Create Date: 2026-03-31 22:11:52.163452

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '758cd1ca2aad'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('component_configs', sa.Column('backend_route', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('component_configs', 'backend_route')
