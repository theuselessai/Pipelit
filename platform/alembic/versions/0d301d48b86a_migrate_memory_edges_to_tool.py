"""Migrate memory edges to tool edges.

Revision ID: 0d301d48b86a
Revises: ab94b16af1a9
Create Date: 2026-02-19
"""

from alembic import op

revision = "0d301d48b86a"
down_revision = "ab94b16af1a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE workflow_edges SET edge_label = 'tool' WHERE edge_label = 'memory'")


def downgrade() -> None:
    raise NotImplementedError(
        "Cannot reliably reverse this migration — 'memory' edges have been converted to 'tool' edges. "
        "Manual intervention required to restore original edge_label values if needed."
    )
