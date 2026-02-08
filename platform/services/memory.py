"""MemoryService — Central service for all memory operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from models.memory import MemoryEpisode, MemoryFact, MemoryProcedure, MemoryUser

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Central service for all memory operations.

    Design principles:
    - Scope hierarchy: session > user > agent > global
    - Confidence tracking for facts
    - Usage tracking for optimization
    - Extensible for future semantic search
    """

    def __init__(self, db: Session):
        self.db = db

    # ========== FACTS ==========

    def get_fact(
        self,
        key: str,
        agent_id: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> Any | None:
        """
        Get fact by key with scope hierarchy.
        Most specific scope wins.
        """
        # Try session first
        if session_id:
            fact = self._find_fact(key, scope="session", session_id=session_id)
            if fact:
                self._record_access(fact)
                return fact.value

        # Then user
        if user_id:
            fact = self._find_fact(key, scope="user", user_id=user_id)
            if fact:
                self._record_access(fact)
                return fact.value

        # Then agent
        fact = self._find_fact(key, scope="agent", agent_id=agent_id)
        if fact:
            self._record_access(fact)
            return fact.value

        # Finally global
        fact = self._find_fact(key, scope="global")
        if fact:
            self._record_access(fact)
            return fact.value

        return None

    def _find_fact(
        self,
        key: str,
        scope: str,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> MemoryFact | None:
        """Find a single fact matching scope criteria."""
        stmt = select(MemoryFact).where(
            MemoryFact.key == key,
            MemoryFact.scope == scope,
        )

        if scope == "agent":
            stmt = stmt.where(MemoryFact.agent_id == agent_id)
        elif scope == "user":
            stmt = stmt.where(MemoryFact.user_id == user_id)
        elif scope == "session":
            stmt = stmt.where(MemoryFact.session_id == session_id)

        return self.db.execute(stmt).scalar_one_or_none()

    def _record_access(self, fact: MemoryFact) -> None:
        """Track fact access for usage analytics."""
        fact.access_count += 1
        fact.last_accessed = datetime.now(timezone.utc)
        self.db.commit()

    def set_fact(
        self,
        key: str,
        value: Any,
        fact_type: str,
        scope: str = "agent",
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        source_episode_id: str | None = None,
        source_description: str | None = None,
        overwrite: bool = True,
    ) -> MemoryFact:
        """
        Store a fact with appropriate scoping.
        """
        existing = self._find_fact(
            key,
            scope,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
        )

        if existing:
            if overwrite:
                existing.value = value
                existing.times_confirmed += 1
                existing.updated_at = datetime.now(timezone.utc)
                self.db.commit()
                return existing
            else:
                return existing

        fact = MemoryFact(
            key=key,
            value=value,
            fact_type=fact_type,
            scope=scope,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            source_episode_id=source_episode_id,
            source_description=source_description,
        )
        self.db.add(fact)
        self.db.commit()
        return fact

    def search_facts(
        self,
        query: str,
        agent_id: str,
        user_id: str | None = None,
        fact_types: list[str] | None = None,
        limit: int = 10,
        min_confidence: float = 0.5,
    ) -> list[MemoryFact]:
        """
        Search facts by text matching.
        TODO: Replace with vector search in Phase 7.
        """
        # Build scope conditions
        scope_conditions = [MemoryFact.scope == "global"]
        scope_conditions.append(
            and_(MemoryFact.scope == "agent", MemoryFact.agent_id == agent_id)
        )
        if user_id:
            scope_conditions.append(
                and_(MemoryFact.scope == "user", MemoryFact.user_id == user_id)
            )

        stmt = (
            select(MemoryFact)
            .where(
                MemoryFact.confidence >= min_confidence,
                or_(*scope_conditions),
                or_(
                    MemoryFact.key.ilike(f"%{query}%"),
                    # Note: JSON value search is basic - will be replaced with vector search
                ),
            )
            .order_by(MemoryFact.confidence.desc())
            .limit(limit)
        )

        if fact_types:
            stmt = stmt.where(MemoryFact.fact_type.in_(fact_types))

        return list(self.db.execute(stmt).scalars().all())

    def get_user_facts(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[MemoryFact]:
        """Get all facts about a specific user."""
        stmt = (
            select(MemoryFact)
            .where(
                MemoryFact.user_id == user_id,
                MemoryFact.scope == "user",
            )
            .order_by(MemoryFact.access_count.desc())
            .limit(limit)
        )

        return list(self.db.execute(stmt).scalars().all())

    def delete_fact(self, fact_id: str) -> bool:
        """Delete a fact by ID."""
        fact = self.db.get(MemoryFact, fact_id)
        if not fact:
            return False
        self.db.delete(fact)
        self.db.commit()
        return True

    # ========== EPISODES ==========

    def log_episode(
        self,
        agent_id: str,
        trigger_type: str,
        trigger_input: dict | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        workflow_id: int | None = None,
        execution_id: str | None = None,
    ) -> MemoryEpisode:
        """Start logging a new episode."""
        episode = MemoryEpisode(
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            workflow_id=workflow_id,
            execution_id=execution_id,
            trigger_type=trigger_type,
            trigger_input=trigger_input,
            conversation=[],
            actions_taken=[],
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(episode)
        self.db.commit()
        return episode

    def complete_episode(
        self,
        episode_id: str,
        success: bool,
        final_output: Any,
        conversation: list[dict] | None = None,
        actions_taken: list[dict] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Complete an episode with results."""
        episode = self.db.get(MemoryEpisode, episode_id)
        if not episode:
            logger.warning(f"Episode {episode_id} not found for completion")
            return

        episode.success = success
        episode.final_output = final_output
        episode.conversation = conversation or []
        episode.actions_taken = actions_taken or []
        episode.error_code = error_code
        episode.error_message = error_message or ""
        episode.ended_at = datetime.now(timezone.utc)
        episode.duration_ms = int(
            (episode.ended_at - episode.started_at).total_seconds() * 1000
        )

        self.db.commit()

    def add_action_to_episode(
        self,
        episode_id: str,
        action: dict,
    ) -> None:
        """Add an action to an in-progress episode."""
        episode = self.db.get(MemoryEpisode, episode_id)
        if not episode:
            return

        actions = episode.actions_taken or []
        actions.append(action)
        episode.actions_taken = actions
        self.db.commit()

    def add_message_to_episode(
        self,
        episode_id: str,
        role: str,
        content: str,
    ) -> None:
        """Add a message to an episode's conversation."""
        episode = self.db.get(MemoryEpisode, episode_id)
        if not episode:
            return

        conversation = list(episode.conversation or [])
        conversation.append({"role": role, "content": content})
        episode.conversation = conversation
        self.db.commit()

    def get_recent_episodes(
        self,
        agent_id: str,
        user_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryEpisode]:
        """Get recent episodes for context."""
        stmt = select(MemoryEpisode).where(
            MemoryEpisode.agent_id == agent_id,
        )

        if user_id:
            stmt = stmt.where(MemoryEpisode.user_id == user_id)

        stmt = stmt.order_by(MemoryEpisode.started_at.desc()).limit(limit)

        return list(self.db.execute(stmt).scalars().all())

    def get_episode(self, episode_id: str) -> MemoryEpisode | None:
        """Get a specific episode by ID."""
        return self.db.get(MemoryEpisode, episode_id)

    # ========== USERS ==========

    def get_or_create_user(
        self,
        channel: str,
        channel_id: str,
        display_name: str | None = None,
    ) -> MemoryUser:
        """
        Get or create user by channel identifier.
        """
        # Build canonical ID
        canonical_id = f"{channel}:{channel_id}"

        # Try to find existing
        user = None
        if channel == "telegram":
            user = self.db.execute(
                select(MemoryUser).where(MemoryUser.telegram_id == channel_id)
            ).scalar_one_or_none()
        elif channel == "email":
            user = self.db.execute(
                select(MemoryUser).where(MemoryUser.email == channel_id)
            ).scalar_one_or_none()
        else:
            user = self.db.execute(
                select(MemoryUser).where(MemoryUser.canonical_id == canonical_id)
            ).scalar_one_or_none()

        if user:
            user.last_seen_at = datetime.now(timezone.utc)
            if display_name and not user.display_name:
                user.display_name = display_name
            self.db.commit()
            return user

        # Create new user
        user = MemoryUser(
            canonical_id=canonical_id,
            display_name=display_name,
            telegram_id=channel_id if channel == "telegram" else None,
            email=channel_id if channel == "email" else None,
        )
        self.db.add(user)
        self.db.commit()
        return user

    def get_user_by_canonical_id(self, canonical_id: str) -> MemoryUser | None:
        """Get user by canonical ID."""
        return self.db.execute(
            select(MemoryUser).where(MemoryUser.canonical_id == canonical_id)
        ).scalar_one_or_none()

    def get_user_context(
        self,
        user_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        """
        Build full context for a user.
        Used by pre-execution memory workflow.
        """
        user = self.db.execute(
            select(MemoryUser).where(MemoryUser.canonical_id == user_id)
        ).scalar_one_or_none()

        if not user:
            return {"user_id": user_id, "is_new": True, "facts": [], "history": []}

        facts = self.get_user_facts(user_id, limit=20)
        episodes = self.get_recent_episodes(agent_id, user_id=user_id, limit=5)

        return {
            "user_id": user_id,
            "is_new": False,
            "display_name": user.display_name,
            "preferences": user.preferences_cache,
            "facts": [
                {"key": f.key, "value": f.value, "type": f.fact_type} for f in facts
            ],
            "history": [
                {
                    "summary": e.summary or "No summary",
                    "success": e.success,
                    "when": e.started_at.isoformat(),
                }
                for e in episodes
            ],
            "total_conversations": user.total_conversations,
            "first_seen": user.first_seen_at.isoformat(),
        }

    def update_user_preferences(
        self,
        user_id: str,
        preferences: dict[str, Any],
    ) -> bool:
        """Update cached preferences for a user."""
        user = self.get_user_by_canonical_id(user_id)
        if not user:
            return False

        current = user.preferences_cache or {}
        current.update(preferences)
        user.preferences_cache = current
        self.db.commit()
        return True

    def increment_user_conversations(self, user_id: str) -> None:
        """Increment conversation count for a user."""
        user = self.get_user_by_canonical_id(user_id)
        if user:
            user.total_conversations += 1
            user.last_conversation_at = datetime.now(timezone.utc)
            self.db.commit()

    # ========== PROCEDURES ==========

    def get_procedure(
        self,
        name: str,
        agent_id: str,
    ) -> MemoryProcedure | None:
        """Get a specific procedure by name."""
        return self.db.execute(
            select(MemoryProcedure).where(
                MemoryProcedure.name == name,
                MemoryProcedure.agent_id == agent_id,
                MemoryProcedure.is_active == True,  # noqa: E712
            )
        ).scalar_one_or_none()

    def find_matching_procedure(
        self,
        goal: str,
        context: dict,
        agent_id: str,
        user_id: str | None = None,
    ) -> MemoryProcedure | None:
        """
        Find a procedure that matches current goal/context.
        Simple keyword matching for now.
        TODO: Replace with smarter matching in later phases.
        """
        stmt = (
            select(MemoryProcedure)
            .where(
                MemoryProcedure.agent_id == agent_id,
                MemoryProcedure.is_active == True,  # noqa: E712
            )
            .order_by(MemoryProcedure.times_succeeded.desc())
        )

        procedures = self.db.execute(stmt).scalars().all()

        for proc in procedures:
            if self._matches_conditions(proc.trigger_conditions, goal, context):
                return proc

        return None

    def _matches_conditions(
        self,
        conditions: dict,
        goal: str,
        context: dict,
    ) -> bool:
        """Check if goal/context matches procedure conditions."""
        if not conditions:
            return False

        goal_lower = goal.lower()

        # Check goal_contains
        if "goal_contains" in conditions:
            keywords = conditions["goal_contains"]
            if isinstance(keywords, list):
                if not any(kw.lower() in goal_lower for kw in keywords):
                    return False
            elif isinstance(keywords, str):
                if keywords.lower() not in goal_lower:
                    return False

        # Check context_has
        if "context_has" in conditions:
            required_keys = conditions["context_has"]
            if isinstance(required_keys, list):
                for key in required_keys:
                    if key not in context:
                        return False

        return True

    def save_procedure(
        self,
        name: str,
        description: str,
        procedure_type: str,
        procedure_content: dict,
        agent_id: str,
        trigger_conditions: dict | None = None,
        source: str = "human_taught",
        user_id: str | None = None,
    ) -> MemoryProcedure:
        """Save a new procedure."""
        procedure = MemoryProcedure(
            name=name,
            description=description,
            procedure_type=procedure_type,
            procedure_content=procedure_content,
            agent_id=agent_id,
            user_id=user_id,
            trigger_conditions=trigger_conditions or {},
            source=source,
        )
        self.db.add(procedure)
        self.db.commit()
        return procedure

    def record_procedure_use(
        self,
        procedure_id: str,
        success: bool,
        duration_ms: int | None = None,
    ) -> None:
        """Record that a procedure was used."""
        procedure = self.db.get(MemoryProcedure, procedure_id)
        if not procedure:
            return

        procedure.times_used += 1
        if success:
            procedure.times_succeeded += 1
        else:
            procedure.times_failed += 1

        procedure.last_used_at = datetime.now(timezone.utc)

        if duration_ms is not None:
            if procedure.avg_duration_ms:
                # Running average
                procedure.avg_duration_ms = (
                    procedure.avg_duration_ms * (procedure.times_used - 1) + duration_ms
                ) / procedure.times_used
            else:
                procedure.avg_duration_ms = float(duration_ms)

        self.db.commit()

    def list_procedures(
        self,
        agent_id: str,
        active_only: bool = True,
        limit: int = 50,
    ) -> list[MemoryProcedure]:
        """List procedures for an agent."""
        stmt = select(MemoryProcedure).where(MemoryProcedure.agent_id == agent_id)

        if active_only:
            stmt = stmt.where(MemoryProcedure.is_active == True)  # noqa: E712

        stmt = stmt.order_by(MemoryProcedure.times_used.desc()).limit(limit)

        return list(self.db.execute(stmt).scalars().all())

    def deactivate_procedure(self, procedure_id: str) -> bool:
        """Deactivate a procedure."""
        procedure = self.db.get(MemoryProcedure, procedure_id)
        if not procedure:
            return False
        procedure.is_active = False
        self.db.commit()
        return True
