"""Tests for services/token_usage.py — pricing, extraction, and cost calculation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.token_usage import (
    calculate_cost,
    extract_usage_from_messages,
    extract_usage_from_response,
    get_model_name_for_node,
    get_model_pricing,
    merge_usage,
)


class TestGetModelPricing:
    def test_openai_gpt4o(self):
        assert get_model_pricing("gpt-4o") == (2.50, 10.00)

    def test_openai_gpt4o_mini(self):
        assert get_model_pricing("gpt-4o-mini") == (0.15, 0.60)

    def test_openai_gpt4o_mini_dated(self):
        """Model names with date suffixes should still match."""
        assert get_model_pricing("gpt-4o-mini-2024-07-18") == (0.15, 0.60)

    def test_anthropic_claude_sonnet(self):
        assert get_model_pricing("claude-sonnet-4-20250514") == (3.00, 15.00)

    def test_anthropic_claude_opus(self):
        assert get_model_pricing("claude-opus-4-20250514") == (15.00, 75.00)

    def test_anthropic_claude_35_sonnet(self):
        assert get_model_pricing("claude-3-5-sonnet-20241022") == (3.00, 15.00)

    def test_unknown_model(self):
        assert get_model_pricing("some-local-llama-model") == (0.0, 0.0)

    def test_empty_model(self):
        assert get_model_pricing("") == (0.0, 0.0)

    def test_case_insensitive(self):
        assert get_model_pricing("GPT-4o-MINI") == (0.15, 0.60)


class TestCalculateCost:
    def test_basic_cost(self):
        # gpt-4o: $2.50/1M input, $10.00/1M output
        cost = calculate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert cost == 12.50

    def test_small_usage(self):
        # 1000 input tokens, 500 output tokens with gpt-4o-mini
        cost = calculate_cost("gpt-4o-mini", 1000, 500)
        expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_zero_tokens(self):
        assert calculate_cost("gpt-4o", 0, 0) == 0.0

    def test_unknown_model_zero_cost(self):
        assert calculate_cost("unknown-model", 10000, 10000) == 0.0


class TestExtractUsageFromResponse:
    def test_with_usage_metadata(self):
        msg = MagicMock()
        msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
        result = extract_usage_from_response(msg)
        assert result == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    def test_no_usage_metadata(self):
        msg = MagicMock(spec=[])  # No usage_metadata attribute
        result = extract_usage_from_response(msg)
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def test_none_usage_metadata(self):
        msg = MagicMock()
        msg.usage_metadata = None
        result = extract_usage_from_response(msg)
        assert result == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


class TestExtractUsageFromMessages:
    def test_multiple_ai_messages(self):
        msg1 = MagicMock()
        msg1.type = "ai"
        msg1.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        msg2 = MagicMock()
        msg2.type = "ai"
        msg2.usage_metadata = {"input_tokens": 200, "output_tokens": 100}

        # Non-AI message should be skipped
        msg3 = MagicMock()
        msg3.type = "human"

        result = extract_usage_from_messages([msg1, msg2, msg3])
        assert result == {
            "input_tokens": 300,
            "output_tokens": 150,
            "total_tokens": 450,
            "llm_calls": 2,
        }

    def test_empty_messages(self):
        result = extract_usage_from_messages([])
        assert result == {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_calls": 0,
        }

    def test_ai_message_without_usage(self):
        msg = MagicMock()
        msg.type = "ai"
        msg.usage_metadata = None
        result = extract_usage_from_messages([msg])
        assert result["llm_calls"] == 0
        assert result["total_tokens"] == 0


class TestMergeUsage:
    def test_basic_merge(self):
        a = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "llm_calls": 1}
        b = {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300, "llm_calls": 2}
        result = merge_usage(a, b)
        assert result == {
            "input_tokens": 300,
            "output_tokens": 150,
            "total_tokens": 450,
            "llm_calls": 3,
        }

    def test_merge_with_cost(self):
        a = {"input_tokens": 100, "cost_usd": 0.01}
        b = {"input_tokens": 200, "cost_usd": 0.02}
        result = merge_usage(a, b)
        assert result["input_tokens"] == 300
        assert abs(result["cost_usd"] - 0.03) < 1e-10

    def test_merge_empty(self):
        a = {"input_tokens": 100}
        b = {}
        result = merge_usage(a, b)
        assert result == {"input_tokens": 100}

    def test_merge_new_keys(self):
        a = {"input_tokens": 100}
        b = {"output_tokens": 50}
        result = merge_usage(a, b)
        assert result == {"input_tokens": 100, "output_tokens": 50}


class TestGetModelNameForNode:
    def test_ai_model_node(self):
        node = MagicMock()
        node.component_config.component_type = "ai_model"
        node.component_config.model_name = "gpt-4o"
        assert get_model_name_for_node(node) == "gpt-4o"

    def test_ai_model_node_no_model(self):
        node = MagicMock()
        node.component_config.component_type = "ai_model"
        node.component_config.model_name = None
        assert get_model_name_for_node(node) == ""

    def test_agent_node_with_llm_config(self):
        """Agent nodes follow llm_model_config_id to find the model name."""
        from unittest.mock import patch

        node = MagicMock()
        node.component_config.component_type = "agent"
        node.component_config.llm_model_config_id = 42

        mock_tc = MagicMock()
        mock_tc.component_type = "ai_model"
        mock_tc.model_name = "claude-sonnet-4-20250514"

        mock_db = MagicMock()
        mock_db.get.return_value = mock_tc

        with patch("database.SessionLocal", return_value=mock_db):
            result = get_model_name_for_node(node)

        assert result == "claude-sonnet-4-20250514"

    def test_node_without_llm(self):
        node = MagicMock()
        node.component_config.component_type = "agent"
        node.component_config.llm_model_config_id = None
        assert get_model_name_for_node(node) == ""

    def test_db_query_failure_returns_empty(self):
        """DB errors during model name lookup return empty string."""
        node = MagicMock()
        node.component_config.component_type = "agent"
        node.component_config.llm_model_config_id = 99

        mock_db = MagicMock()
        mock_db.get.side_effect = RuntimeError("DB error")

        with patch("database.SessionLocal", return_value=mock_db):
            result = get_model_name_for_node(node)
        assert result == ""
        mock_db.close.assert_called_once()

    def test_db_returns_non_ai_model(self):
        """If the linked config is not ai_model, return empty string."""
        node = MagicMock()
        node.component_config.component_type = "agent"
        node.component_config.llm_model_config_id = 10

        mock_tc = MagicMock()
        mock_tc.component_type = "switch"
        mock_tc.model_name = None

        mock_db = MagicMock()
        mock_db.get.return_value = mock_tc

        with patch("database.SessionLocal", return_value=mock_db):
            result = get_model_name_for_node(node)
        assert result == ""
        mock_db.close.assert_called_once()

    def test_db_returns_none(self):
        """If the linked config ID doesn't exist, return empty string."""
        node = MagicMock()
        node.component_config.component_type = "agent"
        node.component_config.llm_model_config_id = 999

        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch("database.SessionLocal", return_value=mock_db):
            result = get_model_name_for_node(node)
        assert result == ""


