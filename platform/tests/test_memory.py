"""Tests for the memory system: service, models, and components."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from models.memory import MemoryEpisode, MemoryFact, MemoryProcedure, MemoryUser
from services.memory import MemoryService


# ── MemoryService Tests ───────────────────────────────────────────────────────


class TestMemoryServiceFacts:
    def test_set_and_get_fact(self, db):
        memory = MemoryService(db)

        # Set fact
        fact = memory.set_fact(
            key="test.key",
            value={"hello": "world"},
            fact_type="world_knowledge",
            scope="agent",
            agent_id="test_agent",
        )

        assert fact.id is not None
        assert fact.key == "test.key"

        # Get fact
        value = memory.get_fact(
            key="test.key",
            agent_id="test_agent",
        )

        assert value == {"hello": "world"}

    def test_scope_hierarchy(self, db):
        memory = MemoryService(db)

        # Set agent-level fact
        memory.set_fact(
            key="preference.style",
            value="verbose",
            fact_type="user_preference",
            scope="agent",
            agent_id="test_agent",
        )

        # Set user-level fact (should override)
        memory.set_fact(
            key="preference.style",
            value="concise",
            fact_type="user_preference",
            scope="user",
            user_id="test_user",
        )

        # Get with user context - should return user-level
        value = memory.get_fact(
            key="preference.style",
            agent_id="test_agent",
            user_id="test_user",
        )
        assert value == "concise"

        # Get without user context - should return agent-level
        value = memory.get_fact(
            key="preference.style",
            agent_id="test_agent",
        )
        assert value == "verbose"

    def test_set_fact_overwrite(self, db):
        memory = MemoryService(db)

        # Set initial fact
        fact1 = memory.set_fact(
            key="counter",
            value=1,
            fact_type="world_knowledge",
            scope="agent",
            agent_id="test_agent",
        )

        # Overwrite with new value
        fact2 = memory.set_fact(
            key="counter",
            value=2,
            fact_type="world_knowledge",
            scope="agent",
            agent_id="test_agent",
            overwrite=True,
        )

        # Should be the same fact, updated
        assert fact1.id == fact2.id
        assert fact2.times_confirmed == 2
        assert memory.get_fact(key="counter", agent_id="test_agent") == 2

    def test_set_fact_no_overwrite(self, db):
        memory = MemoryService(db)

        # Set initial fact
        memory.set_fact(
            key="readonly",
            value="original",
            fact_type="world_knowledge",
            scope="agent",
            agent_id="test_agent",
        )

        # Try to overwrite with overwrite=False
        memory.set_fact(
            key="readonly",
            value="updated",
            fact_type="world_knowledge",
            scope="agent",
            agent_id="test_agent",
            overwrite=False,
        )

        # Should still be original
        assert memory.get_fact(key="readonly", agent_id="test_agent") == "original"

    def test_search_facts(self, db):
        memory = MemoryService(db)

        # Create several facts
        memory.set_fact(
            key="user.name",
            value="Alice",
            fact_type="user_preference",
            scope="agent",
            agent_id="test_agent",
        )
        memory.set_fact(
            key="user.email",
            value="alice@example.com",
            fact_type="user_preference",
            scope="agent",
            agent_id="test_agent",
        )
        memory.set_fact(
            key="system.config",
            value="production",
            fact_type="world_knowledge",
            scope="agent",
            agent_id="test_agent",
        )

        # Search for user-related facts
        results = memory.search_facts(
            query="user",
            agent_id="test_agent",
        )

        # Should find the two user.* facts
        assert len(results) >= 2
        keys = [f.key for f in results]
        assert "user.name" in keys
        assert "user.email" in keys

    def test_get_user_facts(self, db):
        memory = MemoryService(db)

        # Create user-scoped facts
        memory.set_fact(
            key="timezone",
            value="UTC",
            fact_type="user_preference",
            scope="user",
            user_id="user123",
        )
        memory.set_fact(
            key="language",
            value="en",
            fact_type="user_preference",
            scope="user",
            user_id="user123",
        )

        facts = memory.get_user_facts(user_id="user123")

        assert len(facts) == 2


class TestMemoryServiceEpisodes:
    def test_log_and_complete_episode(self, db):
        memory = MemoryService(db)

        # Start episode
        episode = memory.log_episode(
            agent_id="test_agent",
            trigger_type="telegram",
            trigger_input={"message": {"text": "hello"}},
            user_id="test_user",
        )

        assert episode.id is not None
        assert episode.success is False  # Not completed yet

        # Complete episode
        memory.complete_episode(
            episode_id=episode.id,
            success=True,
            final_output={"response": "Hi there!"},
            conversation=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            actions_taken=[],
        )

        # Verify
        db.refresh(episode)
        assert episode.success is True
        assert episode.duration_ms is not None
        assert episode.final_output == {"response": "Hi there!"}

    def test_complete_episode_with_error(self, db):
        memory = MemoryService(db)

        episode = memory.log_episode(
            agent_id="test_agent",
            trigger_type="manual",
            trigger_input={},
        )

        memory.complete_episode(
            episode_id=episode.id,
            success=False,
            final_output=None,
            error_code="RuntimeError",
            error_message="Something went wrong",
        )

        db.refresh(episode)
        assert episode.success is False
        assert episode.error_code == "RuntimeError"
        assert episode.error_message == "Something went wrong"

    def test_get_recent_episodes(self, db):
        memory = MemoryService(db)

        # Create several episodes
        for i in range(5):
            ep = memory.log_episode(
                agent_id="test_agent",
                trigger_type="manual",
                trigger_input={"index": i},
            )
            memory.complete_episode(
                episode_id=ep.id,
                success=True,
                final_output={"index": i},
            )

        episodes = memory.get_recent_episodes(agent_id="test_agent", limit=3)

        assert len(episodes) == 3

    def test_add_action_to_episode(self, db):
        memory = MemoryService(db)

        episode = memory.log_episode(
            agent_id="test_agent",
            trigger_type="manual",
            trigger_input={},
        )

        memory.add_action_to_episode(
            episode_id=episode.id,
            action={"node_id": "node_1", "tool": "web_search", "duration_ms": 150},
        )

        db.refresh(episode)
        assert len(episode.actions_taken) == 1
        assert episode.actions_taken[0]["node_id"] == "node_1"

    def test_add_message_to_episode(self, db):
        memory = MemoryService(db)

        episode = memory.log_episode(
            agent_id="test_agent",
            trigger_type="manual",
            trigger_input={},
        )

        memory.add_message_to_episode(episode.id, "user", "Hello")
        memory.add_message_to_episode(episode.id, "assistant", "Hi there!")

        db.refresh(episode)
        assert len(episode.conversation) == 2
        assert episode.conversation[0]["role"] == "user"
        assert episode.conversation[1]["role"] == "assistant"


class TestMemoryServiceUsers:
    def test_get_or_create_user_telegram(self, db):
        memory = MemoryService(db)

        # First interaction
        user1 = memory.get_or_create_user(
            channel="telegram",
            channel_id="123456",
            display_name="Test User",
        )

        assert user1.canonical_id == "telegram:123456"
        assert user1.telegram_id == "123456"
        assert user1.display_name == "Test User"

        # Second interaction - same user
        user2 = memory.get_or_create_user(
            channel="telegram",
            channel_id="123456",
        )

        assert user2.id == user1.id

    def test_get_or_create_user_email(self, db):
        memory = MemoryService(db)

        user = memory.get_or_create_user(
            channel="email",
            channel_id="test@example.com",
            display_name="Email User",
        )

        assert user.canonical_id == "email:test@example.com"
        assert user.email == "test@example.com"

    def test_get_user_context(self, db):
        memory = MemoryService(db)

        # Create user
        user = memory.get_or_create_user(
            channel="telegram",
            channel_id="789",
            display_name="Context User",
        )

        # Add some facts
        memory.set_fact(
            key="preference",
            value="concise",
            fact_type="user_preference",
            scope="user",
            user_id=user.canonical_id,
        )

        # Get context
        context = memory.get_user_context(
            user_id=user.canonical_id,
            agent_id="test_agent",
        )

        assert context["user_id"] == user.canonical_id
        assert context["is_new"] is False
        assert len(context["facts"]) >= 1

    def test_increment_user_conversations(self, db):
        memory = MemoryService(db)

        user = memory.get_or_create_user(
            channel="telegram",
            channel_id="456",
        )
        assert user.total_conversations == 0

        memory.increment_user_conversations(user.canonical_id)

        db.refresh(user)
        assert user.total_conversations == 1

    def test_update_user_preferences(self, db):
        memory = MemoryService(db)

        user = memory.get_or_create_user(
            channel="telegram",
            channel_id="999",
        )

        memory.update_user_preferences(
            user_id=user.canonical_id,
            preferences={"theme": "dark", "language": "en"},
        )

        db.refresh(user)
        assert user.preferences_cache["theme"] == "dark"
        assert user.preferences_cache["language"] == "en"


class TestMemoryServiceProcedures:
    def test_save_and_get_procedure(self, db):
        memory = MemoryService(db)

        proc = memory.save_procedure(
            name="greet_user",
            description="Greet the user warmly",
            procedure_type="prompt_template",
            procedure_content={"template": "Hello, {name}!"},
            agent_id="test_agent",
            trigger_conditions={"goal_contains": ["greet", "hello"]},
        )

        assert proc.id is not None

        retrieved = memory.get_procedure(
            name="greet_user",
            agent_id="test_agent",
        )

        assert retrieved is not None
        assert retrieved.name == "greet_user"
        assert retrieved.procedure_content == {"template": "Hello, {name}!"}

    def test_find_matching_procedure(self, db):
        memory = MemoryService(db)

        # Save a procedure
        memory.save_procedure(
            name="weather_check",
            description="Check the weather",
            procedure_type="tool_sequence",
            procedure_content=[{"tool": "web_search", "args": {"query": "weather"}}],
            agent_id="test_agent",
            trigger_conditions={"goal_contains": ["weather", "forecast"]},
        )

        # Find matching procedure
        proc = memory.find_matching_procedure(
            goal="What's the weather like today?",
            context={},
            agent_id="test_agent",
        )

        assert proc is not None
        assert proc.name == "weather_check"

    def test_find_matching_procedure_no_match(self, db):
        memory = MemoryService(db)

        memory.save_procedure(
            name="weather_check",
            description="Check the weather",
            procedure_type="tool_sequence",
            procedure_content=[],
            agent_id="test_agent",
            trigger_conditions={"goal_contains": ["weather"]},
        )

        proc = memory.find_matching_procedure(
            goal="Tell me a joke",
            context={},
            agent_id="test_agent",
        )

        assert proc is None

    def test_record_procedure_use(self, db):
        memory = MemoryService(db)

        proc = memory.save_procedure(
            name="test_proc",
            description="Test procedure",
            procedure_type="code_snippet",
            procedure_content={"code": "print('hello')"},
            agent_id="test_agent",
        )

        assert proc.times_used == 0

        memory.record_procedure_use(
            procedure_id=proc.id,
            success=True,
            duration_ms=100,
        )

        db.refresh(proc)
        assert proc.times_used == 1
        assert proc.times_succeeded == 1
        assert proc.avg_duration_ms == 100.0

        memory.record_procedure_use(
            procedure_id=proc.id,
            success=True,
            duration_ms=200,
        )

        db.refresh(proc)
        assert proc.times_used == 2
        assert proc.times_succeeded == 2
        assert proc.avg_duration_ms == 150.0  # (100 + 200) / 2

    def test_deactivate_procedure(self, db):
        memory = MemoryService(db)

        proc = memory.save_procedure(
            name="to_deactivate",
            description="Will be deactivated",
            procedure_type="prompt_template",
            procedure_content={},
            agent_id="test_agent",
        )

        assert proc.is_active is True

        memory.deactivate_procedure(proc.id)

        db.refresh(proc)
        assert proc.is_active is False

        # Should not be found anymore
        retrieved = memory.get_procedure(
            name="to_deactivate",
            agent_id="test_agent",
        )
        assert retrieved is None


# ── Memory Component Tests ────────────────────────────────────────────────────


class TestMemoryReadComponent:
    def test_memory_read_by_key(self, db):
        from components.memory_read import memory_read_factory

        # Setup: create a fact in global scope
        memory = MemoryService(db)
        memory.set_fact(
            key="test.fact",
            value="test_value",
            fact_type="world_knowledge",
            scope="global",
            agent_id="global",
        )

        # Create mock node
        node = MagicMock()
        node.node_id = "memory_read_1"
        node.component_config.extra_config = {"memory_type": "facts"}

        # Patch SessionLocal to return our test db
        with patch("components.memory_read.SessionLocal", return_value=db):
            recall_tool = memory_read_factory(node)
            result = recall_tool.invoke({"key": "test.fact"})

        assert "test.fact" in result
        assert "test_value" in result

    def test_memory_read_not_found(self, db):
        from components.memory_read import memory_read_factory

        node = MagicMock()
        node.node_id = "memory_read_1"
        node.component_config.extra_config = {}

        with patch("components.memory_read.SessionLocal", return_value=db):
            recall_tool = memory_read_factory(node)
            result = recall_tool.invoke({"key": "nonexistent.key"})

        assert "No memory found" in result


class TestMemoryWriteComponent:
    def test_memory_write_creates_fact(self, db):
        from components.memory_write import memory_write_factory

        node = MagicMock()
        node.node_id = "memory_write_1"
        node.component_config.extra_config = {
            "fact_type": "world_knowledge",
        }

        with patch("components.memory_write.SessionLocal", return_value=db):
            remember_tool = memory_write_factory(node)
            result = remember_tool.invoke({"key": "new.fact", "value": "new_value"})

        assert "Remembered" in result
        assert "new.fact" in result
        assert "new_value" in result

        # Verify fact was created in global scope
        memory = MemoryService(db)
        value = memory.get_fact(key="new.fact", agent_id="global")
        assert value == "new_value"

    def test_memory_write_missing_key(self, db):
        from components.memory_write import memory_write_factory

        node = MagicMock()
        node.node_id = "memory_write_1"
        node.component_config.extra_config = {}

        with patch("components.memory_write.SessionLocal", return_value=db):
            remember_tool = memory_write_factory(node)
            result = remember_tool.invoke({"key": "", "value": "some_value"})

        assert "Error" in result


class TestIdentifyUserComponent:
    def test_identify_telegram_user(self, db):
        from components.identify_user import identify_user_factory

        node = MagicMock()
        node.node_id = "identify_user_1"

        trigger_payload = {
            "message": {
                "from": {
                    "id": 123456789,
                    "first_name": "John",
                    "last_name": "Doe",
                }
            }
        }

        with patch("components.identify_user.SessionLocal", return_value=db):
            fn = identify_user_factory(node)
            result = fn({
                "trigger": trigger_payload,
                "execution_id": "test-123",
                "user_context": {},
                "node_outputs": {},
            })

        assert result["user_id"] == "telegram:123456789"
        assert result["_state_patch"]["user_context"]["channel"] == "telegram"

    def test_identify_new_user(self, db):
        from components.identify_user import identify_user_factory

        node = MagicMock()
        node.node_id = "identify_user_1"

        with patch("components.identify_user.SessionLocal", return_value=db):
            fn = identify_user_factory(node)
            result = fn({
                "trigger": {
                    "message": {
                        "from": {"id": 999888777, "first_name": "New"}
                    }
                },
                "execution_id": "test-123",
                "user_context": {},
                "node_outputs": {},
            })

        assert result["is_new_user"] is True


