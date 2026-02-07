"""Tests for DB-dependent components: whoami, create_agent_user, identify_user."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_node(component_type="test", extra_config=None, workflow_id=1, node_id="test_node_1"):
    config = SimpleNamespace(
        component_type=component_type,
        extra_config=extra_config or {},
        system_prompt="",
    )
    return SimpleNamespace(
        node_id=node_id,
        workflow_id=workflow_id,
        component_type=component_type,
        component_config=config,
    )


# ── Whoami ────────────────────────────────────────────────────────────────────

class TestWhoami:
    @patch("components.whoami.SessionLocal")
    def test_no_edge_found(self, mock_session_cls):
        from components.whoami import whoami_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        node = _make_node("whoami", workflow_id=1, node_id="whoami_1")
        tool = whoami_factory(node)
        result = json.loads(tool.invoke({}))
        assert "error" in result
        assert "not connected" in result["error"]

    @patch("components.whoami.SessionLocal")
    def test_agent_not_found(self, mock_session_cls):
        from components.whoami import whoami_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # First query returns an edge
        mock_edge = SimpleNamespace(target_node_id="agent_1")
        # Second query (agent node) returns None
        query = mock_db.query.return_value.filter.return_value
        query.first.side_effect = [mock_edge, None]

        node = _make_node("whoami", workflow_id=1, node_id="whoami_1")
        tool = whoami_factory(node)
        result = json.loads(tool.invoke({}))
        assert "error" in result
        assert "agent_1" in result["error"]

    @patch("components.whoami.SessionLocal")
    def test_success(self, mock_session_cls):
        from components.whoami import whoami_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        mock_edge = SimpleNamespace(target_node_id="agent_1")
        mock_agent_config = SimpleNamespace(
            system_prompt="Be helpful",
            extra_config={"conversation_memory": True},
        )
        mock_agent = SimpleNamespace(
            node_id="agent_1",
            component_type="agent",
            component_config=mock_agent_config,
        )
        mock_workflow = SimpleNamespace(slug="my-workflow")

        query = mock_db.query.return_value.filter.return_value
        query.first.side_effect = [mock_edge, mock_agent, mock_workflow]

        node = _make_node("whoami", workflow_id=1, node_id="whoami_1")
        tool = whoami_factory(node)
        result = json.loads(tool.invoke({}))
        assert result["identity"]["workflow_slug"] == "my-workflow"
        assert result["identity"]["node_id"] == "agent_1"
        assert result["current_config"]["system_prompt"] == "Be helpful"
        assert "self_modification" in result

    @patch("components.whoami.SessionLocal")
    def test_long_prompt_truncated(self, mock_session_cls):
        from components.whoami import whoami_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        long_prompt = "x" * 2000
        mock_edge = SimpleNamespace(target_node_id="agent_1")
        mock_agent_config = SimpleNamespace(
            system_prompt=long_prompt,
            extra_config={},
        )
        mock_agent = SimpleNamespace(
            node_id="agent_1",
            component_type="agent",
            component_config=mock_agent_config,
        )
        mock_workflow = SimpleNamespace(slug="wf")

        query = mock_db.query.return_value.filter.return_value
        query.first.side_effect = [mock_edge, mock_agent, mock_workflow]

        node = _make_node("whoami", workflow_id=1, node_id="whoami_1")
        tool = whoami_factory(node)
        result = json.loads(tool.invoke({}))
        assert result["current_config"]["system_prompt"].endswith("...")
        assert result["current_config"]["system_prompt_length"] == 2000

    @patch("components.whoami.SessionLocal")
    def test_exception_handling(self, mock_session_cls):
        from components.whoami import whoami_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.side_effect = RuntimeError("DB down")

        node = _make_node("whoami")
        tool = whoami_factory(node)
        result = json.loads(tool.invoke({}))
        assert "error" in result


# ── Create Agent User ─────────────────────────────────────────────────────────

class TestCreateAgentUser:
    @patch("components.create_agent_user.SessionLocal")
    def test_create_new_user(self, mock_session_cls):
        from components.create_agent_user import create_agent_user_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # Edge found → agent linked
        mock_edge = SimpleNamespace(target_node_id="agent_1")
        mock_workflow = SimpleNamespace(slug="my-workflow")

        # First call: query edge. Second: query workflow. Third: query existing user (None)
        query = mock_db.query.return_value.filter.return_value
        query.first.side_effect = [mock_edge, mock_workflow, None]

        mock_db.flush = MagicMock()
        mock_db.commit = MagicMock()

        # Capture the APIKey that gets added
        added_objects = []
        def track_add(obj):
            added_objects.append(obj)
            if hasattr(obj, 'id') and obj.id is None:
                obj.id = len(added_objects)
            if hasattr(obj, 'key') and not getattr(obj, 'key', None):
                pass
        mock_db.add.side_effect = track_add
        mock_db.refresh = MagicMock()

        node = _make_node("create_agent_user", node_id="cau_1", workflow_id=5)
        tool = create_agent_user_factory(node)
        result = json.loads(tool.invoke({"purpose": "testing"}))
        assert result["success"] is True
        assert result["already_existed"] is False
        assert "agent_my-workflow_agent_1" in result["username"]

    @patch("components.create_agent_user.SessionLocal")
    def test_return_existing_user(self, mock_session_cls):
        from components.create_agent_user import create_agent_user_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # No edge found
        query = mock_db.query.return_value.filter.return_value
        mock_existing = SimpleNamespace(
            api_key=SimpleNamespace(key="existing-key-123"),
            first_name="previous purpose",
        )
        query.first.side_effect = [None, mock_existing]  # no edge, existing user found

        node = _make_node("create_agent_user", node_id="cau_1", workflow_id=3)
        tool = create_agent_user_factory(node)
        result = json.loads(tool.invoke({}))
        assert result["success"] is True
        assert result["already_existed"] is True
        assert result["api_key"] == "existing-key-123"

    @patch("components.create_agent_user.SessionLocal")
    def test_exception_rollback(self, mock_session_cls):
        from components.create_agent_user import create_agent_user_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.side_effect = RuntimeError("DB error")

        node = _make_node("create_agent_user")
        tool = create_agent_user_factory(node)
        result = json.loads(tool.invoke({}))
        assert result["success"] is False
        assert "error" in result
        mock_db.rollback.assert_called_once()


# ── Identify User ─────────────────────────────────────────────────────────────

class TestIdentifyUser:
    def _factory(self):
        from components.identify_user import identify_user_factory
        return identify_user_factory(_make_node("identify_user"))

    def test_telegram_channel(self):
        fn = self._factory()
        state = {
            "trigger": {
                "message": {
                    "from": {"id": 12345, "first_name": "John", "last_name": "Doe"}
                }
            },
            "node_outputs": {},
        }
        with patch("components.identify_user.SessionLocal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db

            mock_user = SimpleNamespace(
                canonical_id="user_12345",
                total_conversations=3,
            )
            mock_memory = MagicMock()
            mock_memory.get_or_create_user.return_value = mock_user
            mock_memory.get_user_context.return_value = {"facts": ["likes coffee"]}

            with patch("components.identify_user.MemoryService", return_value=mock_memory):
                result = fn(state)

        assert result["user_id"] == "user_12345"
        assert result["is_new_user"] is False

    def test_webhook_channel(self):
        fn = self._factory()
        state = {
            "trigger": {"webhook_id": "wh-1", "user_id": "u1", "user_name": "Alice"},
            "node_outputs": {},
        }
        with patch("components.identify_user.SessionLocal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db

            mock_user = SimpleNamespace(canonical_id="u1", total_conversations=0)
            mock_memory = MagicMock()
            mock_memory.get_or_create_user.return_value = mock_user
            mock_memory.get_user_context.return_value = {"facts": []}

            with patch("components.identify_user.MemoryService", return_value=mock_memory):
                result = fn(state)

        assert result["is_new_user"] is True
        assert result["user_id"] == "u1"

    def test_manual_channel(self):
        fn = self._factory()
        state = {
            "trigger": {"source": "manual", "user_id": "manual_u"},
            "node_outputs": {},
        }
        with patch("components.identify_user.SessionLocal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db

            mock_user = SimpleNamespace(canonical_id="manual_u", total_conversations=1)
            mock_memory = MagicMock()
            mock_memory.get_or_create_user.return_value = mock_user
            mock_memory.get_user_context.return_value = {}

            with patch("components.identify_user.MemoryService", return_value=mock_memory):
                result = fn(state)

        assert result["user_id"] == "manual_u"

    def test_chat_channel(self):
        fn = self._factory()
        state = {
            "trigger": {"source": "chat"},
            "node_outputs": {},
        }
        with patch("components.identify_user.SessionLocal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db

            mock_user = SimpleNamespace(canonical_id="manual_user", total_conversations=0)
            mock_memory = MagicMock()
            mock_memory.get_or_create_user.return_value = mock_user
            mock_memory.get_user_context.return_value = {}

            with patch("components.identify_user.MemoryService", return_value=mock_memory):
                result = fn(state)

        assert result["user_id"] == "manual_user"

    def test_unknown_channel_no_id(self):
        fn = self._factory()
        state = {"trigger": {}, "node_outputs": {}}
        result = fn(state)
        # No channel_id → returns is_new
        assert result["user_id"] is None
        assert result["is_new_user"] is True

    def test_node_outputs_override(self):
        fn = self._factory()
        state = {
            "trigger": {},
            "node_outputs": {
                "prev": {"channel": "telegram", "trigger_input": {
                    "message": {"from": {"id": 999, "first_name": "Bot"}}
                }}
            },
        }
        with patch("components.identify_user.SessionLocal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db

            mock_user = SimpleNamespace(canonical_id="user_999", total_conversations=0)
            mock_memory = MagicMock()
            mock_memory.get_or_create_user.return_value = mock_user
            mock_memory.get_user_context.return_value = {}

            with patch("components.identify_user.MemoryService", return_value=mock_memory):
                result = fn(state)

        assert result["user_id"] == "user_999"

    def test_exception_handling(self):
        fn = self._factory()
        state = {
            "trigger": {"source": "manual", "user_id": "u1"},
            "node_outputs": {},
        }
        with patch("components.identify_user.SessionLocal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db
            with patch("components.identify_user.MemoryService", side_effect=RuntimeError("DB fail")):
                result = fn(state)

        assert result["user_id"] is None
        assert result["is_new_user"] is True
        assert "error" in result["_state_patch"]["user_context"]

    def test_unknown_channel_with_user_id(self):
        fn = self._factory()
        state = {
            "trigger": {"user_id": "custom_user"},
            "node_outputs": {},
        }
        with patch("components.identify_user.SessionLocal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db

            mock_user = SimpleNamespace(canonical_id="custom_user", total_conversations=0)
            mock_memory = MagicMock()
            mock_memory.get_or_create_user.return_value = mock_user
            mock_memory.get_user_context.return_value = {}

            with patch("components.identify_user.MemoryService", return_value=mock_memory):
                result = fn(state)

        assert result["user_id"] == "custom_user"

    def test_execution_id_agent_id(self):
        fn = self._factory()
        state = {
            "trigger": {"source": "manual", "user_id": "u1"},
            "node_outputs": {},
            "execution_id": "abc123-def-456",
        }
        with patch("components.identify_user.SessionLocal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db

            mock_user = SimpleNamespace(canonical_id="u1", total_conversations=1)
            mock_memory = MagicMock()
            mock_memory.get_or_create_user.return_value = mock_user
            mock_memory.get_user_context.return_value = {}

            with patch("components.identify_user.MemoryService", return_value=mock_memory):
                result = fn(state)

        # agent_id derived from execution_id prefix
        mock_memory.get_user_context.assert_called_once()
        call_kwargs = mock_memory.get_user_context.call_args
        assert "abc123" in call_kwargs[1]["agent_id"]