class TestMergeUsageEdgeCases:
    def test_non_numeric_values_take_new(self):
        """Non-numeric values should take the new value."""
        a = {"model": "gpt-4o", "input_tokens": 100}
        b = {"model": "claude-3", "input_tokens": 200}
        result = merge_usage(a, b)
        assert result["model"] == "claude-3"
        assert result["input_tokens"] == 300


class TestPersistExecutionCosts:
    def test_persist_costs_from_state(self):
        from services.orchestrator import _persist_execution_costs

        execution = MagicMock()
        state = {
            "_execution_token_usage": {
                "input_tokens": 500,
                "output_tokens": 200,
                "total_tokens": 700,
                "cost_usd": 0.05,
                "llm_calls": 3,
            }
        }
        _persist_execution_costs(execution, state)
        assert execution.total_input_tokens == 500
        assert execution.total_output_tokens == 200
        assert execution.total_tokens == 700
        assert execution.total_cost_usd == 0.05
        assert execution.llm_calls == 3

    def test_persist_costs_empty_state(self):
        from services.orchestrator import _persist_execution_costs

        execution = MagicMock()
        _persist_execution_costs(execution, {})
        assert execution.total_input_tokens == 0
        assert execution.total_output_tokens == 0
        assert execution.total_tokens == 0
        assert execution.total_cost_usd == 0.0
        assert execution.llm_calls == 0


class TestCheckBudget:
    def test_no_task_returns_none(self):
        from services.orchestrator import _check_budget

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = _check_budget("exec-1", {}, mock_db)
        assert result is None

    def test_no_epic_returns_none(self):
        from services.orchestrator import _check_budget

        mock_task = MagicMock()
        mock_task.epic = None
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task
        result = _check_budget("exec-1", {}, mock_db)
        assert result is None

    def test_token_budget_exceeded(self):
        from services.orchestrator import _check_budget

        mock_epic = MagicMock()
        mock_epic.budget_tokens = 1000
        mock_epic.spent_tokens = 800
        mock_epic.budget_usd = None
        mock_task = MagicMock()
        mock_task.epic = mock_epic
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        state = {"_execution_token_usage": {"total_tokens": 300, "cost_usd": 0.01}}
        result = _check_budget("exec-1", state, mock_db)
        assert result is not None
        assert "budget exceeded" in result.lower()

    def test_usd_budget_exceeded(self):
        from services.orchestrator import _check_budget
        from decimal import Decimal

        mock_epic = MagicMock()
        mock_epic.budget_tokens = None
        mock_epic.budget_usd = Decimal("1.00")
        mock_epic.spent_usd = Decimal("0.80")
        mock_task = MagicMock()
        mock_task.epic = mock_epic
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        state = {"_execution_token_usage": {"total_tokens": 100, "cost_usd": 0.30}}
        result = _check_budget("exec-1", state, mock_db)
        assert result is not None
        assert "budget exceeded" in result.lower()

    def test_within_budget_returns_none(self):
        from services.orchestrator import _check_budget

        mock_epic = MagicMock()
        mock_epic.budget_tokens = 10000
        mock_epic.spent_tokens = 100
        mock_epic.budget_usd = None
        mock_task = MagicMock()
        mock_task.epic = mock_epic
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        state = {"_execution_token_usage": {"total_tokens": 50, "cost_usd": 0.001}}
        result = _check_budget("exec-1", state, mock_db)
        assert result is None
