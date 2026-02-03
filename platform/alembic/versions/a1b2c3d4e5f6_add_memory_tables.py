"""Add memory tables (episodes, facts, procedures, users)

Revision ID: a1b2c3d4e5f6
Revises: bc3b7ec815f1
Create Date: 2026-02-03
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "bc3b7ec815f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MemoryUser table
    op.create_table(
        "memory_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_id", sa.String(100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("telegram_id", sa.String(100), nullable=True, unique=True),
        sa.Column("telegram_username", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("merged_into_id", sa.String(36), sa.ForeignKey("memory_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("preferences_cache", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("total_conversations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_conversation_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_user_telegram", "memory_users", ["telegram_id"])
    op.create_index("ix_memory_user_email", "memory_users", ["email"])

    # MemoryEpisode table
    op.create_table(
        "memory_episodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("workflow_executions.execution_id", ondelete="SET NULL"), nullable=True),
        sa.Column("trigger_type", sa.String(50), nullable=False, server_default=""),
        sa.Column("trigger_input", sa.JSON(), nullable=True),
        sa.Column("conversation", sa.JSON(), nullable=True),
        sa.Column("actions_taken", sa.JSON(), nullable=True),
        sa.Column("final_output", sa.JSON(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("human_feedback", sa.Text(), nullable=True),
        sa.Column("human_rating", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("processed_for_facts", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_episodes_agent_id", "memory_episodes", ["agent_id"])
    op.create_index("ix_memory_episodes_user_id", "memory_episodes", ["user_id"])
    op.create_index("ix_memory_episodes_session_id", "memory_episodes", ["session_id"])
    op.create_index("ix_episode_agent_user", "memory_episodes", ["agent_id", "user_id"])
    op.create_index("ix_episode_agent_time", "memory_episodes", ["agent_id", "started_at"])
    op.create_index("ix_episode_user_time", "memory_episodes", ["user_id", "started_at"])

    # MemoryFact table
    op.create_table(
        "memory_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(20), nullable=False, server_default="agent"),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("user_id", sa.String(100), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("fact_type", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("times_confirmed", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("times_contradicted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_episode_id", sa.String(36), sa.ForeignKey("memory_episodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_description", sa.String(255), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed", sa.DateTime(), nullable=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_facts_agent_id", "memory_facts", ["agent_id"])
    op.create_index("ix_memory_facts_user_id", "memory_facts", ["user_id"])
    op.create_index("ix_memory_facts_session_id", "memory_facts", ["session_id"])
    op.create_index("ix_fact_scope_key", "memory_facts", ["scope", "agent_id", "user_id", "key"])
    op.create_index("ix_fact_agent_type", "memory_facts", ["agent_id", "fact_type"])
    op.create_index("ix_fact_user", "memory_facts", ["user_id", "fact_type"])

    # MemoryProcedure table
    op.create_table(
        "memory_procedures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("trigger_conditions", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("procedure_type", sa.String(50), nullable=False),
        sa.Column("procedure_content", sa.JSON(), nullable=False),
        sa.Column("times_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("times_succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("times_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_duration_ms", sa.Float(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="human_taught"),
        sa.Column("parent_procedure_id", sa.String(36), sa.ForeignKey("memory_procedures.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_procedures_agent_id", "memory_procedures", ["agent_id"])
    op.create_index("ix_memory_procedures_user_id", "memory_procedures", ["user_id"])
    op.create_index("ix_procedure_agent", "memory_procedures", ["agent_id", "is_active"])


def downgrade() -> None:
    op.drop_table("memory_procedures")
    op.drop_table("memory_facts")
    op.drop_table("memory_episodes")
    op.drop_table("memory_users")
