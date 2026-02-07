"""Tests for services/memory.py — MemoryService."""

from __future__ import annotations

import pytest

from models.memory import MemoryEpisode, MemoryFact, MemoryProcedure, MemoryUser
from services.memory import MemoryService


class TestFactOperations:
    def test_set_and_get_fact(self, db):
        svc = MemoryService(db)
        svc.set_fact("name", "Alice", fact_type="identity", agent_id="a1", scope="agent")
        result = svc.get_fact("name", agent_id="a1")
        assert result == "Alice"

    def test_get_fact_session_scope(self, db):
        svc = MemoryService(db)
        svc.set_fact("key1", "session_val", fact_type="general", agent_id="a1", scope="session", session_id="s1")
        svc.set_fact("key1", "agent_val", fact_type="general", agent_id="a1", scope="agent")
        # Session scope should win
        result = svc.get_fact("key1", agent_id="a1", session_id="s1")
        assert result == "session_val"

    def test_get_fact_user_scope(self, db):
        svc = MemoryService(db)
        svc.set_fact("key1", "user_val", fact_type="general", agent_id="a1", scope="user", user_id="u1")
        svc.set_fact("key1", "agent_val", fact_type="general", agent_id="a1", scope="agent")
        result = svc.get_fact("key1", agent_id="a1", user_id="u1")
        assert result == "user_val"

    def test_get_fact_not_found(self, db):
        svc = MemoryService(db)
        assert svc.get_fact("missing", agent_id="a1") is None

    def test_get_fact_global_scope(self, db):
        svc = MemoryService(db)
        svc.set_fact("key1", "global_val", fact_type="general", agent_id="a1", scope="global")
        result = svc.get_fact("key1", agent_id="a1")
        assert result == "global_val"

    def test_search_facts(self, db):
        svc = MemoryService(db)
        svc.set_fact("user_name", "Alice", fact_type="identity", agent_id="a1", scope="agent")
        svc.set_fact("user_age", 30, fact_type="identity", agent_id="a1", scope="agent")
        results = svc.search_facts("user", agent_id="a1")
        assert len(results) >= 1

    def test_search_facts_with_types(self, db):
        svc = MemoryService(db)
        svc.set_fact("color", "blue", agent_id="a1", scope="agent", fact_type="preference")
        results = svc.search_facts("color", agent_id="a1", fact_types=["preference"])
        assert len(results) >= 1

    def test_get_user_facts(self, db):
        svc = MemoryService(db)
        svc.set_fact("pref", "dark", fact_type="preference", agent_id="a1", scope="user", user_id="u1")
        results = svc.get_user_facts("u1")
        assert len(results) >= 1

    def test_delete_fact(self, db):
        svc = MemoryService(db)
        svc.set_fact("temp", "val", fact_type="general", agent_id="a1", scope="agent")
        fact = db.query(MemoryFact).filter(MemoryFact.key == "temp").first()
        assert fact is not None
        result = svc.delete_fact(str(fact.id))
        assert result is True
        assert svc.get_fact("temp", agent_id="a1") is None

    def test_delete_fact_not_found(self, db):
        svc = MemoryService(db)
        assert svc.delete_fact("00000000-0000-0000-0000-000000000000") is False


