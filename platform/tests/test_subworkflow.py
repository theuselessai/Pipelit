"""Tests for the subworkflow component and orchestrator integration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_node(component_type="workflow", extra_config=None, subworkflow_id=None):
    """Build a minimal node-like object for component factories."""
    config = SimpleNamespace(
        component_type=component_type,
        extra_config=extra_config or {},
        system_prompt="",
    )
    return SimpleNamespace(
        node_id="subworkflow_1",
        workflow_id=1,
        component_type=component_type,
        component_config=config,
        subworkflow_id=subworkflow_id,
    )


# ── Component factory tests ──────────────────────────────────────────────────


class TestSubworkflowComponent:
    """Tests for the subworkflow_factory component."""

    def test_returns_child_result_on_second_invocation(self):
        """When _subworkflow_results contains this node's result, return it."""
        from components.subworkflow import subworkflow_factory

        node = _make_node(extra_config={"target_workflow": "child-wf"})
        fn = subworkflow_factory(node)

        state = {
            "_subworkflow_results": {
                "subworkflow_1": {"message": "child completed"},
            },
        }
        result = fn(state)
        assert result == {"output": {"message": "child completed"}}

    @patch("components.subworkflow._create_child_execution")
    def test_first_invocation_returns_subworkflow_signal(self, mock_create):
        """First invocation (no child result) creates child and returns _subworkflow signal."""
        from components.subworkflow import subworkflow_factory

        mock_create.return_value = "child-exec-123"
        node = _make_node(extra_config={"target_workflow": "child-wf"})
        fn = subworkflow_factory(node)

        state = {
            "execution_id": "parent-exec-1",
            "trigger": {"text": "hello"},
            "node_outputs": {},
            "user_context": {"user_profile_id": 1},
        }
        result = fn(state)

        assert "_subworkflow" in result
        assert result["_subworkflow"]["child_execution_id"] == "child-exec-123"
        mock_create.assert_called_once()

    def test_empty_subworkflow_results_triggers_child_creation(self):
        """If _subworkflow_results exists but doesn't have this node, treat as first invocation."""
        from components.subworkflow import subworkflow_factory

        node = _make_node(extra_config={"target_workflow": "child-wf"})
        fn = subworkflow_factory(node)

        state = {
            "_subworkflow_results": {"other_node": {"data": "x"}},
            "execution_id": "parent-exec-1",
            "trigger": {},
            "node_outputs": {},
            "user_context": {"user_profile_id": 1},
        }
        with patch("components.subworkflow._create_child_execution", return_value="child-456"):
            result = fn(state)
        assert result["_subworkflow"]["child_execution_id"] == "child-456"


# ── Trigger payload builder tests ─────────────────────────────────────────────


class TestBuildTriggerPayload:
    def test_default_payload_includes_trigger_and_outputs(self):
        from components.subworkflow import _build_trigger_payload

        state = {
            "trigger": {"text": "hello", "chat_id": 123},
            "node_outputs": {"agent_1": {"output": "result"}},
        }
        payload = _build_trigger_payload(state, {})
        assert payload["text"] == "hello"
        assert payload["payload"]["trigger"]["chat_id"] == 123
        assert payload["payload"]["node_outputs"]["agent_1"]["output"] == "result"

    def test_input_mapping_resolves_dotted_paths(self):
        from components.subworkflow import _build_trigger_payload

        state = {
            "trigger": {"text": "hi"},
            "node_outputs": {"agent_1": {"output": "result data"}},
        }
        mapping = {
            "task_input": "node_outputs.agent_1.output",
            "user_text": "trigger.text",
        }
        payload = _build_trigger_payload(state, mapping)
        assert payload["task_input"] == "result data"
        assert payload["user_text"] == "hi"

    def test_input_mapping_returns_none_for_missing_path(self):
        from components.subworkflow import _build_trigger_payload

        state = {"trigger": {}, "node_outputs": {}}
        mapping = {"missing": "node_outputs.nonexistent.field"}
        payload = _build_trigger_payload(state, mapping)
        assert payload["missing"] is None


