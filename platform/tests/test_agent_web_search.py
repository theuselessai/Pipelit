"""Tests for agent web search integration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class TestAgentWebSearch:
    """Test agent web search tool resolution."""

    @patch("components.agent.resolve_credential_for_node")
    @patch("components.agent._get_ai_model_extra")
    @patch("components.agent.resolve_web_search_tools")
    def test_agent_with_native_search(self, mock_resolve, mock_extra, mock_cred):
        """Test agent injects native search tools when configured."""
        from components.agent import _get_agent_tools
        
        # Setup mocks
        mock_cred.return_value = SimpleNamespace(provider_type="anthropic", api_key="test-key", base_url="")
        mock_extra.return_value = {"use_native_search": True}
        mock_resolve.return_value = (
            [{"type": "web_search_20250305", "name": "web_search"}],  # native
            []  # lc_tools
        )
        
        node = MagicMock()
        node.node_id = "test-agent"
        node.component_type = "agent"
        
        tools, tool_metadata = _get_agent_tools(node)
        
        # Should have native search tool
        assert len(tools) > 0

    @patch("components.agent.resolve_credential_for_node")
    @patch("components.agent._get_ai_model_extra")
    @patch("components.agent.resolve_web_search_tools")
    def test_agent_with_searxng(self, mock_resolve, mock_extra, mock_cred):
        """Test agent uses SearXNG when native not enabled."""
        from components.agent import _get_agent_tools
        
        # Setup mocks
        mock_cred.return_value = SimpleNamespace(provider_type="openai", api_key="test-key")
        mock_extra.return_value = {"use_native_search": False}
        mock_resolve.return_value = (
            [],  # native
            [{"type": "search", "name": "search"}]  # lc_tools
        )
        
        node = MagicMock()
        node.node_id = "test-agent"
        
        tools, tool_metadata = _get_agent_tools(node)
        
        # Should have LC tools
        assert len(tools) > 0


class TestDeepAgentWebSearch:
    """Test deep_agent web search tool resolution."""

    @patch("components.deep_agent.resolve_credential_for_node")
    @patch("components.deep_agent._get_ai_model_extra")
    @patch("components.deep_agent.resolve_web_search_tools")
    def test_deep_agent_with_native_search(self, mock_resolve, mock_extra, mock_cred):
        """Test deep_agent injects native search tools."""
        from components.deep_agent import _get_deep_agent_tools
        
        # Setup mocks
        mock_cred.return_value = SimpleNamespace(provider_type="anthropic", api_key="test-key")
        mock_extra.return_value = {"use_native_search": True}
        mock_resolve.return_value = (
            [{"type": "web_search_20250305", "name": "web_search"}],
            []
        )
        
        node = MagicMock()
        node.node_id = "test-deep-agent"
        
        tools, tool_metadata = _get_deep_agent_tools(node)
        
        assert len(tools) > 0


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
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            {"role": "assistant", "content": [
                {"type": "thinking", "text": "let me think"},
                {"type": "text", "text": "answer"},
            ]},
        ]
        
        result = strip_thinking_blocks(messages)
        
        # Should remove thinking blocks
        content = result[1]["content"]
        types = [c["type"] for c in content]
        assert "thinking" not in types
        assert "text" in types

    def test_strip_web_search_blocks(self):
        """Test stripping web search blocks from messages."""
        from components._agent_shared import strip_web_search_blocks
        
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "search for X"}]},
            {"role": "assistant", "content": [
                {"type": "web_search_20250305", "id": "search1"},
                {"type": "text", "text": "here are results"},
            ]},
        ]
        
        result = strip_web_search_blocks(messages)
        
        content = result[1]["content"]
        types = [c["type"] for c in content]
        assert "web_search_20250305" not in types

    def test_wrap_llm_with_native_tools(self):
        """Test wrapping LLM with native tools."""
        from components._agent_shared import _wrap_llm_with_native_tools
        
        mock_llm = MagicMock()
        mock_llm.some_attr = "value"
        
        native_tools = [{"type": "web_search", "name": "web_search"}]
        
        wrapped = _wrap_llm_with_native_tools(mock_llm, native_tools)
        
        # Should be wrapped in NativeSearchWrapper
        assert hasattr(wrapped, 'bind_tools')