class TestEpisodeOperations:
    def test_log_and_complete_episode(self, db):
        svc = MemoryService(db)
        episode = svc.log_episode(agent_id="a1", trigger_type="chat", trigger_input={"text": "hi"})
        assert episode.id is not None

        svc.complete_episode(
            episode_id=str(episode.id),
            success=True,
            final_output={"result": "ok"},
            conversation=[{"role": "user", "content": "hi"}],
            actions_taken=[{"node_id": "n1", "status": "success"}],
        )
        refreshed = svc.get_episode(str(episode.id))
        assert refreshed.success is True
        assert refreshed.duration_ms is not None

    def test_complete_episode_not_found(self, db):
        svc = MemoryService(db)
        # Should not raise
        svc.complete_episode("00000000-0000-0000-0000-000000000000", success=False, final_output=None)

    def test_add_action_to_episode(self, db):
        svc = MemoryService(db)
        ep = svc.log_episode(agent_id="a1", trigger_type="manual")
        svc.add_action_to_episode(str(ep.id), {"node_id": "n1", "status": "success"})
        refreshed = svc.get_episode(str(ep.id))
        assert len(refreshed.actions_taken) == 1

    def test_add_action_not_found(self, db):
        svc = MemoryService(db)
        svc.add_action_to_episode("00000000-0000-0000-0000-000000000000", {"x": 1})

    def test_add_message_to_episode(self, db):
        svc = MemoryService(db)
        ep = svc.log_episode(agent_id="a1", trigger_type="chat")
        svc.add_message_to_episode(str(ep.id), "user", "hello")
        refreshed = svc.get_episode(str(ep.id))
        assert len(refreshed.conversation) == 1
        assert refreshed.conversation[0]["role"] == "user"

    def test_add_message_not_found(self, db):
        svc = MemoryService(db)
        svc.add_message_to_episode("00000000-0000-0000-0000-000000000000", "user", "hi")

    def test_get_recent_episodes(self, db):
        svc = MemoryService(db)
        svc.log_episode(agent_id="a1", trigger_type="manual")
        svc.log_episode(agent_id="a1", trigger_type="chat")
        result = svc.get_recent_episodes("a1")
        assert len(result) == 2

    def test_get_recent_episodes_with_user_id(self, db):
        svc = MemoryService(db)
        svc.log_episode(agent_id="a1", trigger_type="chat", user_id="u1")
        svc.log_episode(agent_id="a1", trigger_type="chat", user_id="u2")
        result = svc.get_recent_episodes("a1", user_id="u1")
        assert len(result) == 1

    def test_complete_episode_with_error(self, db):
        svc = MemoryService(db)
        ep = svc.log_episode(agent_id="a1", trigger_type="manual")
        svc.complete_episode(
            str(ep.id), success=False, final_output=None,
            error_code="RuntimeError", error_message="Something failed",
        )
        refreshed = svc.get_episode(str(ep.id))
        assert refreshed.success is False
        assert refreshed.error_code == "RuntimeError"


class TestUserOperations:
    def test_get_or_create_user_telegram(self, db):
        svc = MemoryService(db)
        user = svc.get_or_create_user("telegram", "123456", display_name="Alice")
        assert user.telegram_id == "123456"
        assert user.display_name == "Alice"

        # Second call should find existing
        user2 = svc.get_or_create_user("telegram", "123456")
        assert user2.id == user.id

    def test_get_or_create_user_email(self, db):
        svc = MemoryService(db)
        user = svc.get_or_create_user("email", "a@b.com", display_name="Bob")
        assert user.email == "a@b.com"

        user2 = svc.get_or_create_user("email", "a@b.com")
        assert user2.id == user.id

    def test_get_or_create_user_other_channel(self, db):
        svc = MemoryService(db)
        user = svc.get_or_create_user("slack", "U12345", display_name="Charlie")
        assert user.canonical_id == "slack:U12345"

        user2 = svc.get_or_create_user("slack", "U12345")
        assert user2.id == user.id

    def test_get_user_by_canonical_id(self, db):
        svc = MemoryService(db)
        svc.get_or_create_user("telegram", "999")
        user = svc.get_user_by_canonical_id("telegram:999")
        assert user is not None

    def test_get_user_context_new_user(self, db):
        svc = MemoryService(db)
        ctx = svc.get_user_context("unknown:123", agent_id="a1")
        assert ctx["is_new"] is True

    def test_get_user_context_existing(self, db):
        svc = MemoryService(db)
        svc.get_or_create_user("telegram", "123", display_name="Alice")
        ctx = svc.get_user_context("telegram:123", agent_id="a1")
        assert ctx["is_new"] is False
        assert ctx["display_name"] == "Alice"

    def test_update_user_preferences(self, db):
        svc = MemoryService(db)
        svc.get_or_create_user("telegram", "123")
        result = svc.update_user_preferences("telegram:123", {"lang": "en"})
        assert result is True

    def test_update_user_preferences_not_found(self, db):
        svc = MemoryService(db)
        result = svc.update_user_preferences("nonexistent", {"lang": "en"})
        assert result is False

    def test_increment_user_conversations(self, db):
        svc = MemoryService(db)
        user = svc.get_or_create_user("telegram", "555")
        initial = user.total_conversations
        svc.increment_user_conversations("telegram:555")
        db.refresh(user)
        assert user.total_conversations == initial + 1


