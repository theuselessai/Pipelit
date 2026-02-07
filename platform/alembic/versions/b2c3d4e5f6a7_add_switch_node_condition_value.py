"""Add condition_value to workflow_edges for switch node routing

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-06
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "00bb091e6dd1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_edges",
        sa.Column("condition_value", sa.String(100), server_default="", nullable=False),
    )

    # Migrate existing conditional edges: expand condition_mapping into individual edges
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, workflow_id, source_node_id, edge_type, edge_label, "
            "condition_mapping, priority FROM workflow_edges "
            "WHERE edge_type = 'conditional' AND condition_mapping IS NOT NULL"
        )
    ).fetchall()

    for row in rows:
        import json
        mapping = row[5]
        if isinstance(mapping, str):
            mapping = json.loads(mapping)
        if not isinstance(mapping, dict) or not mapping:
            continue

        # Create individual edges for each mapping entry
        for route_val, target_id in mapping.items():
            if target_id:
                conn.execute(
                    sa.text(
                        "INSERT INTO workflow_edges "
                        "(workflow_id, source_node_id, target_node_id, edge_type, "
                        "edge_label, condition_value, priority) "
                        "VALUES (:wf_id, :src, :tgt, 'conditional', :label, :cv, :pri)"
                    ),
                    {
                        "wf_id": row[1],
                        "src": row[2],
                        "tgt": target_id,
                        "label": row[4] or "",
                        "cv": route_val,
                        "pri": row[6] or 0,
                    },
                )

        # Delete the original edge with condition_mapping
        conn.execute(
            sa.text("DELETE FROM workflow_edges WHERE id = :eid"),
            {"eid": row[0]},
        )


def downgrade() -> None:
    op.drop_column("workflow_edges", "condition_value")
