"""Tests for deep_agent component: _build_backend, _build_subagents, deep_agent_factory, inner node."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_node(extra_config=None, system_prompt=None, node_id="deep_1", workflow_id=1):
    concrete = SimpleNamespace(
        system_prompt=system_prompt or "",
        extra_config=extra_config or {},
    )
    config = SimpleNamespace(
        component_type="deep_agent",
        extra_config=extra_config or {},
        system_prompt=system_prompt or "",
        concrete=concrete,
    )
    return SimpleNamespace(
        node_id=node_id,
        workflow_id=workflow_id,
        component_type="deep_agent",
        component_config=config,
        workflow=SimpleNamespace(slug="test-wf"),
    )


# ---------------------------------------------------------------------------
# _build_backend
# ---------------------------------------------------------------------------


class TestBuildBackend:
    def test_filesystem_backend(self):
        from components.deep_agent import _build_backend

        mock_backend = MagicMock()
        with patch("components.deep_agent.FilesystemBackend", mock_backend, create=True):
            # Patch the lazy import inside _build_backend
            import sys
            mock_fs_mod = MagicMock()
            mock_fs_mod.FilesystemBackend = mock_backend
            with patch.dict(sys.modules, {"deepagents.backends.filesystem": mock_fs_mod}):
                result = _build_backend({"filesystem_backend": "filesystem", "filesystem_root_dir": "/tmp/test"})
        assert result is mock_backend.return_value
        mock_backend.assert_called_once_with(root_dir="/tmp/test")

    def test_filesystem_backend_no_root_dir(self):
        from components.deep_agent import _build_backend

        mock_backend = MagicMock()
        import sys
        mock_fs_mod = MagicMock()
        mock_fs_mod.FilesystemBackend = mock_backend
        with patch.dict(sys.modules, {"deepagents.backends.filesystem": mock_fs_mod}):
            result = _build_backend({"filesystem_backend": "filesystem"})
        assert result is mock_backend.return_value
        mock_backend.assert_called_once_with(root_dir=None)

    def test_store_backend(self):
        from components.deep_agent import _build_backend

        result = _build_backend({"filesystem_backend": "store"})
        assert result is None

    def test_state_backend_default(self):
        from components.deep_agent import _build_backend

        result = _build_backend({})
        assert result is None

    def test_state_backend_explicit(self):
        from components.deep_agent import _build_backend

        result = _build_backend({"filesystem_backend": "state"})
        assert result is None


# ---------------------------------------------------------------------------
# _build_subagents
# ---------------------------------------------------------------------------


class TestBuildSubagents:
    def test_valid_subagents(self):
        from components.deep_agent import _build_subagents

        result = _build_subagents({
            "subagents": [
                {"name": "research", "description": "Researches topics", "system_prompt": "You research."},
                {"name": "writer", "description": "Writes content", "system_prompt": "You write."},
            ]
        })
        assert result is not None
        assert len(result) == 2
        assert result[0]["name"] == "research"
        assert result[1]["name"] == "writer"

    def test_with_model_override(self):
        from components.deep_agent import _build_subagents

        result = _build_subagents({
            "subagents": [
                {"name": "coder", "description": "Writes code", "system_prompt": "You code.", "model": "gpt-4"},
            ]
        })
        assert result is not None
        assert result[0]["model"] == "gpt-4"

    def test_missing_required_fields_skipped(self):
        from components.deep_agent import _build_subagents

        result = _build_subagents({
            "subagents": [
                {"name": "incomplete", "description": ""},  # missing system_prompt, empty description
                {"name": "valid", "description": "Does stuff", "system_prompt": "You do stuff."},
            ]
        })
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "valid"

    def test_non_dict_entries_skipped(self):
        from components.deep_agent import _build_subagents

        result = _build_subagents({
            "subagents": [
                "not a dict",
                42,
                {"name": "valid", "description": "Does stuff", "system_prompt": "You do stuff."},
            ]
        })
        assert result is not None
        assert len(result) == 1

    def test_empty_list(self):
        from components.deep_agent import _build_subagents

        result = _build_subagents({"subagents": []})
        assert result is None

    def test_missing_key(self):
        from components.deep_agent import _build_subagents

        result = _build_subagents({})
        assert result is None

    def test_all_entries_invalid_returns_none(self):
        from components.deep_agent import _build_subagents

        result = _build_subagents({
            "subagents": [
                {"name": "", "description": "no name", "system_prompt": "prompt"},
            ]
        })
        assert result is None


# ---------------------------------------------------------------------------
# deep_agent_factory
# ---------------------------------------------------------------------------


class TestDeepAgentFactory:
    """Test the factory function that builds the deep_agent closure."""

    def _build(self, extra_config=None, system_prompt=None):
        """Call deep_agent_factory with all external deps mocked; return captured kwargs."""
        from components.deep_agent import deep_agent_factory

        extra = extra_config or {}
        node = _make_node(extra_config=extra, system_prompt=system_prompt)

        captured = {}

        def capture_create(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        mock_sqlite = MagicMock(name="sqlite_checkpointer")
        mock_redis = MagicMock(name="redis_checkpointer")

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()) as mock_llm, \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", side_effect=capture_create), \
             patch("components.deep_agent._get_checkpointer", return_value=mock_sqlite), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=mock_redis), \
             patch("components.deep_agent.get_model_name_for_node", return_value="test-model"):
            fn = deep_agent_factory(node)

        return fn, captured, mock_sqlite, mock_redis

    def test_basic_creation(self):
        fn, captured, _, _ = self._build()
        assert fn is not None
        assert "model" in captured
        assert captured.get("system_prompt") is None  # empty string → None
        assert captured.get("checkpointer") is not None

    def test_conversation_memory_checkpointer(self):
        _, captured, mock_sqlite, _ = self._build(extra_config={"conversation_memory": True})
        assert captured["checkpointer"] is mock_sqlite

    def test_no_conversation_memory_checkpointer(self):
        _, captured, _, mock_redis = self._build(extra_config={"conversation_memory": False})
        assert captured["checkpointer"] is mock_redis

    def test_enable_filesystem_and_todos(self):
        _, captured, _, _ = self._build(extra_config={
            "enable_filesystem": True,
            "enable_todos": True,
            "filesystem_backend": "state",
        })
        assert "todos" in captured["memory"]
        assert "filesystem" in captured["memory"]

    def test_enable_filesystem_with_backend(self):
        import sys
        mock_fs_mod = MagicMock()
        mock_backend_instance = MagicMock()
        mock_fs_mod.FilesystemBackend.return_value = mock_backend_instance

        with patch.dict(sys.modules, {"deepagents.backends.filesystem": mock_fs_mod}):
            _, captured, _, _ = self._build(extra_config={
                "enable_filesystem": True,
                "filesystem_backend": "filesystem",
                "filesystem_root_dir": "/tmp/deep",
            })
        assert captured.get("backend") is mock_backend_instance

    def test_with_subagents(self):
        _, captured, _, _ = self._build(extra_config={
            "subagents": [
                {"name": "helper", "description": "Helps", "system_prompt": "You help."},
            ]
        })
        assert captured.get("subagents") is not None
        assert len(captured["subagents"]) == 1
        assert captured["subagents"][0]["name"] == "helper"

    def test_model_name_fallback(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node()

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=MagicMock()), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", side_effect=RuntimeError("no model")):
            fn = deep_agent_factory(node)
        # Should not raise — falls back to ""
        assert fn is not None

    def test_prompt_fallback_with_system_prompt(self):
        fn, captured, _, _ = self._build(system_prompt="Be helpful.")
        assert captured.get("system_prompt") == "Be helpful."

    def test_prompt_fallback_without_system_prompt(self):
        fn, captured, _, _ = self._build(system_prompt="")
        assert captured.get("system_prompt") is None

    def test_no_memory_features_omits_key(self):
        _, captured, _, _ = self._build(extra_config={})
        assert "memory" not in captured

    def test_tools_passed_when_present(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node()
        mock_tool = MagicMock()
        captured = {}

        def capture_create(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([mock_tool], {"t": {}})), \
             patch("components.deep_agent.create_deep_agent", side_effect=capture_create), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"):
            deep_agent_factory(node)

        assert captured["tools"] == [mock_tool]

    def test_invalid_context_window_falls_back_to_none(self):
        fn, _, _, _ = self._build(extra_config={"context_window": "bad"})
        assert callable(fn)


# ---------------------------------------------------------------------------
# deep_agent_node (inner closure)
# ---------------------------------------------------------------------------


class TestDeepAgentNode:
    """Test the inner closure returned by deep_agent_factory."""

    def _build_and_invoke(self, state, extra_config=None, system_prompt=None, invoke_return=None):
        """Build the node closure with mocked deps and invoke it with the given state."""
        from components.deep_agent import deep_agent_factory

        extra = extra_config or {}
        node = _make_node(extra_config=extra, system_prompt=system_prompt)

        ai_msg = MagicMock()
        ai_msg.content = "Hello from deep agent"
        ai_msg.type = "ai"
        ai_msg.additional_kwargs = {}
        ai_msg.tool_calls = []

        default_return = {"messages": [ai_msg]}
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = invoke_return or default_return

        mock_usage = {"llm_calls": 1, "input_tokens": 10, "output_tokens": 20, "total_tokens": 30}

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="test-model"), \
             patch("components.deep_agent.extract_usage_from_messages", return_value=mock_usage), \
             patch("components.deep_agent.calculate_cost", return_value=0.001):
            fn = deep_agent_factory(node)
            result = fn(state)

        return result, mock_agent

    def test_basic_invoke(self):
        result, mock_agent = self._build_and_invoke(
            state={"messages": [MagicMock(content="Hi")], "execution_id": "exec-1"},
        )
        assert "output" in result
        assert result["output"] == "Hello from deep agent"
        assert "_messages" in result
        assert "_token_usage" in result
        mock_agent.invoke.assert_called_once()

    def test_invoke_exception_logged_and_reraised(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node()
        mock_agent = MagicMock()
        mock_agent.invoke.side_effect = RuntimeError("boom")

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"):
            fn = deep_agent_factory(node)

        with pytest.raises(RuntimeError, match="boom"):
            fn({"messages": [], "execution_id": "exec-1"})

    def test_thread_id_child_execution(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node(node_id="deep_child")
        mock_agent = MagicMock()
        ai_msg = MagicMock(content="ok", type="ai", additional_kwargs={}, tool_calls=[])
        mock_agent.invoke.return_value = {"messages": [ai_msg]}

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"), \
             patch("components.deep_agent.extract_usage_from_messages", return_value={"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}), \
             patch("components.deep_agent.calculate_cost", return_value=0.0):
            fn = deep_agent_factory(node)
            fn({"messages": [], "execution_id": "exec-42", "_is_child_execution": True})

        call_args = mock_agent.invoke.call_args
        config = call_args[1]["config"]
        assert config["configurable"]["thread_id"] == "exec:exec-42:deep_child"

    def test_thread_id_conversation_memory(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node(extra_config={"conversation_memory": True}, node_id="deep_mem")
        mock_agent = MagicMock()
        ai_msg = MagicMock(content="ok", type="ai", additional_kwargs={}, tool_calls=[])
        mock_agent.invoke.return_value = {"messages": [ai_msg]}

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"), \
             patch("components.deep_agent.extract_usage_from_messages", return_value={"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}), \
             patch("components.deep_agent.calculate_cost", return_value=0.0):
            fn = deep_agent_factory(node)
            fn({
                "messages": [],
                "execution_id": "exec-99",
                "user_context": {"user_profile_id": "user1", "telegram_chat_id": "chat1"},
            })

        call_args = mock_agent.invoke.call_args
        config = call_args[1]["config"]
        assert config["configurable"]["thread_id"] == "user1:chat1:1"

    def test_thread_id_conversation_memory_no_chat_id(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node(extra_config={"conversation_memory": True}, node_id="deep_mem2")
        mock_agent = MagicMock()
        ai_msg = MagicMock(content="ok", type="ai", additional_kwargs={}, tool_calls=[])
        mock_agent.invoke.return_value = {"messages": [ai_msg]}

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"), \
             patch("components.deep_agent.extract_usage_from_messages", return_value={"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}), \
             patch("components.deep_agent.calculate_cost", return_value=0.0):
            fn = deep_agent_factory(node)
            fn({
                "messages": [],
                "execution_id": "exec-99",
                "user_context": {"user_profile_id": "user2"},
            })

        call_args = mock_agent.invoke.call_args
        config = call_args[1]["config"]
        assert config["configurable"]["thread_id"] == "user2:1"

    def test_thread_id_ephemeral(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node(node_id="deep_eph")
        mock_agent = MagicMock()
        ai_msg = MagicMock(content="ok", type="ai", additional_kwargs={}, tool_calls=[])
        mock_agent.invoke.return_value = {"messages": [ai_msg]}

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"), \
             patch("components.deep_agent.extract_usage_from_messages", return_value={"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}), \
             patch("components.deep_agent.calculate_cost", return_value=0.0):
            fn = deep_agent_factory(node)
            fn({"messages": [], "execution_id": "exec-77"})

        call_args = mock_agent.invoke.call_args
        config = call_args[1]["config"]
        assert config["configurable"]["thread_id"] == "exec:exec-77:deep_eph"

    def test_timestamp_enrichment(self):
        result, _ = self._build_and_invoke(
            state={"messages": [MagicMock(content="Hi")], "execution_id": "exec-1"},
        )
        # The AI messages in _messages should have a timestamp
        for msg in result["_messages"]:
            if hasattr(msg, "type") and msg.type == "ai":
                assert "timestamp" in msg.additional_kwargs

    def test_token_usage_fallback(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node()
        mock_agent = MagicMock()
        ai_msg = MagicMock(content="ok", type="ai", additional_kwargs={}, tool_calls=[])
        mock_agent.invoke.return_value = {"messages": [ai_msg]}

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"), \
             patch("components.deep_agent.extract_usage_from_messages", side_effect=RuntimeError("parse fail")):
            fn = deep_agent_factory(node)
            result = fn({"messages": [], "execution_id": "exec-1"})

        usage = result["_token_usage"]
        assert usage["llm_calls"] == 0
        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0
        assert usage["total_tokens"] == 0
        assert usage["cost_usd"] == 0.0
        assert usage["tool_invocations"] == 0

    def test_prompt_fallback_prepended(self):
        """When system_prompt is set, the HumanMessage fallback is prepended to messages."""
        from components.deep_agent import deep_agent_factory

        node = _make_node(system_prompt="Be helpful.")
        mock_agent = MagicMock()
        ai_msg = MagicMock(content="ok", type="ai", additional_kwargs={}, tool_calls=[])
        mock_agent.invoke.return_value = {"messages": [ai_msg]}

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"), \
             patch("components.deep_agent.extract_usage_from_messages", return_value={"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}), \
             patch("components.deep_agent.calculate_cost", return_value=0.0):
            fn = deep_agent_factory(node)
            fn({"messages": [MagicMock(content="Hi")], "execution_id": "exec-1"})

        call_args = mock_agent.invoke.call_args
        invoke_input = call_args[0][0]
        # First message should be the system prompt fallback HumanMessage
        first_msg = invoke_input["messages"][0]
        assert "Be helpful." in first_msg.content

    def test_no_prompt_fallback_when_no_system_prompt(self):
        """When system_prompt is empty, no fallback HumanMessage is prepended."""
        from components.deep_agent import deep_agent_factory

        node = _make_node(system_prompt="")
        mock_agent = MagicMock()
        ai_msg = MagicMock(content="ok", type="ai", additional_kwargs={}, tool_calls=[])
        mock_agent.invoke.return_value = {"messages": [ai_msg]}

        user_msg = MagicMock(content="Hi")

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"), \
             patch("components.deep_agent.extract_usage_from_messages", return_value={"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}), \
             patch("components.deep_agent.calculate_cost", return_value=0.0):
            fn = deep_agent_factory(node)
            fn({"messages": [user_msg], "execution_id": "exec-1"})

        call_args = mock_agent.invoke.call_args
        invoke_input = call_args[0][0]
        # Should only have the user message, no fallback
        assert len(invoke_input["messages"]) == 1
        assert invoke_input["messages"][0] is user_msg

    def test_execution_id_passed_in_invoke_input(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node()
        mock_agent = MagicMock()
        ai_msg = MagicMock(content="ok", type="ai", additional_kwargs={}, tool_calls=[])
        mock_agent.invoke.return_value = {"messages": [ai_msg]}

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="m"), \
             patch("components.deep_agent.extract_usage_from_messages", return_value={"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}), \
             patch("components.deep_agent.calculate_cost", return_value=0.0):
            fn = deep_agent_factory(node)
            fn({"messages": [], "execution_id": "exec-555"})

        call_args = mock_agent.invoke.call_args
        invoke_input = call_args[0][0]
        assert invoke_input["execution_id"] == "exec-555"

    def test_empty_messages_returns_empty_output(self):
        """When agent returns no AI messages, output should be empty string."""
        result, _ = self._build_and_invoke(
            state={"messages": [], "execution_id": "exec-1"},
            invoke_return={"messages": []},
        )
        assert result["output"] == ""

    def test_tool_invocations_counted(self):
        from components.deep_agent import deep_agent_factory

        node = _make_node()
        mock_agent = MagicMock()

        ai_msg1 = MagicMock(content="thinking", type="ai", additional_kwargs={})
        ai_msg1.tool_calls = [{"name": "tool1"}, {"name": "tool2"}]
        ai_msg2 = MagicMock(content="done", type="ai", additional_kwargs={})
        ai_msg2.tool_calls = [{"name": "tool3"}]
        mock_agent.invoke.return_value = {"messages": [ai_msg1, ai_msg2]}

        base_usage = {"llm_calls": 2, "input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="test-model"), \
             patch("components.deep_agent.extract_usage_from_messages", return_value=base_usage), \
             patch("components.deep_agent.calculate_cost", return_value=0.005):
            fn = deep_agent_factory(node)
            result = fn({"messages": [], "execution_id": "exec-1"})

        assert result["_token_usage"]["tool_invocations"] == 3
        assert result["_token_usage"]["cost_usd"] == 0.005
