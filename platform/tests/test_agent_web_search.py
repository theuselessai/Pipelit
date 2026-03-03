"""Tests for agent web search integration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_agent_node(component_type="agent"):
    """Create a minimal mock node for agent factory tests."""
    node = MagicMock()
    node.node_id = f"{component_type}_1"
    node.workflow_id = 1
    node.workflow.slug = "test"
    concrete = MagicMock()
    concrete.system_prompt = ""
    concrete.extra_config = {}
    concrete.max_tokens = None
    node.component_config.concrete = concrete
    node.component_config.component_type = component_type
    return node


class TestAgentWebSearchIntegration:
    """Test agent_factory web search tool resolution."""

    @patch("components.agent.create_agent")
    @patch("database.SessionLocal")
    @patch("services.web_search.resolve_web_search_tools")
    @patch("services.llm.resolve_credential_for_node")
    @patch("components.agent._resolve_skills", return_value=[])
    @patch("components.agent._resolve_tools", return_value=([], {}))
    @patch("components.agent._get_ai_model_extra", return_value={"use_native_search": True})
    @patch("components.agent.get_model_name_for_node", return_value="test-model")
    @patch("components.agent.resolve_llm_for_node")
    def test_agent_with_native_search(
        self, mock_llm, mock_model_name, mock_extra, mock_tools, mock_skills,
        mock_cred, mock_web_search, mock_session_cls, mock_create,
    ):
        """agent_factory wraps LLM when native search tools are returned."""
        from components.agent import agent_factory

        mock_llm.return_value = MagicMock()
        mock_cred.return_value = SimpleNamespace(
            provider_type="anthropic", api_key="k", base_url="",
        )
        mock_web_search.return_value = (
            [{"type": "web_search_20250305", "name": "web_search"}],
            [],
        )
        mock_create.return_value = MagicMock()

        result = agent_factory(_make_agent_node())

        assert callable(result)
        mock_web_search.assert_called_once()
        mock_create.assert_called_once()
        # Model should be wrapped with _NativeToolLLMWrapper
        model = mock_create.call_args.kwargs["model"]
        assert type(model).__name__ == "_NativeToolLLMWrapper"

    @patch("components.agent.create_agent")
    @patch("database.SessionLocal")
    @patch("services.web_search.resolve_web_search_tools")
    @patch("services.llm.resolve_credential_for_node")
    @patch("components.agent._resolve_skills", return_value=[])
    @patch("components.agent._resolve_tools", return_value=([], {}))
    @patch("components.agent._get_ai_model_extra", return_value={"use_native_search": False})
    @patch("components.agent.get_model_name_for_node", return_value="test-model")
    @patch("components.agent.resolve_llm_for_node")
    def test_agent_with_searxng(
        self, mock_llm, mock_model_name, mock_extra, mock_tools, mock_skills,
        mock_cred, mock_web_search, mock_session_cls, mock_create,
    ):
        """agent_factory adds LC search tools when SearXNG is available."""
        from components.agent import agent_factory

        raw_llm = MagicMock()
        mock_llm.return_value = raw_llm
        mock_cred.return_value = SimpleNamespace(
            provider_type="openai", api_key="k", base_url="",
        )
        lc_tool = MagicMock()
        lc_tool.name = "web_search"
        mock_web_search.return_value = ([], [lc_tool])
        mock_create.return_value = MagicMock()

        result = agent_factory(_make_agent_node())

        assert callable(result)
        mock_create.assert_called_once()
        # Model should NOT be wrapped (no native tools)
        assert mock_create.call_args.kwargs["model"] is raw_llm
        # LC tool should be in the tools list
        assert lc_tool in mock_create.call_args.kwargs["tools"]


class TestDeepAgentWebSearchIntegration:
    """Test deep_agent_factory web search tool resolution."""

    @patch("components.deep_agent.create_deep_agent")
    @patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock())
    @patch("components.deep_agent._build_backend", return_value=MagicMock())
    @patch("database.SessionLocal")
    @patch("services.web_search.resolve_web_search_tools")
    @patch("services.llm.resolve_credential_for_node")
    @patch("components.deep_agent._resolve_skills", return_value=[])
    @patch("components.deep_agent._resolve_tools", return_value=([], {}))
    @patch("components.deep_agent._get_ai_model_extra", return_value={"use_native_search": True})
    @patch("components.deep_agent.get_model_name_for_node", return_value="test-model")
    @patch("components.deep_agent.resolve_llm_for_node")
    def test_deep_agent_with_native_search(
        self, mock_llm, mock_model_name, mock_extra, mock_tools, mock_skills,
        mock_cred, mock_web_search, mock_session_cls, mock_backend,
        mock_redis_cp, mock_create,
    ):
        """deep_agent_factory wraps LLM when native search tools are returned."""
        from components.deep_agent import deep_agent_factory

        mock_llm.return_value = MagicMock()
        mock_cred.return_value = SimpleNamespace(
            provider_type="anthropic", api_key="k", base_url="",
        )
        mock_web_search.return_value = (
            [{"type": "web_search_20250305", "name": "web_search"}],
            [],
        )
        mock_create.return_value = MagicMock()

        result = deep_agent_factory(_make_agent_node(component_type="deep_agent"))

        assert callable(result)
        mock_web_search.assert_called_once()
        mock_create.assert_called_once()
        model = mock_create.call_args.kwargs["model"]
        assert type(model).__name__ == "_NativeToolLLMWrapper"


class TestAgentShared:
    """Test _agent_shared.py functions."""

    def test_is_empty_text_block_true(self):
        """Test empty text block detection."""
        from components._agent_shared import _is_empty_text_block

        # Empty text block
        assert _is_empty_text_block({"type": "text", "text": ""}) is True

        # Non-empty text block
        assert _is_empty_text_block({"type": "text", "text": "hello"}) is False

        # Non-text block
        assert _is_empty_text_block({"type": "tool_use", "text": ""}) is False

    def test_strip_thinking_blocks(self):
        """Test stripping thinking blocks from messages."""
        from components._agent_shared import strip_thinking_blocks

        messages = [
            SimpleNamespace(type="user", content=[{"type": "text", "text": "hello"}]),
            SimpleNamespace(type="ai", content=[
                {"type": "thinking", "text": "let me think"},
                {"type": "text", "text": "answer"},
            ]),
        ]

        result = strip_thinking_blocks(messages)

        # Should remove thinking blocks from AI message
        content = result[1].content
        types = [c["type"] for c in content]
        assert "thinking" not in types
        assert "text" in types

    def test_strip_web_search_blocks(self):
        """Test stripping web search blocks from messages."""
        from components._agent_shared import strip_web_search_blocks

        messages = [
            SimpleNamespace(type="user", content=[{"type": "text", "text": "search for X"}]),
            SimpleNamespace(type="ai", content=[
                {"type": "server_tool_use", "id": "search1", "name": "web_search"},
                {"type": "text", "text": "here are results"},
            ]),
        ]

        result = strip_web_search_blocks(messages)

        content = result[1].content
        types = [c["type"] for c in content]
        assert "server_tool_use" not in types

    def test_wrap_llm_with_native_tools(self):
        """Test wrapping LLM with native tools."""
        from components._agent_shared import _wrap_llm_with_native_tools

        mock_llm = MagicMock()
        mock_llm.some_attr = "value"

        native_tools = [{"type": "web_search", "name": "web_search"}]

        wrapped = _wrap_llm_with_native_tools(mock_llm, native_tools)

        # Should be wrapped in NativeSearchWrapper
        assert hasattr(wrapped, 'bind_tools')
