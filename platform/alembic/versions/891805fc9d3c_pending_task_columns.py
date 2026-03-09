"""pending_task_columns

Revision ID: 891805fc9d3c
Revises: 3993f4ab1bc0
Create Date: 2026-03-10 01:43:11.389202

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '891805fc9d3c'
down_revision: Union[str, Sequence[str], None] = '3993f4ab1bc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns to pending_tasks
    op.add_column('pending_tasks', sa.Column('chat_id', sa.String(length=255), nullable=True))
    op.add_column('pending_tasks', sa.Column('credential_id', sa.String(length=255), nullable=True))
    
    # Copy data from telegram_chat_id to chat_id (convert BigInteger to String)
    op.execute("UPDATE pending_tasks SET chat_id = CAST(telegram_chat_id AS TEXT)")
    
    # Drop the old column
    op.drop_column('pending_tasks', 'telegram_chat_id')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('pending_tasks', sa.Column('telegram_chat_id', sa.BIGINT(), nullable=False))
    op.execute("UPDATE pending_tasks SET telegram_chat_id = CAST(chat_id AS INTEGER)")
    op.drop_column('pending_tasks', 'credential_id')
    op.drop_column('pending_tasks', 'chat_id')
