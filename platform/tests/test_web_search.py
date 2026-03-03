"""Tests for services/web_search.py — web search resolution logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.web_search import (
    is_anthropic_native,
    resolve_web_search_tools,
)


# ── Provider detection ────────────────────────────────────────────────────────


class TestIsAnthropicNative:
    def test_true_anthropic_no_base_url(self):
        cred = SimpleNamespace(provider_type="anthropic", base_url="")
        assert is_anthropic_native(cred) is True

    def test_true_anthropic_with_anthropic_url(self):
        cred = SimpleNamespace(provider_type="anthropic", base_url="https://api.anthropic.com/v1")
        assert is_anthropic_native(cred) is True

    def test_false_anthropic_with_proxy_url(self):
        """MiniMax via Anthropic-compatible proxy is NOT native."""
        cred = SimpleNamespace(provider_type="anthropic", base_url="https://api.minimax.io/anthropic")
        assert is_anthropic_native(cred) is False

    def test_false_openai_provider(self):
        cred = SimpleNamespace(provider_type="openai", base_url="")
        assert is_anthropic_native(cred) is False

    def test_true_anthropic_none_base_url(self):
        cred = SimpleNamespace(provider_type="anthropic", base_url=None)
        assert is_anthropic_native(cred) is True


# ── resolve_web_search_tools ──────────────────────────────────────────────────


class TestResolveWebSearchTools:
    def _mock_no_searxng(self, db):
        """Configure db mock to return no SearXNG credential."""
        db.query.return_value.join.return_value.filter.return_value.order_by.return_value.first.return_value = None

    def _mock_searxng(self, db):
        """Configure db mock to return a SearXNG credential."""
        searxng_cred = SimpleNamespace(
            config={"url": "http://localhost:8888"},
            tool_type="searxng",
            is_preferred=False,
        )
        mock_base = MagicMock()
        mock_base.tool_credential = searxng_cred
        mock_base.name = "My SearXNG"
        mock_base.id = 1
        db.query.return_value.join.return_value.filter.return_value.order_by.return_value.first.return_value = mock_base

    def test_searxng_is_default_when_no_native_opt_in(self):
        """SearXNG is the default for Anthropic credentials when native is not opted in."""
        cred = SimpleNamespace(provider_type="anthropic", base_url="")
        db = MagicMock()
        self._mock_searxng(db)

        native, lc = resolve_web_search_tools(cred, db)
        assert native == []
        assert len(lc) == 1
        assert lc[0].name == "web_search"

    def test_anthropic_native_only_when_opted_in(self):
        """Anthropic native search only returned when use_native_search=True and no SearXNG."""
        cred = SimpleNamespace(provider_type="anthropic", base_url="")
        db = MagicMock()
        self._mock_no_searxng(db)

        native, lc = resolve_web_search_tools(cred, db, use_native_search=True)
        assert len(native) == 1
        assert native[0]["type"] == "web_search_20250305"
        assert native[0]["name"] == "web_search"
        assert lc == []

    def test_anthropic_native_rejected_without_opt_in(self):
        """Anthropic credential without opt-in returns no search (when no SearXNG)."""
        cred = SimpleNamespace(provider_type="anthropic", base_url="")
        db = MagicMock()
        self._mock_no_searxng(db)

        native, lc = resolve_web_search_tools(cred, db)
        assert native == []
        assert lc == []

    def test_anthropic_native_returns_native_tool(self):
        """Explicit opt-in with no SearXNG returns native tool."""
        cred = SimpleNamespace(provider_type="anthropic", base_url="")
        db = MagicMock()
        self._mock_no_searxng(db)

        native, lc = resolve_web_search_tools(cred, db, use_native_search=True)
        assert len(native) == 1
        assert native[0]["type"] == "web_search_20250305"
        assert native[0]["name"] == "web_search"
        assert lc == []

    def test_glm_falls_through_to_searxng(self):
        """GLM uses SearXNG like all non-Anthropic providers."""
        cred = SimpleNamespace(provider_type="glm", base_url="")
        db = MagicMock()
        self._mock_no_searxng(db)
        native, lc = resolve_web_search_tools(cred, db)
        assert native == []
        assert lc == []

    def test_searxng_fallback(self):
        cred = SimpleNamespace(provider_type="openai", base_url="")
        db = MagicMock()
        self._mock_searxng(db)

        native, lc = resolve_web_search_tools(cred, db)
        assert native == []
        assert len(lc) == 1
        assert lc[0].name == "web_search"

    def test_no_search_available(self):
        cred = SimpleNamespace(provider_type="openai", base_url="")
        db = MagicMock()
        self._mock_no_searxng(db)

        native, lc = resolve_web_search_tools(cred, db)
        assert native == []
        assert lc == []

    def test_anthropic_proxy_falls_through_to_searxng(self):
        """MiniMax via Anthropic proxy should NOT get native tools, should try SearXNG."""
        cred = SimpleNamespace(provider_type="anthropic", base_url="https://api.minimax.io/anthropic")
        db = MagicMock()
        self._mock_no_searxng(db)

        native, lc = resolve_web_search_tools(cred, db)
        assert native == []
        assert lc == []

    def test_searxng_preferred_credential_selected(self):
        """When a preferred SearXNG credential exists, it should be selected."""
        cred = SimpleNamespace(provider_type="openai", base_url="")
        db = MagicMock()
        preferred_searxng = SimpleNamespace(
            config={"url": "http://preferred:8888"},
            tool_type="searxng",
            is_preferred=True,
        )
        mock_base = MagicMock()
        mock_base.tool_credential = preferred_searxng
        mock_base.name = "Preferred SearXNG"
        mock_base.id = 2
        db.query.return_value.join.return_value.filter.return_value.order_by.return_value.first.return_value = mock_base

        native, lc = resolve_web_search_tools(cred, db)
        assert native == []
        assert len(lc) == 1
        assert lc[0].name == "web_search"

    def test_native_opt_in_overrides_searxng(self):
        """With use_native_search=True, Anthropic native overrides SearXNG."""
        cred = SimpleNamespace(provider_type="anthropic", base_url="")
        db = MagicMock()
        self._mock_searxng(db)

        native, lc = resolve_web_search_tools(cred, db, use_native_search=True)
        assert len(native) == 1
        assert native[0]["type"] == "web_search_20250305"
        assert lc == []

    def test_native_opt_in_ignored_for_non_anthropic(self):
        """use_native_search=True has no effect for non-Anthropic providers."""
        cred = SimpleNamespace(provider_type="openai", base_url="")
        db = MagicMock()
        self._mock_no_searxng(db)

        native, lc = resolve_web_search_tools(cred, db, use_native_search=True)
        assert native == []
        assert lc == []


# ── strip_web_search_blocks ───────────────────────────────────────────────────


class TestStripWebSearchBlocks:
    def test_strips_server_tool_use(self):
        from components._agent_shared import strip_web_search_blocks

        msg = SimpleNamespace(type="ai", content=[
            {"type": "text", "text": "Here are the results:"},
            {"type": "server_tool_use", "id": "abc", "name": "web_search"},
            {"type": "web_search_tool_result", "content": "..."},
            {"type": "text", "text": "Based on the search..."},
        ])
        strip_web_search_blocks([msg])
        assert len(msg.content) == 2
        assert all(b["type"] == "text" for b in msg.content)

    def test_ignores_non_ai_messages(self):
        from components._agent_shared import strip_web_search_blocks

        msg = SimpleNamespace(type="human", content=[
            {"type": "server_tool_use", "id": "abc"},
        ])
        strip_web_search_blocks([msg])
        assert len(msg.content) == 1  # unchanged

    def test_ignores_string_content(self):
        from components._agent_shared import strip_web_search_blocks

        msg = SimpleNamespace(type="ai", content="just a string")
        strip_web_search_blocks([msg])
        assert msg.content == "just a string"

    def test_strips_web_search_result(self):
        from components._agent_shared import strip_web_search_blocks

        msg = SimpleNamespace(type="ai", content=[
            {"type": "text", "text": "Answer"},
            {"type": "web_search_result", "data": "..."},
        ])
        strip_web_search_blocks([msg])
        assert len(msg.content) == 1
        assert msg.content[0]["type"] == "text"

    def test_strips_empty_text_blocks(self):
        from components._agent_shared import strip_web_search_blocks

        msg = SimpleNamespace(type="ai", content=[
            {"type": "text", "text": ""},
            {"type": "text", "text": "Real content"},
            {"type": "text", "text": ""},
        ])
        strip_web_search_blocks([msg])
        assert len(msg.content) == 1
        assert msg.content[0]["text"] == "Real content"


    def test_strips_citations_from_text_blocks(self):
        from components._agent_shared import strip_web_search_blocks

        msg = SimpleNamespace(type="ai", content=[
            {"type": "text", "text": "Based on search results...", "citations": [
                {"type": "web_search_result_location", "cited_text": "...", "encrypted_index": "abc"}
            ]},
            {"type": "server_tool_use", "id": "abc", "name": "web_search"},
            {"type": "web_search_tool_result", "content": "..."},
            {"type": "text", "text": "Final answer"},
        ])
        strip_web_search_blocks([msg])
        assert len(msg.content) == 2
        assert all(b["type"] == "text" for b in msg.content)
        assert "citations" not in msg.content[0]  # citations stripped
        assert "citations" not in msg.content[1]


class TestStripThinkingBlocksEmptyText:
    def test_strips_empty_text_blocks(self):
        from components._agent_shared import strip_thinking_blocks

        msg = SimpleNamespace(type="ai", content=[
            {"type": "thinking", "thinking": "..."},
            {"type": "text", "text": ""},
            {"type": "text", "text": "Answer"},
        ])
        strip_thinking_blocks([msg])
        assert len(msg.content) == 1
        assert msg.content[0]["text"] == "Answer"

    def test_strips_pydantic_empty_text_blocks(self):
        """Pydantic v2 TextBlock objects from checkpointer are caught."""
        from components._agent_shared import strip_thinking_blocks

        pydantic_block = SimpleNamespace(type="text", text="")
        msg = SimpleNamespace(type="ai", content=[
            {"type": "thinking", "thinking": "..."},
            pydantic_block,
            {"type": "text", "text": "Answer"},
        ])
        strip_thinking_blocks([msg])
        assert len(msg.content) == 1
        assert msg.content[0]["text"] == "Answer"


# ── strip_empty_text_blocks (all message types) ──────────────────────────────


class TestStripEmptyTextBlocks:
    def test_strips_from_human_message(self):
        from components._agent_shared import strip_empty_text_blocks

        msg = SimpleNamespace(type="human", content=[
            {"type": "text", "text": ""},
            {"type": "text", "text": "Hello"},
        ])
        strip_empty_text_blocks([msg])
        assert len(msg.content) == 1
        assert msg.content[0]["text"] == "Hello"

    def test_strips_from_tool_message(self):
        from components._agent_shared import strip_empty_text_blocks

        msg = SimpleNamespace(type="tool", content=[
            {"type": "text", "text": "Result"},
            {"type": "text", "text": ""},
        ])
        strip_empty_text_blocks([msg])
        assert len(msg.content) == 1
        assert msg.content[0]["text"] == "Result"

    def test_ignores_string_content(self):
        from components._agent_shared import strip_empty_text_blocks

        msg = SimpleNamespace(type="human", content="just a string")
        strip_empty_text_blocks([msg])
        assert msg.content == "just a string"

    def test_leaves_nonempty_blocks_intact(self):
        from components._agent_shared import strip_empty_text_blocks

        msg = SimpleNamespace(type="ai", content=[
            {"type": "text", "text": "First"},
            {"type": "tool_use", "id": "x", "name": "y", "input": {}},
            {"type": "text", "text": "Second"},
        ])
        strip_empty_text_blocks([msg])
        assert len(msg.content) == 3

    def test_strips_pydantic_empty_text_blocks(self):
        """Pydantic v2 TextBlock objects from checkpointer are caught."""
        from components._agent_shared import strip_empty_text_blocks

        pydantic_block = SimpleNamespace(type="text", text="")
        msg = SimpleNamespace(type="ai", content=[
            pydantic_block,
            {"type": "text", "text": "Real content"},
        ])
        strip_empty_text_blocks([msg])
        assert len(msg.content) == 1
        assert msg.content[0]["text"] == "Real content"

    def test_keeps_pydantic_nonempty_text_blocks(self):
        """Pydantic v2 TextBlock with actual text should be preserved."""
        from components._agent_shared import strip_empty_text_blocks

        pydantic_block = SimpleNamespace(type="text", text="Keep me")
        msg = SimpleNamespace(type="ai", content=[
            pydantic_block,
            {"type": "text", "text": "Also keep"},
        ])
        strip_empty_text_blocks([msg])
        assert len(msg.content) == 2

    def test_strips_mixed_dict_and_pydantic_empty_blocks(self):
        """Mix of dict and Pydantic empty text blocks in one message."""
        from components._agent_shared import strip_empty_text_blocks

        msg = SimpleNamespace(type="human", content=[
            {"type": "text", "text": ""},
            SimpleNamespace(type="text", text=""),
            {"type": "text", "text": "Survivor"},
            SimpleNamespace(type="text", text="Also survives"),
        ])
        strip_empty_text_blocks([msg])
        assert len(msg.content) == 2


# ── _wrap_llm_with_native_tools ───────────────────────────────────────────────


class TestWrapLlmWithNativeTools:
    def test_injects_native_tools(self):
        from components._agent_shared import _wrap_llm_with_native_tools

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = "bound"

        native = [{"type": "web_search_20250305", "name": "web_search"}]
        wrapped = _wrap_llm_with_native_tools(mock_llm, native)

        # Call bind_tools with regular tools
        result = wrapped.bind_tools(["tool_a", "tool_b"])

        # Original bind_tools should have been called with regular + native
        mock_llm.bind_tools.assert_called_once()
        call_args = mock_llm.bind_tools.call_args[0][0]
        assert call_args == ["tool_a", "tool_b", {"type": "web_search_20250305", "name": "web_search"}]
        assert result == "bound"

    def test_preserves_kwargs(self):
        from components._agent_shared import _wrap_llm_with_native_tools

        mock_llm = MagicMock()
        wrapped = _wrap_llm_with_native_tools(mock_llm, [{"type": "native"}])
        wrapped.bind_tools([], tool_choice="auto")
        mock_llm.bind_tools.assert_called_once_with([{"type": "native"}], tool_choice="auto")

    def test_delegates_other_attrs(self):
        from components._agent_shared import _wrap_llm_with_native_tools

        mock_llm = MagicMock()
        mock_llm.model_name = "claude-sonnet-4-6"
        wrapped = _wrap_llm_with_native_tools(mock_llm, [])
        assert wrapped.model_name == "claude-sonnet-4-6"
