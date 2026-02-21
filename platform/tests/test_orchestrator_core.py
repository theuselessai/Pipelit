"""Tests for orchestrator core functions: start_execution, execute_node_job, _advance, _finalize."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


def _mock_redis():
    """Return a mock Redis client with common methods."""
    r = MagicMock()
    r.get.return_value = None
    r.set.return_value = True
    r.delete.return_value = True
    r.incr.return_value = 1
    r.decr.return_value = 0
    r.expire.return_value = True
    r.sadd.return_value = 1
    r.smembers.return_value = set()
    r.keys.return_value = []
    return r


# ── start_execution ───────────────────────────────────────────────────────────

class TestStartExecution:
    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator._save_topology")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.build_topology")
    @patch("services.orchestrator._start_episode")
    def test_basic(self, mock_episode, mock_build_topo, mock_pub, mock_save_topo, mock_save_state, mock_redis_fn, mock_queue_fn):
        from services.orchestrator import start_execution

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        mock_topo = SimpleNamespace(
            entry_node_ids=["trigger_1"],
            workflow_slug="test-wf",
            nodes={},
            edges_by_source={},
            incoming_count={},
            loop_bodies={},
            loop_return_nodes={},
            loop_body_all_nodes={},
        )
        mock_build_topo.return_value = mock_topo
        mock_episode.return_value = None

        # Set up DB objects
        mock_db = MagicMock()
        exec_id = "exec-test-123"
        mock_execution = MagicMock()
        mock_execution.execution_id = exec_id
        mock_execution.workflow_id = 1
        mock_execution.trigger_node_id = None
        mock_execution.trigger_payload = {"text": "hello"}
        mock_execution.user_profile_id = 1
        mock_execution.status = "pending"
        mock_execution.parent_execution_id = None

        mock_workflow = MagicMock()
        mock_workflow.id = 1
        mock_workflow.slug = "test-wf"

        mock_db.query.return_value.filter.return_value.first.side_effect = [mock_execution, mock_workflow]

        start_execution(exec_id, db=mock_db)

        assert mock_execution.status == "running"
        mock_save_topo.assert_called_once()
        mock_save_state.assert_called_once()
        mock_q.enqueue.assert_called_once()  # one entry node

    @patch("services.orchestrator._publish_event")
    def test_execution_not_found(self, mock_pub):
        from services.orchestrator import start_execution

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Should not raise
        start_execution("nonexistent", db=mock_db)

    @patch("services.orchestrator._publish_event")
    def test_workflow_not_found(self, mock_pub):
        from services.orchestrator import start_execution

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.workflow_id = 1
        mock_db.query.return_value.filter.return_value.first.side_effect = [mock_execution, None]

        start_execution("exec-1", db=mock_db)


# ── execute_node_job ──────────────────────────────────────────────────────────

class TestExecuteNodeJob:
    @patch("services.orchestrator._advance")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    @patch("services.orchestrator.get_component_factory", create=True)
    def test_successful_execution(self, mock_factory_fn, mock_load_topo, mock_load_state, mock_save_state, mock_redis_fn, mock_pub, mock_advance):
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "workflow_slug": "wf",
            "nodes": {
                "agent_1": {
                    "node_id": "agent_1",
                    "component_type": "agent",
                    "db_id": 10,
                    "component_config_id": 20,
                    "interrupt_before": False,
                    "interrupt_after": False,
                }
            },
            "edges_by_source": {},
            "incoming_count": {},
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }
        mock_load_topo.return_value = topo_data
        mock_load_state.return_value = {"messages": [], "node_outputs": {}, "trigger": {}}

        # Mock the DB node
        mock_config = MagicMock()
        mock_config.system_prompt = ""
        mock_config.extra_config = {}
        mock_db_node = MagicMock()
        mock_db_node.component_config = mock_config

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-1"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution
        mock_db.get.return_value = mock_db_node

        # Mock component factory
        mock_fn = MagicMock(return_value={"output": "done"})
        with patch("components.get_component_factory", return_value=lambda node: mock_fn):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-1", "agent_1")

        # Should save state and advance
        mock_save_state.assert_called()
        mock_advance.assert_called_once()

    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._load_topology")
    def test_execution_not_runnable(self, mock_load_topo, mock_pub):
        from services.orchestrator import execute_node_job

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "completed"  # not running
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("database.SessionLocal", return_value=mock_db):
            execute_node_job("exec-1", "agent_1")

        # Should return early
        mock_load_topo.assert_not_called()


# ── _advance ──────────────────────────────────────────────────────────────────

class TestAdvance:
    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_no_edges_finalizes(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 0  # no inflight remaining
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "edges_by_source": {},
            "nodes": {},
            "incoming_count": {},
            "workflow_slug": "wf",
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

        _advance("exec-1", "agent_1", {}, topo_data, MagicMock())
        mock_finalize.assert_called_once()

    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_direct_edge_enqueues(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 1  # still inflight
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        topo_data = {
            "edges_by_source": {
                "n1": [
                    {"edge_type": "direct", "target_node_id": "n2", "edge_label": "", "condition_mapping": None, "condition_value": "", "priority": 0},
                ]
            },
            "nodes": {"n2": {"component_type": "agent", "node_id": "n2"}},
            "incoming_count": {},
            "workflow_slug": "wf",
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

        _advance("exec-1", "n1", {}, topo_data, MagicMock())
        mock_q.enqueue.assert_called_once()

    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_conditional_edge_matches(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 1
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        topo_data = {
            "edges_by_source": {
                "switch_1": [
                    {"edge_type": "conditional", "target_node_id": "handler_a", "edge_label": "", "condition_value": "route_a", "condition_mapping": None, "priority": 0},
                    {"edge_type": "conditional", "target_node_id": "handler_b", "edge_label": "", "condition_value": "route_b", "condition_mapping": None, "priority": 0},
                ]
            },
            "nodes": {
                "handler_a": {"component_type": "agent", "node_id": "handler_a"},
                "handler_b": {"component_type": "agent", "node_id": "handler_b"},
            },
            "incoming_count": {},
            "workflow_slug": "wf",
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

        _advance("exec-1", "switch_1", {"route": "route_b"}, topo_data, MagicMock())
        # Should enqueue handler_b
        mock_q.enqueue.assert_called_once()

    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_conditional_legacy_mapping(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 1
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        topo_data = {
            "edges_by_source": {
                "switch_1": [
                    {"edge_type": "conditional", "target_node_id": "handler_a", "edge_label": "", "condition_value": "", "condition_mapping": {"val_x": "handler_x"}, "priority": 0},
                ]
            },
            "nodes": {
                "handler_x": {"component_type": "agent", "node_id": "handler_x"},
            },
            "incoming_count": {},
            "workflow_slug": "wf",
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

        _advance("exec-1", "switch_1", {"route": "val_x"}, topo_data, MagicMock())
        mock_q.enqueue.assert_called_once()

    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_fan_out(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 2
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        topo_data = {
            "edges_by_source": {
                "n1": [
                    {"edge_type": "direct", "target_node_id": "n2", "edge_label": "", "condition_mapping": None, "condition_value": "", "priority": 0},
                    {"edge_type": "direct", "target_node_id": "n3", "edge_label": "", "condition_mapping": None, "condition_value": "", "priority": 0},
                ]
            },
            "nodes": {
                "n2": {"component_type": "agent", "node_id": "n2"},
                "n3": {"component_type": "agent", "node_id": "n3"},
            },
            "incoming_count": {},
            "workflow_slug": "wf",
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

        _advance("exec-1", "n1", {}, topo_data, MagicMock())
        assert mock_q.enqueue.call_count == 2

    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_merge_fan_in(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.incr.return_value = 1  # first parent done, 2 expected
        mock_r.decr.return_value = 1
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        topo_data = {
            "edges_by_source": {
                "n1": [
                    {"edge_type": "direct", "target_node_id": "merge_1", "edge_label": "", "condition_mapping": None, "condition_value": "", "priority": 0},
                ]
            },
            "nodes": {
                "merge_1": {"component_type": "merge", "node_id": "merge_1"},
            },
            "incoming_count": {"merge_1": 2},
            "workflow_slug": "wf",
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

        _advance("exec-1", "n1", {}, topo_data, MagicMock())
        # Merge not ready yet (1/2 parents done)
        mock_q.enqueue.assert_not_called()


# ── _finalize ─────────────────────────────────────────────────────────────────

class TestFinalize:
    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._get_workflow_slug", return_value="wf")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.load_state")
    def test_basic(self, mock_load_state, mock_pub, mock_slug, mock_episode, mock_cleanup):
        from services.orchestrator import _finalize

        mock_load_state.return_value = {"output": "final result", "messages": []}

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-1"
        mock_execution.status = "running"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("services.delivery.output_delivery") as mock_delivery:
            _finalize("exec-1", mock_db)

        assert mock_execution.status == "completed"
        mock_db.commit.assert_called()
        mock_delivery.deliver.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch("services.orchestrator.load_state")
    def test_already_completed(self, mock_load_state):
        from services.orchestrator import _finalize

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "completed"  # already done
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        _finalize("exec-1", mock_db)
        # Should not re-complete
        mock_load_state.assert_not_called()


# ── resume_node_job ───────────────────────────────────────────────────────────

class TestResumeNodeJob:
    @patch("services.orchestrator._queue")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    def test_resume(self, mock_load, mock_save, mock_queue_fn):
        from services.orchestrator import resume_node_job

        mock_load.return_value = {"messages": []}
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-1"
        mock_execution.status = "interrupted"

        mock_pending = MagicMock()
        mock_pending.node_id = "human_1"

        mock_db.query.return_value.filter.return_value.first.side_effect = [mock_execution, mock_pending]

        with patch("database.SessionLocal", return_value=mock_db):
            resume_node_job("exec-1", "yes")

        assert mock_execution.status == "running"
        mock_save.assert_called_once()
        saved_state = mock_save.call_args[0][1]
        assert saved_state["_resume_input"] == "yes"
        mock_q.enqueue.assert_called_once()

    def test_resume_not_interrupted(self):
        from services.orchestrator import resume_node_job

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "completed"  # not interrupted
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("database.SessionLocal", return_value=mock_db):
            resume_node_job("exec-1", "yes")

    def test_resume_no_pending_task(self):
        from services.orchestrator import resume_node_job

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-1"
        mock_execution.status = "interrupted"

        mock_db.query.return_value.filter.return_value.first.side_effect = [mock_execution, None]

        with patch("database.SessionLocal", return_value=mock_db):
            resume_node_job("exec-1", "yes")

        assert mock_execution.status == "running"


# ── _maybe_finalize ───────────────────────────────────────────────────────────

class TestMaybeFinalize:
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._redis")
    def test_all_done(self, mock_redis_fn, mock_finalize):
        from services.orchestrator import _maybe_finalize

        mock_r = _mock_redis()
        mock_r.smembers.return_value = {"n1", "n2"}
        mock_redis_fn.return_value = mock_r

        topo_data = {"nodes": {"n1": {}, "n2": {}}}
        _maybe_finalize("exec-1", topo_data, MagicMock())
        mock_finalize.assert_called_once()

    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._redis")
    def test_not_all_done(self, mock_redis_fn, mock_finalize):
        from services.orchestrator import _maybe_finalize

        mock_r = _mock_redis()
        mock_r.smembers.return_value = {"n1"}  # only 1 of 2
        mock_redis_fn.return_value = mock_r

        topo_data = {"nodes": {"n1": {}, "n2": {}}}
        _maybe_finalize("exec-1", topo_data, MagicMock())
        mock_finalize.assert_not_called()
