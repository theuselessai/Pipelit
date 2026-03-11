"""rename telegram_user_id to external_user_id

Revision ID: 3993f4ab1bc0
Revises: 97895779df3d
Create Date: 2026-03-10 12:00:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "3993f4ab1bc0"
down_revision: Union[str, None] = "97895779df3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Copy data from old column to new column (idempotent)
    op.execute("UPDATE user_profiles SET external_user_id = telegram_user_id WHERE external_user_id IS NULL")

    # Drop the old unique constraint on telegram_user_id
    try:
        op.drop_constraint("uq_user_profiles_telegram_user_id", "user_profiles", type_="unique")
    except Exception:
        logger.info("Constraint uq_user_profiles_telegram_user_id does not exist, skipping")

    # Drop the old column
    try:
        op.drop_column("user_profiles", "telegram_user_id")
    except Exception:
        logger.info("Column telegram_user_id does not exist, skipping")

    # Create unique constraint on new column
    try:
        op.create_unique_constraint(
            "uq_user_profiles_external_user_id",
            "user_profiles",
            ["external_user_id"],
        )
    except Exception:
        logger.info("Constraint uq_user_profiles_external_user_id already exists, skipping")


def downgrade() -> None:
    # Add old column back
    try:
        op.add_column(
            "user_profiles",
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        )
    except Exception:
        logger.info("Column telegram_user_id already exists, skipping")

    # Copy data from new column to old column
    op.execute("UPDATE user_profiles SET telegram_user_id = external_user_id WHERE telegram_user_id IS NULL")

    # Drop the new unique constraint
    try:
        op.drop_constraint("uq_user_profiles_external_user_id", "user_profiles", type_="unique")
    except Exception:
        logger.info("Constraint uq_user_profiles_external_user_id does not exist, skipping")

    # Drop the new column
    try:
        op.drop_column("user_profiles", "external_user_id")
    except Exception:
        logger.info("Column external_user_id does not exist, skipping")

    # Recreate the old unique constraint
    try:
        op.create_unique_constraint(
            "uq_user_profiles_telegram_user_id",
            "user_profiles",
            ["telegram_user_id"],
        )
    except Exception:
        logger.info("Constraint uq_user_profiles_telegram_user_id already exists, skipping")
