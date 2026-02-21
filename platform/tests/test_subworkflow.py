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
    @patch("services.orchestrator._redis")
    @patch("database.SessionLocal")
    def test_injects_child_output_and_reenqueues(self, mock_session_cls, mock_redis, mock_load, mock_save, mock_queue):
        import json
        from services.orchestrator import _resume_from_child

        mock_load.return_value = {
            "node_outputs": {},
            "execution_id": "parent-exec-1",
        }
        mock_q = MagicMock()
        mock_queue.return_value = mock_q

        # Mock Redis to return a legacy (non-parallel) wait key
        mock_r = MagicMock()
        mock_r.get.return_value = json.dumps({
            "deadline": 9999999999,
            "child_execution_id": "child-1",
        })
        mock_redis.return_value = mock_r

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


# ── _create_child_execution tests (implicit mode) ────────────────────────────


class TestCreateChildExecutionImplicit:
    """Test _create_child_execution with trigger_mode='implicit'."""

    @patch("database.SessionLocal")
    def test_lookup_by_slug(self, mock_session_cls):
        """Implicit mode looks up workflow by slug and creates child execution."""
        from components.subworkflow import _create_child_execution

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # Mock workflow found by slug
        mock_workflow = MagicMock()
        mock_workflow.id = 42
        mock_workflow.slug = "child-wf"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_workflow

        def refresh_side_effect(obj):
            obj.execution_id = "child-exec-abc"
        mock_db.refresh.side_effect = refresh_side_effect

        with patch("redis.from_url"), \
             patch("rq.Queue") as mock_queue_cls:
            mock_q = MagicMock()
            mock_queue_cls.return_value = mock_q

            result = _create_child_execution(
                state={
                    "execution_id": "parent-exec-1",
                    "trigger": {"text": "hello"},
                    "node_outputs": {},
                    "user_context": {"user_profile_id": 5},
                },
                target_slug="child-wf",
                subworkflow_id_fk=None,
                trigger_mode="implicit",
                input_mapping={},
                parent_node_id="subworkflow_1",
            )

        assert result == "child-exec-abc"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_q.enqueue.assert_called_once()

    @patch("database.SessionLocal")
    def test_fallback_to_subworkflow_id(self, mock_session_cls):
        """When slug lookup fails, fall back to subworkflow_id FK."""
        from components.subworkflow import _create_child_execution

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # First query (by slug) returns None, second (by id) returns workflow
        mock_workflow = MagicMock()
        mock_workflow.id = 99
        mock_workflow.slug = "fallback-wf"
        mock_db.query.return_value.filter.return_value.first.side_effect = [None, mock_workflow]

        def refresh_side_effect(obj):
            obj.execution_id = "child-fallback"
        mock_db.refresh.side_effect = refresh_side_effect

        with patch("redis.from_url"), \
             patch("rq.Queue") as mock_queue_cls:
            mock_queue_cls.return_value = MagicMock()

            result = _create_child_execution(
                state={
                    "execution_id": "parent-1",
                    "trigger": {},
                    "node_outputs": {},
                    "user_context": {"user_profile_id": 1},
                },
                target_slug="nonexistent",
                subworkflow_id_fk=99,
                trigger_mode="implicit",
                input_mapping={},
                parent_node_id="sw_1",
            )

        assert result == "child-fallback"

    @patch("database.SessionLocal")
    def test_workflow_not_found_raises(self, mock_session_cls):
        """Raises ValueError when neither slug nor subworkflow_id resolves."""
        from components.subworkflow import _create_child_execution

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="Target workflow not found"):
            _create_child_execution(
                state={"execution_id": "p1", "trigger": {}, "node_outputs": {}, "user_context": {"user_profile_id": 1}},
                target_slug="missing",
                subworkflow_id_fk=None,
                trigger_mode="implicit",
                input_mapping={},
                parent_node_id="sw_1",
            )

    @patch("database.SessionLocal")
    def test_no_user_profile_raises(self, mock_session_cls):
        """Raises ValueError when user_profile_id cannot be determined."""
        from components.subworkflow import _create_child_execution

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        mock_workflow = MagicMock()
        mock_workflow.id = 1
        mock_db.query.return_value.filter.return_value.first.return_value = mock_workflow

        with pytest.raises(ValueError, match="Cannot determine user_profile_id"):
            _create_child_execution(
                state={"execution_id": "", "trigger": {}, "node_outputs": {}, "user_context": {}},
                target_slug="wf",
                subworkflow_id_fk=None,
                trigger_mode="implicit",
                input_mapping={},
                parent_node_id="sw_1",
            )

    @patch("database.SessionLocal")
    def test_user_profile_fallback_from_parent_execution(self, mock_session_cls):
        """Falls back to looking up user_profile_id from parent execution."""
        from components.subworkflow import _create_child_execution

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        mock_workflow = MagicMock()
        mock_workflow.id = 1
        mock_workflow.slug = "wf"

        mock_parent_exec = MagicMock()
        mock_parent_exec.user_profile_id = 7

        # First query: workflow lookup, second: parent execution lookup
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_workflow, mock_parent_exec,
        ]

        def refresh_side_effect(obj):
            obj.execution_id = "child-from-parent"
        mock_db.refresh.side_effect = refresh_side_effect

        with patch("redis.from_url"), \
             patch("rq.Queue") as mock_queue_cls:
            mock_queue_cls.return_value = MagicMock()

            result = _create_child_execution(
                state={
                    "execution_id": "parent-exec-1",
                    "trigger": {},
                    "node_outputs": {},
                    "user_context": {},  # no user_profile_id
                },
                target_slug="wf",
                subworkflow_id_fk=None,
                trigger_mode="implicit",
                input_mapping={},
                parent_node_id="sw_1",
            )

        assert result == "child-from-parent"

    @patch("components.subworkflow._create_via_dispatch")
    @patch("database.SessionLocal")
    def test_explicit_mode_delegates_to_dispatch(self, mock_session_cls, mock_dispatch):
        """When trigger_mode='explicit', delegates to _create_via_dispatch."""
        from components.subworkflow import _create_child_execution

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_dispatch.return_value = "dispatch-exec-1"

        result = _create_child_execution(
            state={"execution_id": "p1", "user_context": {"user_profile_id": 1}},
            target_slug="wf",
            subworkflow_id_fk=None,
            trigger_mode="explicit",
            input_mapping={},
            parent_node_id="sw_1",
        )

        assert result == "dispatch-exec-1"
        mock_dispatch.assert_called_once()


