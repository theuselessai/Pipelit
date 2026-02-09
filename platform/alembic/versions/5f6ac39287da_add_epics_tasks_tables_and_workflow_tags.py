"""add_epics_tasks_tables_and_workflow_tags

Revision ID: 5f6ac39287da
Revises: b2c3d4e5f6a7
Create Date: 2026-02-10 09:10:45.554932

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f6ac39287da'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Epics table
    op.create_table(
        'epics',
        sa.Column('id', sa.String(20), primary_key=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), server_default=''),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('created_by_node_id', sa.String(255), nullable=True),
        sa.Column('workflow_id', sa.Integer(),
                  sa.ForeignKey('workflows.id', ondelete='SET NULL'), nullable=True),
        sa.Column('user_profile_id', sa.Integer(),
                  sa.ForeignKey('user_profiles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(20), server_default='planning'),
        sa.Column('priority', sa.Integer(), server_default='2'),
        sa.Column('budget_tokens', sa.Integer(), nullable=True),
        sa.Column('budget_usd', sa.Float(), nullable=True),
        sa.Column('spent_tokens', sa.Integer(), server_default='0'),
        sa.Column('spent_usd', sa.Float(), server_default='0.0'),
        sa.Column('agent_overhead_tokens', sa.Integer(), server_default='0'),
        sa.Column('agent_overhead_usd', sa.Float(), server_default='0.0'),
        sa.Column('total_tasks', sa.Integer(), server_default='0'),
        sa.Column('completed_tasks', sa.Integer(), server_default='0'),
        sa.Column('failed_tasks', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('result_summary', sa.Text(), nullable=True),
    )
    op.create_index('ix_epics_status', 'epics', ['status'])
    op.create_index('ix_epics_user_profile_id', 'epics', ['user_profile_id'])

    # Tasks table
    op.create_table(
        'tasks',
        sa.Column('id', sa.String(20), primary_key=True),
        sa.Column('epic_id', sa.String(20),
                  sa.ForeignKey('epics.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), server_default=''),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('created_by_node_id', sa.String(255), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('priority', sa.Integer(), server_default='2'),
        sa.Column('workflow_id', sa.Integer(),
                  sa.ForeignKey('workflows.id', ondelete='SET NULL'), nullable=True),
        sa.Column('workflow_slug', sa.String(255), nullable=True),
        sa.Column('execution_id', sa.String(36), nullable=True),
        sa.Column('workflow_source', sa.String(20), server_default='inline'),
        sa.Column('depends_on', sa.JSON(), nullable=True),
        sa.Column('requirements', sa.JSON(), nullable=True),
        sa.Column('estimated_tokens', sa.Integer(), nullable=True),
        sa.Column('actual_tokens', sa.Integer(), server_default='0'),
        sa.Column('actual_usd', sa.Float(), server_default='0.0'),
        sa.Column('llm_calls', sa.Integer(), server_default='0'),
        sa.Column('tool_invocations', sa.Integer(), server_default='0'),
        sa.Column('duration_ms', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('result_summary', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('max_retries', sa.Integer(), server_default='2'),
        sa.Column('notes', sa.JSON(), nullable=True),
    )
    op.create_index('ix_tasks_epic_id', 'tasks', ['epic_id'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])
    op.create_index('ix_tasks_workflow_id', 'tasks', ['workflow_id'])

    # Workflow tags column
    op.add_column('workflows', sa.Column('tags', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('workflows', 'tags')
    op.drop_index('ix_tasks_workflow_id', 'tasks')
    op.drop_index('ix_tasks_status', 'tasks')
    op.drop_index('ix_tasks_epic_id', 'tasks')
    op.drop_table('tasks')
    op.drop_index('ix_epics_user_profile_id', 'epics')
    op.drop_index('ix_epics_status', 'epics')
    op.drop_table('epics')
