"""multi_key_api_key_management

Revision ID: c5d6e7f8a9b0
Revises: b4c2e8f1a903
Create Date: 2026-03-13 00:00:00.000000

Migrate APIKey from 1:1 to many-to-one with UserProfile.
Add name, prefix, last_used_at, expires_at, is_active columns.
Existing keys get name='default' and prefix from first 8 chars of key.
Drop unique constraint on user_id.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b4c2e8f1a903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(text("PRAGMA foreign_keys=OFF"))

    # SQLite requires batch mode to alter constraints.
    # The initial migration creates UniqueConstraint('user_id') without a name,
    # so we must pass naming_convention to let Alembic resolve it by convention.
    naming_convention = {
        "uq": "uq_%(table_name)s_%(column_0_name)s",
    }
    with op.batch_alter_table("api_keys", naming_convention=naming_convention) as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(100), nullable=False, server_default="default"))
        batch_op.add_column(sa.Column("prefix", sa.String(8), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("last_used_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"))
        # Drop the unique constraint on user_id (1:1 → many-to-one)
        batch_op.drop_constraint("uq_api_keys_user_id", type_="unique")

    # Backfill prefix from first 8 chars of existing key values
    connection.execute(text("UPDATE api_keys SET prefix = SUBSTR(key, 1, 8) WHERE prefix = ''"))

    connection.execute(text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(text("PRAGMA foreign_keys=OFF"))

    # Keep only the newest API key per user before restoring unique constraint
    connection.execute(text("""
        DELETE FROM api_keys WHERE id NOT IN (
            SELECT MAX(id) FROM api_keys GROUP BY user_id
        )
    """))

    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_column("name")
        batch_op.drop_column("prefix")
        batch_op.drop_column("last_used_at")
        batch_op.drop_column("expires_at")
        batch_op.drop_column("is_active")
        batch_op.create_unique_constraint("uq_api_keys_user_id", ["user_id"])

    connection.execute(text("PRAGMA foreign_keys=ON"))
