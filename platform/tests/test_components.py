"""Tests for simple component factories — calculator, datetime, trigger, subworkflow,
human_confirmation, run_command."""

from __future__ import annotations

import ast
import subprocess
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_node(component_type="test", extra_config=None, system_prompt=None):
    """Build a minimal node-like object for component factories."""
    config = SimpleNamespace(
        component_type=component_type,
        extra_config=extra_config or {},
        system_prompt=system_prompt or "",
    )
    return SimpleNamespace(
        node_id="test_node_1",
        workflow_id=1,
        component_type=component_type,
        component_config=config,
    )


# ── Calculator ─────────────────────────────────────────────────────────────────

class TestCalculator:
    def _get_tool(self, node=None):
        from components.calculator import calculator_factory
        return calculator_factory(node or _make_node("calculator"))

    def test_addition(self):
        t = self._get_tool()
        assert t.invoke({"expression": "2 + 3"}) == "5"

    def test_subtraction(self):
        t = self._get_tool()
        assert t.invoke({"expression": "10 - 4"}) == "6"

    def test_multiplication(self):
        t = self._get_tool()
        assert t.invoke({"expression": "6 * 7"}) == "42"

    def test_division(self):
        t = self._get_tool()
        assert t.invoke({"expression": "15 / 4"}) == "3.75"

    def test_floor_division(self):
        t = self._get_tool()
        assert t.invoke({"expression": "15 // 4"}) == "3"

    def test_modulo(self):
        t = self._get_tool()
        assert t.invoke({"expression": "10 % 3"}) == "1"

    def test_power(self):
        t = self._get_tool()
        assert t.invoke({"expression": "2 ** 10"}) == "1024"

    def test_unary_neg(self):
        t = self._get_tool()
        assert t.invoke({"expression": "-5 + 3"}) == "-2"

    def test_unary_pos(self):
        t = self._get_tool()
        assert t.invoke({"expression": "+5"}) == "5"

    def test_complex_expression(self):
        t = self._get_tool()
        assert t.invoke({"expression": "(2 + 3) * 4 - 1"}) == "19"

    def test_float(self):
        t = self._get_tool()
        assert t.invoke({"expression": "3.14 * 2"}) == "6.28"

    def test_invalid_expression(self):
        t = self._get_tool()
        result = t.invoke({"expression": "foo + bar"})
        assert "Error" in result

    def test_string_constant_rejected(self):
        t = self._get_tool()
        result = t.invoke({"expression": "'hello'"})
        assert "Error" in result

    def test_unsupported_expression(self):
        t = self._get_tool()
        result = t.invoke({"expression": "[1, 2, 3]"})
        assert "Error" in result

    def test_division_by_zero(self):
        t = self._get_tool()
        result = t.invoke({"expression": "1 / 0"})
        assert "Error" in result


class TestSafeEval:
    """Direct tests for the _safe_eval helper."""

    def test_unsupported_operator(self):
        from components.calculator import _safe_eval

        # BinOp with unsupported operator type
        tree = ast.parse("1 << 2", mode="eval")
        with pytest.raises(ValueError, match="Unsupported operator"):
            _safe_eval(tree)


# ── Datetime ───────────────────────────────────────────────────────────────────

class TestDatetime:
    def test_utc_default(self):
        from components.datetime_tool import datetime_factory
        node = _make_node("datetime")
        tool = datetime_factory(node)
        result = tool.invoke({})
        assert "UTC" in result

    def test_with_timezone(self):
        from components.datetime_tool import datetime_factory
        node = _make_node("datetime", extra_config={"timezone": "US/Eastern"})
        tool = datetime_factory(node)
        result = tool.invoke({})
        # Should contain a timezone abbreviation
        assert "E" in result or "UTC" not in result

    def test_invalid_timezone(self):
        from components.datetime_tool import datetime_factory
        node = _make_node("datetime", extra_config={"timezone": "Invalid/Nonexistent"})
        tool = datetime_factory(node)
        result = tool.invoke({})
        assert "Error" in result


