"""Add cost tracking columns to workflow_executions

Revision ID: ce940f4fa7f6
Revises: a7b8c9d0e1f2
Create Date: 2026-02-12 23:34:53.147474

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce940f4fa7f6'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cost tracking columns to workflow_executions."""
    op.add_column('workflow_executions', sa.Column('total_input_tokens', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('workflow_executions', sa.Column('total_output_tokens', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('workflow_executions', sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('workflow_executions', sa.Column('total_cost_usd', sa.Numeric(precision=12, scale=6), nullable=False, server_default='0'))
    op.add_column('workflow_executions', sa.Column('llm_calls', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Remove cost tracking columns from workflow_executions."""
    op.drop_column('workflow_executions', 'llm_calls')
    op.drop_column('workflow_executions', 'total_cost_usd')
    op.drop_column('workflow_executions', 'total_tokens')
    op.drop_column('workflow_executions', 'total_output_tokens')
    op.drop_column('workflow_executions', 'total_input_tokens')