# ── Path resolver tests ───────────────────────────────────────────────────────


class TestResolvePath:
    def test_simple_path(self):
        from components.subworkflow import _resolve_path

        assert _resolve_path({"a": "hello"}, "a") == "hello"

    def test_nested_path(self):
        from components.subworkflow import _resolve_path

        state = {"node_outputs": {"agent_1": {"output": "data"}}}
        assert _resolve_path(state, "node_outputs.agent_1.output") == "data"

    def test_missing_key_returns_none(self):
        from components.subworkflow import _resolve_path

        assert _resolve_path({"a": {"b": 1}}, "a.c") is None

    def test_non_dict_intermediate_returns_none(self):
        from components.subworkflow import _resolve_path

        assert _resolve_path({"a": "string"}, "a.b") is None


# ── Orchestrator resume_from_child tests ─────────────────────────────────────


class TestResumeFromChild:
    """Test the _resume_from_child orchestrator function."""

    @patch("services.orchestrator._queue")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("database.SessionLocal")
    def test_injects_child_output_and_reenqueues(self, mock_session_cls, mock_load, mock_save, mock_queue):
        from services.orchestrator import _resume_from_child

        mock_load.return_value = {
            "node_outputs": {},
            "execution_id": "parent-exec-1",
        }
        mock_q = MagicMock()
        mock_queue.return_value = mock_q

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        parent_exec = MagicMock()
        parent_exec.status = "running"
        mock_db.query.return_value.filter.return_value.first.return_value = parent_exec

        _resume_from_child(
            parent_execution_id="parent-exec-1",
            parent_node_id="subworkflow_1",
            child_output={"message": "done"},
        )

        # Verify state was updated with child output
        saved_state = mock_save.call_args[0][1]
        assert saved_state["_subworkflow_results"]["subworkflow_1"] == {"message": "done"}

        # Verify node was re-enqueued
        mock_q.enqueue.assert_called_once()

    @patch("services.orchestrator.load_state")
    @patch("database.SessionLocal")
    def test_skips_if_parent_not_running(self, mock_session_cls, mock_load):
        from services.orchestrator import _resume_from_child

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        parent_exec = MagicMock()
        parent_exec.status = "failed"
        mock_db.query.return_value.filter.return_value.first.return_value = parent_exec

        _resume_from_child("parent-exec-1", "subworkflow_1", {"msg": "done"})

        mock_load.assert_not_called()

    @patch("services.orchestrator.load_state")
    @patch("database.SessionLocal")
    def test_skips_if_parent_not_found(self, mock_session_cls, mock_load):
        from services.orchestrator import _resume_from_child

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        _resume_from_child("parent-exec-1", "subworkflow_1", {"msg": "done"})

        mock_load.assert_not_called()


# ── Node type registry tests ─────────────────────────────────────────────────


class TestSubworkflowRegistry:
    def test_workflow_type_registered(self):
        import schemas.node_type_defs  # noqa: F401 — triggers registration
        from schemas.node_types import NODE_TYPE_REGISTRY

        assert "workflow" in NODE_TYPE_REGISTRY

    def test_workflow_type_spec(self):
        import schemas.node_type_defs  # noqa: F401
        from schemas.node_types import NODE_TYPE_REGISTRY

        spec = NODE_TYPE_REGISTRY["workflow"]
        assert spec.display_name == "Subworkflow"
        assert spec.category == "logic"
        assert len(spec.inputs) == 1
        assert len(spec.outputs) == 1
        assert spec.inputs[0].name == "payload"
        assert spec.outputs[0].name == "output"

    def test_workflow_type_is_executable(self):
        import schemas.node_type_defs  # noqa: F401
        from schemas.node_types import NODE_TYPE_REGISTRY

        spec = NODE_TYPE_REGISTRY["workflow"]
        assert spec.executable is True


# ── NodeStatus enum tests ─────────────────────────────────────────────────────


class TestNodeStatusWaiting:
    def test_waiting_status_exists(self):
        from schemas.node_io import NodeStatus

        assert NodeStatus.WAITING == "waiting"
        assert "waiting" in [s.value for s in NodeStatus]
