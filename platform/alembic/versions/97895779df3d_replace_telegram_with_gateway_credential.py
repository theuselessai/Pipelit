"""replace telegram_credential with gateway_credential

Revision ID: 97895779df3d
Revises: d31aa5f91a24
Create Date: 2026-03-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "97895779df3d"
down_revision: Union[str, None] = "d31aa5f91a24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Delete all telegram credentials from the credentials table
    op.execute("DELETE FROM credentials WHERE credential_type='telegram'")
    
    # Drop the telegram_credentials table
    op.drop_table("telegram_credentials")
    
    # Create the gateway_credentials table
    op.create_table(
        "gateway_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("base_credentials_id", sa.Integer(), nullable=False),
        sa.Column("gateway_credential_id", sa.String(255), nullable=False),
        sa.Column("adapter_type", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(["base_credentials_id"], ["credentials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("base_credentials_id"),
    )


def downgrade() -> None:
    # Drop the gateway_credentials table
    op.drop_table("gateway_credentials")
    
    # Recreate the telegram_credentials table
    op.create_table(
        "telegram_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("base_credentials_id", sa.Integer(), nullable=False),
        sa.Column("bot_token", sa.String(500), nullable=False),
        sa.Column("allowed_user_ids", sa.String(500), nullable=True, server_default=""),
        sa.ForeignKeyConstraint(["base_credentials_id"], ["credentials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("base_credentials_id"),
    )