# ── _create_via_dispatch tests (explicit mode) ───────────────────────────────


class TestCreateViaDispatch:
    """Test _create_via_dispatch for explicit trigger mode."""

    def test_successful_dispatch(self):
        from components.subworkflow import _create_via_dispatch

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "dispatched-123"
        mock_user = MagicMock()

        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        with patch("handlers.dispatch_event", return_value=mock_execution):
            result = _create_via_dispatch(
                state={
                    "execution_id": "parent-1",
                    "trigger": {"text": "hi"},
                    "node_outputs": {},
                    "user_context": {"user_profile_id": 5},
                },
                target_slug="target-wf",
                input_mapping={},
                parent_node_id="sw_1",
                db=mock_db,
            )

        assert result == "dispatched-123"
        assert mock_execution.parent_execution_id == "parent-1"
        assert mock_execution.parent_node_id == "sw_1"
        mock_db.commit.assert_called_once()

    def test_dispatch_no_match_raises(self):
        from components.subworkflow import _create_via_dispatch

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        with patch("handlers.dispatch_event", return_value=None):
            with pytest.raises(ValueError, match="No workflow matched"):
                _create_via_dispatch(
                    state={"execution_id": "p1", "trigger": {}, "node_outputs": {}, "user_context": {"user_profile_id": 1}},
                    target_slug="no-match",
                    input_mapping={},
                    parent_node_id="sw_1",
                    db=mock_db,
                )

    def test_dispatch_user_not_found_raises(self):
        from components.subworkflow import _create_via_dispatch

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="User profile.*not found"):
            _create_via_dispatch(
                state={"execution_id": "p1", "trigger": {}, "node_outputs": {}, "user_context": {"user_profile_id": 999}},
                target_slug="wf",
                input_mapping={},
                parent_node_id="sw_1",
                db=mock_db,
            )