class TestProcedureOperations:
    def test_save_and_get_procedure(self, db):
        svc = MemoryService(db)
        proc = svc.save_procedure(
            name="greet",
            description="Greet the user",
            procedure_type="workflow",
            procedure_content={"steps": ["say hi"]},
            agent_id="a1",
        )
        assert proc.id is not None
        found = svc.get_procedure("greet", "a1")
        assert found is not None

    def test_find_matching_procedure(self, db):
        svc = MemoryService(db)
        svc.save_procedure(
            name="book_flight",
            description="Book a flight",
            procedure_type="workflow",
            procedure_content={"steps": []},
            agent_id="a1",
            trigger_conditions={"goal_contains": ["book", "flight"]},
        )
        found = svc.find_matching_procedure("I want to book a flight", {}, "a1")
        assert found is not None
        assert found.name == "book_flight"

    def test_find_matching_procedure_no_match(self, db):
        svc = MemoryService(db)
        svc.save_procedure(
            name="book_flight",
            description="Book a flight",
            procedure_type="workflow",
            procedure_content={},
            agent_id="a1",
            trigger_conditions={"goal_contains": ["flight"]},
        )
        result = svc.find_matching_procedure("weather forecast", {}, "a1")
        assert result is None

    def test_find_matching_procedure_context_has(self, db):
        svc = MemoryService(db)
        svc.save_procedure(
            name="process_order",
            description="Process an order",
            procedure_type="workflow",
            procedure_content={},
            agent_id="a1",
            trigger_conditions={"context_has": ["order_id"]},
        )
        found = svc.find_matching_procedure("process", {"order_id": "123"}, "a1")
        assert found is not None

    def test_find_matching_procedure_context_has_missing(self, db):
        svc = MemoryService(db)
        svc.save_procedure(
            name="process_order",
            description="Process an order",
            procedure_type="workflow",
            procedure_content={},
            agent_id="a1",
            trigger_conditions={"context_has": ["order_id"]},
        )
        found = svc.find_matching_procedure("process", {}, "a1")
        assert found is None

    def test_matches_conditions_string_goal(self, db):
        svc = MemoryService(db)
        svc.save_procedure(
            name="hello",
            description="Hello proc",
            procedure_type="workflow",
            procedure_content={},
            agent_id="a1",
            trigger_conditions={"goal_contains": "hello"},
        )
        found = svc.find_matching_procedure("say hello world", {}, "a1")
        assert found is not None

    def test_record_procedure_use(self, db):
        svc = MemoryService(db)
        proc = svc.save_procedure(
            name="test_proc", description="Test", procedure_type="workflow",
            procedure_content={}, agent_id="a1",
        )
        svc.record_procedure_use(str(proc.id), success=True, duration_ms=100)
        db.refresh(proc)
        assert proc.times_used == 1
        assert proc.times_succeeded == 1
        assert proc.avg_duration_ms == 100.0

    def test_record_procedure_use_failure(self, db):
        svc = MemoryService(db)
        proc = svc.save_procedure(
            name="test_proc2", description="Test2", procedure_type="workflow",
            procedure_content={}, agent_id="a1",
        )
        svc.record_procedure_use(str(proc.id), success=False)
        db.refresh(proc)
        assert proc.times_failed == 1

    def test_record_procedure_use_running_avg(self, db):
        svc = MemoryService(db)
        proc = svc.save_procedure(
            name="test_proc3", description="Test3", procedure_type="workflow",
            procedure_content={}, agent_id="a1",
        )
        svc.record_procedure_use(str(proc.id), success=True, duration_ms=100)
        svc.record_procedure_use(str(proc.id), success=True, duration_ms=200)
        db.refresh(proc)
        assert proc.times_used == 2
        assert proc.avg_duration_ms == 150.0

    def test_record_procedure_not_found(self, db):
        svc = MemoryService(db)
        svc.record_procedure_use("00000000-0000-0000-0000-000000000000", success=True)

    def test_list_procedures(self, db):
        svc = MemoryService(db)
        svc.save_procedure(name="p1", description="d1", procedure_type="workflow", procedure_content={}, agent_id="a1")
        svc.save_procedure(name="p2", description="d2", procedure_type="workflow", procedure_content={}, agent_id="a1")
        result = svc.list_procedures("a1")
        assert len(result) == 2

    def test_deactivate_procedure(self, db):
        svc = MemoryService(db)
        proc = svc.save_procedure(
            name="p1", description="d1", procedure_type="workflow",
            procedure_content={}, agent_id="a1",
        )
        result = svc.deactivate_procedure(str(proc.id))
        assert result is True
        # Should not show in active list
        active = svc.list_procedures("a1", active_only=True)
        assert len(active) == 0

    def test_deactivate_procedure_not_found(self, db):
        svc = MemoryService(db)
        assert svc.deactivate_procedure("00000000-0000-0000-0000-000000000000") is False
