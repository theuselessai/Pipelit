"""Memory system models: Episodes, Facts, Procedures, and Users."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class MemoryEpisode(Base):
    """
    Full record of a past execution - the agent's "episodic memory."
    Like remembering "that conversation last Tuesday."

    Future use:
    - Semantic search via embeddings
    - Pattern extraction for procedures
    - Training data for self-improvement
    """

    __tablename__ = "memory_episodes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Scoping
    agent_id: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_executions.execution_id", ondelete="SET NULL"), nullable=True
    )

    # What triggered it
    trigger_type: Mapped[str] = mapped_column(String(50), default="")
    trigger_input: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # What happened
    conversation: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    actions_taken: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    final_output: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    # Outcome
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    human_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timing
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # For retrieval (Phase 7 - embeddings for semantic search)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Processing state
    processed_for_facts: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    workflow: Mapped["Workflow | None"] = relationship("Workflow")  # noqa: F821
    execution: Mapped["WorkflowExecution | None"] = relationship("WorkflowExecution")  # noqa: F821

    __table_args__ = (
        Index("ix_episode_agent_user", "agent_id", "user_id"),
        Index("ix_episode_agent_time", "agent_id", "started_at"),
        Index("ix_episode_user_time", "user_id", "started_at"),
    )

    def __repr__(self):
        return f"<MemoryEpisode {self.id[:8]} agent={self.agent_id}>"


class MemoryFact(Base):
    """
    Extracted knowledge, not tied to specific episode - the agent's "semantic memory."
    Like knowing "Paris is the capital of France."

    Scope hierarchy (most specific wins):
    - session: Only this conversation
    - user: This user across all conversations
    - agent: This agent across all users
    - global: All agents, all users

    Future use:
    - Confidence decay over time
    - Contradiction detection
    - Semantic clustering
    """

    __tablename__ = "memory_facts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Scoping - hierarchical
    scope: Mapped[str] = mapped_column(String(20), default="agent")
    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # The knowledge
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[Any] = mapped_column(JSON)

    # Classification
    # Types:
    # - user_preference: "user likes concise answers"
    # - world_knowledge: "API endpoint is X"
    # - self_knowledge: "my success rate for X is 73%"
    # - correction: "don't do X, do Y instead"
    # - relationship: "user works at Zerocap"
    fact_type: Mapped[str] = mapped_column(String(50))

    # Confidence tracking
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    times_confirmed: Mapped[int] = mapped_column(Integer, default=1)
    times_contradicted: Mapped[int] = mapped_column(Integer, default=0)

    # Provenance
    source_episode_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_episodes.id", ondelete="SET NULL"), nullable=True
    )
    source_description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Usage tracking
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # For retrieval (Phase 7 - embeddings for semantic search)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    source_episode: Mapped["MemoryEpisode | None"] = relationship("MemoryEpisode")

    __table_args__ = (
        Index("ix_fact_scope_key", "scope", "agent_id", "user_id", "key"),
        Index("ix_fact_agent_type", "agent_id", "fact_type"),
        Index("ix_fact_user", "user_id", "fact_type"),
    )

    def __repr__(self):
        return f"<MemoryFact {self.key} scope={self.scope}>"


class MemoryProcedure(Base):
    """
    Learned procedures / reusable patterns - the agent's "procedural memory."
    Like knowing "how to ride a bike."

    These emerge from:
    - Human teaching ("when X, do Y")
    - Pattern extraction from successful episodes
    - Agent self-discovery

    Future use:
    - Auto-trigger matching
    - Success rate optimization
    - Procedure composition
    """

    __tablename__ = "memory_procedures"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Scoping
    agent_id: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Identity
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")

    # When to use
    # Examples:
    # {"goal_contains": ["weather"], "has_location": true}
    # {"message_type": "question", "topic": "code"}
    # {"time_of_day": "morning", "user_mood": "rushed"}
    trigger_conditions: Mapped[dict] = mapped_column(JSON, default=dict)

    # What to do
    # Types:
    # - workflow_graph: Saved node structure
    # - prompt_template: Text template with variables
    # - code_snippet: Executable code
    # - tool_sequence: Ordered list of tool calls
    procedure_type: Mapped[str] = mapped_column(String(50))

    # Content varies by type:
    # workflow_graph: {nodes: [...], edges: [...]}
    # prompt_template: {template: "...", variables: [...]}
    # code_snippet: {language: "python", code: "..."}
    # tool_sequence: [{tool: "...", args: {...}}, ...]
    procedure_content: Mapped[dict] = mapped_column(JSON)

    # Performance tracking
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    times_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    times_failed: Mapped[int] = mapped_column(Integer, default=0)
    avg_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # How it was learned
    # Sources:
    # - human_taught: Explicit instruction
    # - self_learned: Extracted from episodes
    # - evolved: Modified from another procedure
    source: Mapped[str] = mapped_column(String(50), default="human_taught")

    parent_procedure_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_procedures.id", ondelete="SET NULL"), nullable=True
    )

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    parent_procedure: Mapped["MemoryProcedure | None"] = relationship(
        "MemoryProcedure", remote_side="MemoryProcedure.id"
    )

    __table_args__ = (Index("ix_procedure_agent", "agent_id", "is_active"),)

    @property
    def success_rate(self) -> float:
        """Calculate success rate, defaulting to 0.5 for unused procedures."""
        if self.times_used == 0:
            return 0.5
        return self.times_succeeded / self.times_used

    def __repr__(self):
        return f"<MemoryProcedure {self.name} agent={self.agent_id}>"


class MemoryUser(Base):
    """
    Known users across all channels.
    Allows same person on Telegram + Email to be recognized.

    Future use:
    - Cross-channel identity resolution
    - Preference caching for fast lookup
    - User segmentation
    """

    __tablename__ = "memory_users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Canonical identity
    canonical_id: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Channel-specific identifiers (can add more later)
    telegram_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    # Merged profiles (if same person identified on multiple channels)
    merged_into_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_users.id", ondelete="SET NULL"), nullable=True
    )

    # Cached preferences (denormalized from facts for speed)
    # Example: {"response_style": "concise", "timezone": "Australia/Adelaide"}
    preferences_cache: Mapped[dict] = mapped_column(JSON, default=dict)

    # Stats
    total_conversations: Mapped[int] = mapped_column(Integer, default=0)
    last_conversation_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    merged_into: Mapped["MemoryUser | None"] = relationship(
        "MemoryUser", remote_side="MemoryUser.id"
    )

    __table_args__ = (
        Index("ix_memory_user_telegram", "telegram_id"),
        Index("ix_memory_user_email", "email"),
    )

    def __repr__(self):
        return f"<MemoryUser {self.canonical_id}>"
