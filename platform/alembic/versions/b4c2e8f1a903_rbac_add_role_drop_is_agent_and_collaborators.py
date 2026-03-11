"""rbac_add_role_drop_is_agent_and_collaborators

Revision ID: b4c2e8f1a903
Revises: a3b01ecbbd73
Create Date: 2026-03-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa


revision: str = 'b4c2e8f1a903'
down_revision: Union[str, Sequence[str], None] = 'a3b01ecbbd73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(text("PRAGMA foreign_keys=OFF"))

    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(10), nullable=False, server_default='normal'))

    op.execute("UPDATE user_profiles SET role = 'admin'")

    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.drop_column('is_agent')

    op.drop_table('workflow_collaborators')

    connection.execute(text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(text("PRAGMA foreign_keys=OFF"))

    op.create_table(
        'workflow_collaborators',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workflow_id', sa.Integer(), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_profile_id', sa.Integer(), sa.ForeignKey('user_profiles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(10), nullable=False),
        sa.Column('invited_by_id', sa.Integer(), sa.ForeignKey('user_profiles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('invited_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
    )

    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.add_column(sa.Column('is_agent', sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.drop_column('role')

    connection.execute(text("PRAGMA foreign_keys=ON"))
