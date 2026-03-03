"""add is_preferred to tool_credentials

Revision ID: d31aa5f91a24
Revises: 34c15bdd588b
Create Date: 2026-03-03 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d31aa5f91a24"
down_revision: Union[str, None] = "34c15bdd588b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tool_credentials",
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("tool_credentials", "is_preferred")