# ── Trigger pass-through ──────────────────────────────────────────────────────

class TestTrigger:
    def test_all_trigger_types_registered(self):
        from components import COMPONENT_REGISTRY
        expected = [
            "trigger_telegram", "trigger_schedule",
            "trigger_manual", "trigger_workflow", "trigger_error", "trigger_chat",
        ]
        for ct in expected:
            assert ct in COMPONENT_REGISTRY, f"{ct} not registered"

    def test_passthrough_returns_trigger_payload(self):
        from components import COMPONENT_REGISTRY
        factory = COMPONENT_REGISTRY["trigger_manual"]
        run_fn = factory(None)
        state = {"messages": [], "trigger": {"text": "hello", "payload": {"k": "v"}}}
        result = run_fn(state)
        assert result == {"text": "hello", "payload": {"k": "v"}}
        # Must be a copy, not the original trigger dict
        assert result is not state["trigger"]


# ── Subworkflow ───────────────────────────────────────────────────────────────

class TestSubworkflow:
    def test_returns_child_result_when_available(self):
        from components.subworkflow import subworkflow_factory
        node = _make_node("workflow")
        node.subworkflow_id = None
        fn = subworkflow_factory(node)
        state = {"_subworkflow_results": {"test_node_1": {"message": "done"}}}
        result = fn(state)
        assert result == {"output": {"message": "done"}}


# ── Human Confirmation ────────────────────────────────────────────────────────

class TestHumanConfirmation:
    def _factory(self, prompt="Confirm?"):
        from components.human_confirmation import human_confirmation_factory
        node = _make_node("human_confirmation", extra_config={"prompt": prompt})
        return human_confirmation_factory(node)

    def test_no_resume_input(self):
        fn = self._factory()
        result = fn({})
        assert result["confirmed"] is False
        assert result["_route"] == "cancelled"
        assert result["prompt"] == "Confirm?"

    def test_confirmed_yes(self):
        fn = self._factory()
        for val in ("yes", "Yes", "YES", "y", "Y", "confirm", "true", "1"):
            result = fn({"_resume_input": val})
            assert result["confirmed"] is True
            assert result["_route"] == "confirmed"

    def test_cancelled_no(self):
        fn = self._factory()
        for val in ("no", "cancel", "false", "0", "nah", ""):
            result = fn({"_resume_input": val})
            assert result["confirmed"] is False
            assert result["_route"] == "cancelled"

    def test_default_prompt(self):
        from components.human_confirmation import human_confirmation_factory
        node = _make_node("human_confirmation", extra_config={})
        fn = human_confirmation_factory(node)
        result = fn({})
        assert result["prompt"] == "Please confirm to proceed."


# ── Run Command ───────────────────────────────────────────────────────────────

class TestRunCommand:
    def _get_tool(self):
        from components.run_command import run_command_factory
        return run_command_factory(_make_node("run_command"))

    def test_echo(self):
        tool = self._get_tool()
        result = tool.invoke({"command": "echo hello"})
        assert "hello" in result

    def test_stderr(self):
        tool = self._get_tool()
        result = tool.invoke({"command": "echo error >&2"})
        assert "STDERR" in result
        assert "error" in result

    def test_nonzero_exit(self):
        tool = self._get_tool()
        result = tool.invoke({"command": "exit 42"})
        assert "exit code: 42" in result

    def test_no_output(self):
        tool = self._get_tool()
        result = tool.invoke({"command": "true"})
        assert result == "(no output)"

    def test_timeout(self):
        tool = self._get_tool()
        with patch("components.run_command.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 60)):
            result = tool.invoke({"command": "sleep 999"})
        assert "timed out" in result

    def test_generic_error(self):
        tool = self._get_tool()
        with patch("components.run_command.subprocess.run", side_effect=OSError("no such file")):
            result = tool.invoke({"command": "nonexistent"})
        assert "Error" in result


