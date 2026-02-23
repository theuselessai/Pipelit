"""Tests for services.context — context window lookups and message trimming."""

import pytest
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from services.context import (
    DEFAULT_CONTEXT_WINDOW,
    get_context_window,
    trim_messages_for_model,
)


class TestGetContextWindow:
    def test_claude_models(self):
        assert get_context_window("claude-3-5-sonnet-20241022") == 200_000
        assert get_context_window("claude-sonnet-4-20250514") == 200_000
        assert get_context_window("claude-opus-4-20250514") == 200_000

    def test_gpt4o(self):
        assert get_context_window("gpt-4o-2024-08-06") == 128_000
        assert get_context_window("gpt-4o-mini") == 128_000

    def test_gpt4(self):
        assert get_context_window("gpt-4-0613") == 8_192

    def test_gpt35(self):
        assert get_context_window("gpt-3.5-turbo-0125") == 16_384

    def test_o1_o3(self):
        assert get_context_window("o1-preview") == 200_000
        assert get_context_window("o3-mini") == 200_000

    def test_unknown_returns_default(self):
        assert get_context_window("some-unknown-model") == DEFAULT_CONTEXT_WINDOW

    def test_empty_returns_default(self):
        assert get_context_window("") == DEFAULT_CONTEXT_WINDOW

    def test_case_insensitive(self):
        assert get_context_window("Claude-3-5-Sonnet") == 200_000
        assert get_context_window("GPT-4o") == 128_000


class TestTrimMessagesForModel:
    def test_under_budget_noop(self):
        """Messages that fit within budget should be returned unchanged."""
        messages = [
            SystemMessage(content="You are helpful."),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
        ]
        result = trim_messages_for_model(messages, "claude-3-5-sonnet")
        assert len(result) == len(messages)

    def test_system_message_preserved(self):
        """System message should always be preserved even when trimming."""
        messages = [SystemMessage(content="System")]
        # Add enough messages to potentially trigger trimming
        for i in range(100):
            messages.append(HumanMessage(content=f"Question {i}"))
            messages.append(AIMessage(content=f"Answer {i}"))
        result = trim_messages_for_model(messages, "gpt-4")
        # System message should be first
        assert result[0].content == "System"

    def test_empty_messages(self):
        """Empty message list should return empty."""
        result = trim_messages_for_model([], "claude-3-5-sonnet")
        assert result == []

    def test_unknown_model_uses_default(self):
        """Unknown model should use default context window and still work."""
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi"),
        ]
        result = trim_messages_for_model(messages, "unknown-model-xyz")
        assert len(result) == len(messages)
