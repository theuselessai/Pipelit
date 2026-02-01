"""add llm_model_config_id to component_configs

Revision ID: 95a44955aacc
Revises: ee58ce0cf036
Create Date: 2026-02-01 15:04:35.755818

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '95a44955aacc'
down_revision: Union[str, Sequence[str], None] = 'ee58ce0cf036'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('component_configs') as batch_op:
        batch_op.add_column(sa.Column('llm_model_config_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_llm_model_config', 'component_configs', ['llm_model_config_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('component_configs') as batch_op:
        batch_op.drop_constraint('fk_llm_model_config', type_='foreignkey')
        batch_op.drop_column('llm_model_config_id')
