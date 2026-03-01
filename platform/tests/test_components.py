"""Tests for simple component factories — trigger, subworkflow,
human_confirmation, run_command."""

from __future__ import annotations

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

    def test_no_sandbox_returns_error(self):
        """Without a workspace/sandbox backend, run_command returns an error."""
        tool = self._get_tool()
        result = tool.invoke({"command": "echo hello"})
        assert "No sandbox backend available" in result

    def test_with_sandbox_backend(self):
        """With a sandbox backend, run_command uses it."""
        from components.run_command import run_command_factory
        mock_backend = MagicMock()
        mock_backend.execute.return_value = MagicMock(output="hello\n", exit_code=0)

        with patch("components.run_command._resolve_parent_workspace", return_value={"workspace_id": 1}), \
             patch("components._agent_shared._build_backend", return_value=mock_backend):
            tool = run_command_factory(_make_node("run_command"))
        result = tool.invoke({"command": "echo hello"})
        assert "hello" in result


