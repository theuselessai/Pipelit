"""Tests for orchestrator loop logic, error paths, and edge cases."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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


# ── _advance_loop_body ───────────────────────────────────────────────────────

class TestAdvanceLoopBody:
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._redis")
    def test_enqueues_body_targets(self, mock_redis_fn, mock_queue_fn, mock_pub):
        from services.orchestrator import _advance_loop_body

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        topo_data = {
            "loop_bodies": {"loop_1": ["body_a", "body_b"]},
            "workflow_slug": "wf",
        }
        _advance_loop_body("exec-1", "loop_1", topo_data, "wf", iter_index=0)

        assert mock_q.enqueue.call_count == 2
        assert mock_r.incr.call_count == 2  # inflight for each body target

    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._redis")
    def test_enqueues_with_delay(self, mock_redis_fn, mock_queue_fn, mock_pub):
        from services.orchestrator import _advance_loop_body

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        topo_data = {
            "loop_bodies": {"loop_1": ["body_a"]},
            "workflow_slug": "wf",
        }
        _advance_loop_body("exec-1", "loop_1", topo_data, "wf", iter_index=0, delay_seconds=5.0)

        mock_q.enqueue_in.assert_called_once()
        mock_q.enqueue.assert_not_called()


# ── _check_loop_body_done ────────────────────────────────────────────────────

class TestCheckLoopBodyDone:
    @patch("services.orchestrator._loop_next_iteration")
    @patch("services.orchestrator._redis")
    def test_returns_true_for_body_node(self, mock_redis_fn, mock_loop_next):
        from services.orchestrator import _check_loop_body_done

        mock_r = _mock_redis()
        mock_r.get.return_value = json.dumps({"items": ["a", "b"], "index": 0, "results": []})
        mock_r.incr.return_value = 1  # completion node done
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "loop_bodies": {"loop_1": ["body_a"]},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {"loop_1": ["body_a"]},
        }
        result = _check_loop_body_done("exec-1", "body_a", topo_data, MagicMock())
        assert result is True
        mock_loop_next.assert_called_once()

    @patch("services.orchestrator._redis")
    def test_returns_false_for_non_body_node(self, mock_redis_fn):
        from services.orchestrator import _check_loop_body_done

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "loop_bodies": {"loop_1": ["body_a"]},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {"loop_1": ["body_a"]},
        }
        result = _check_loop_body_done("exec-1", "other_node", topo_data, MagicMock())
        assert result is False

    @patch("services.orchestrator._loop_next_iteration")
    @patch("services.orchestrator._redis")
    def test_waits_for_all_completion_nodes(self, mock_redis_fn, mock_loop_next):
        from services.orchestrator import _check_loop_body_done

        mock_r = _mock_redis()
        mock_r.get.return_value = json.dumps({"items": ["a"], "index": 0})
        mock_r.incr.return_value = 1  # 1 of 2 done
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "loop_bodies": {"loop_1": ["body_a", "body_b"]},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {"loop_1": ["body_a", "body_b"]},
        }
        result = _check_loop_body_done("exec-1", "body_a", topo_data, MagicMock())
        assert result is True
        mock_loop_next.assert_not_called()  # not all completion nodes done

    @patch("services.orchestrator._loop_next_iteration")
    @patch("services.orchestrator._redis")
    def test_with_return_nodes(self, mock_redis_fn, mock_loop_next):
        from services.orchestrator import _check_loop_body_done

        mock_r = _mock_redis()
        mock_r.get.return_value = json.dumps({"items": ["a"], "index": 0})
        mock_r.incr.return_value = 1  # 1 of 1 return node done
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "loop_bodies": {"loop_1": ["body_a"]},
            "loop_return_nodes": {"loop_1": ["return_a"]},
            "loop_body_all_nodes": {"loop_1": ["body_a", "return_a"]},
        }
        result = _check_loop_body_done("exec-1", "return_a", topo_data, MagicMock())
        assert result is True
        mock_loop_next.assert_called_once()


# ── _loop_next_iteration ─────────────────────────────────────────────────────

class TestLoopNextIteration:
    @patch("services.orchestrator._advance_loop_body")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._redis")
    def test_advances_to_next_item(self, mock_redis_fn, mock_load_state, mock_save_state, mock_advance_loop):
        from services.orchestrator import _loop_next_iteration

        mock_r = _mock_redis()
        mock_r.get.return_value = json.dumps({
            "items": ["a", "b", "c"], "index": 0, "results": [],
            "body_targets": ["body_a"],
        })
        mock_redis_fn.return_value = mock_r
        mock_load_state.return_value = {"node_outputs": {"body_a": {"out": 1}}, "_loop_errors": {}}

        topo_data = {
            "loop_return_nodes": {},
            "workflow_slug": "wf",
        }
        _loop_next_iteration("exec-1", "loop_1", topo_data, MagicMock())

        # Should advance to next iteration (index 1)
        mock_advance_loop.assert_called_once()
        # Should save state with loop context
        saved_state = mock_save_state.call_args[0][1]
        assert saved_state["loop"]["index"] == 1
        assert saved_state["loop"]["item"] == "b"

    @patch("services.orchestrator._advance")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._redis")
    def test_completes_loop(self, mock_redis_fn, mock_load_state, mock_save_state, mock_advance):
        from services.orchestrator import _loop_next_iteration

        mock_r = _mock_redis()
        # Last item (index 1, 2 items total)
        mock_r.get.return_value = json.dumps({
            "items": ["a", "b"], "index": 1, "results": [{"body_a": {"out": 1}}],
            "body_targets": ["body_a"],
        })
        mock_redis_fn.return_value = mock_r
        mock_load_state.return_value = {"node_outputs": {"body_a": {"out": 2}}}

        topo_data = {
            "loop_return_nodes": {},
            "workflow_slug": "wf",
        }
        _loop_next_iteration("exec-1", "loop_1", topo_data, MagicMock())

        # Should advance via normal edges (loop complete)
        mock_advance.assert_called_once()
        # loop_1 should have results in node_outputs
        saved_state = mock_save_state.call_args[0][1]
        assert "results" in saved_state["node_outputs"]["loop_1"]
        assert "loop" not in saved_state  # loop context cleared

    @patch("services.orchestrator._advance_loop_body")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._redis")
    def test_handles_loop_errors(self, mock_redis_fn, mock_load_state, mock_save_state, mock_advance_loop):
        from services.orchestrator import _loop_next_iteration

        mock_r = _mock_redis()
        mock_r.get.return_value = json.dumps({
            "items": ["a", "b"], "index": 0, "results": [],
            "body_targets": ["body_a"],
        })
        mock_redis_fn.return_value = mock_r
        mock_load_state.return_value = {
            "node_outputs": {},
            "_loop_errors": {
                "loop_1": {"body_a": {"error": "failed", "error_code": "RuntimeError"}},
            },
        }

        topo_data = {
            "loop_return_nodes": {},
            "workflow_slug": "wf",
        }
        _loop_next_iteration("exec-1", "loop_1", topo_data, MagicMock())

        # Errors should be captured in results
        mock_advance_loop.assert_called_once()
        saved_state = mock_save_state.call_args[0][1]
        # Loop errors for this iteration should be cleared
        assert "loop_1" not in saved_state.get("_loop_errors", {})

    @patch("services.orchestrator._advance")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._redis")
    def test_complete_loop_with_delay(self, mock_redis_fn, mock_load_state, mock_save_state, mock_advance):
        from services.orchestrator import _loop_next_iteration

        mock_r = _mock_redis()
        mock_r.get.return_value = json.dumps({
            "items": ["a"], "index": 0, "results": [],
            "body_targets": ["body_a"],
        })
        mock_redis_fn.return_value = mock_r
        mock_load_state.return_value = {"node_outputs": {"body_a": {"out": 1}}}

        topo_data = {"loop_return_nodes": {}, "workflow_slug": "wf"}
        _loop_next_iteration("exec-1", "loop_1", topo_data, MagicMock(), delay_seconds=2.0)

        mock_advance.assert_called_once()
        # Verify delay_seconds is passed
        _, kwargs = mock_advance.call_args
        assert kwargs.get("delay_seconds") == 2.0


# ── execute_node_job error paths ─────────────────────────────────────────────

class TestExecuteNodeJobErrors:
    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_node_failure_permanent(self, mock_load_topo, mock_load_state, mock_save_state, mock_redis_fn, mock_pub, mock_episode, mock_cleanup):
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "workflow_slug": "wf",
            "nodes": {
                "agent_1": {
                    "node_id": "agent_1", "component_type": "agent",
                    "db_id": 10, "component_config_id": 20,
                    "interrupt_before": False, "interrupt_after": False,
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

        # Component raises an exception at max retries
        def _raise(*args, **kwargs):
            raise RuntimeError("test error")

        with patch("components.get_component_factory", return_value=lambda node: _raise):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-1", "agent_1", retry_count=3)

        # Should mark execution as failed
        assert mock_execution.status == "failed"
        mock_pub.assert_called()

    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_node_failure_retries(self, mock_load_topo, mock_load_state, mock_save_state, mock_redis_fn, mock_pub, mock_queue_fn):
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        topo_data = {
            "workflow_slug": "wf",
            "nodes": {
                "agent_1": {
                    "node_id": "agent_1", "component_type": "agent",
                    "db_id": 10, "component_config_id": 20,
                    "interrupt_before": False, "interrupt_after": False,
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

        def _raise(*args, **kwargs):
            raise RuntimeError("retry me")

        with patch("components.get_component_factory", return_value=lambda node: _raise):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-1", "agent_1", retry_count=0)

        # Should enqueue retry
        mock_q.enqueue_in.assert_called_once()

    @patch("services.orchestrator._advance")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_node_with_route_and_messages(self, mock_load_topo, mock_load_state, mock_save_state, mock_redis_fn, mock_pub, mock_advance):
        """Test a node that returns _route, _messages, and _state_patch."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "workflow_slug": "wf",
            "nodes": {
                "switch_1": {
                    "node_id": "switch_1", "component_type": "switch",
                    "db_id": 10, "component_config_id": 20,
                    "interrupt_before": False, "interrupt_after": False,
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

        # Component returns route, messages, and state_patch
        def _component(state):
            return {
                "output": "value",
                "_route": "path_a",
                "_messages": [{"role": "ai", "content": "hi"}],
                "_state_patch": {"custom_key": "custom_val"},
            }

        with patch("components.get_component_factory", return_value=lambda node: _component):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-1", "switch_1")

        # Verify state was saved with route, messages, state_patch
        saved_state = mock_save_state.call_args[0][1]
        assert saved_state["route"] == "path_a"
        assert len(saved_state["messages"]) == 1
        assert saved_state["custom_key"] == "custom_val"
        assert "switch_1" in saved_state["node_outputs"]

    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._load_topology")
    def test_node_not_in_topology(self, mock_load_topo, mock_pub):
        from services.orchestrator import execute_node_job

        topo_data = {
            "workflow_slug": "wf",
            "nodes": {},
            "edges_by_source": {},
        }
        mock_load_topo.return_value = topo_data

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-1"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("database.SessionLocal", return_value=mock_db):
            execute_node_job("exec-1", "unknown_node")

    @patch("services.orchestrator._handle_interrupt")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._load_topology")
    def test_interrupt_before(self, mock_load_topo, mock_pub, mock_interrupt):
        from services.orchestrator import execute_node_job

        topo_data = {
            "workflow_slug": "wf",
            "nodes": {
                "human_1": {
                    "node_id": "human_1", "component_type": "human_confirmation",
                    "db_id": 10, "component_config_id": 20,
                    "interrupt_before": True, "interrupt_after": False,
                }
            },
            "edges_by_source": {},
        }
        mock_load_topo.return_value = topo_data

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-1"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("database.SessionLocal", return_value=mock_db):
            execute_node_job("exec-1", "human_1")

        mock_interrupt.assert_called_once()


# ── _advance edge cases ──────────────────────────────────────────────────────

class TestAdvanceEdgeCases:
    @patch("services.orchestrator._check_loop_body_done", return_value=True)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_no_edges_but_in_loop(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        """When a node has no edges but is inside a loop body, it returns early."""
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 1
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "edges_by_source": {},
            "nodes": {},
            "incoming_count": {},
            "workflow_slug": "wf",
            "loop_bodies": {"loop_1": ["body_a"]},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {"loop_1": ["body_a"]},
        }

        _advance("exec-1", "body_a", {}, topo_data, MagicMock())
        # Should check loop body, and since it returns True, decrement and return
        mock_finalize.assert_not_called()

    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_direct_edge_to_end(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        """Direct edge to __end__ should not enqueue anything."""
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 0
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "edges_by_source": {
                "n1": [
                    {"edge_type": "direct", "target_node_id": "__end__", "edge_label": "", "condition_mapping": None, "condition_value": "", "priority": 0},
                ]
            },
            "nodes": {},
            "incoming_count": {},
            "workflow_slug": "wf",
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

        _advance("exec-1", "n1", {}, topo_data, MagicMock())
        mock_queue_fn.return_value.enqueue.assert_not_called()

    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_direct_edge_with_delay(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 1
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

        _advance("exec-1", "n1", {}, topo_data, MagicMock(), delay_seconds=3.0)
        mock_q.enqueue_in.assert_called_once()

    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_conditional_edge_to_end(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 0
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "edges_by_source": {
                "switch_1": [
                    {"edge_type": "conditional", "target_node_id": "__end__", "edge_label": "", "condition_value": "done", "condition_mapping": None, "priority": 0},
                ]
            },
            "nodes": {},
            "incoming_count": {},
            "workflow_slug": "wf",
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

        _advance("exec-1", "switch_1", {"route": "done"}, topo_data, MagicMock())
        # __end__ should not be enqueued
        mock_queue_fn.return_value.enqueue.assert_not_called()

    @patch("services.orchestrator._check_loop_body_done", return_value=False)
    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._queue")
    def test_skip_loop_edges(self, mock_queue_fn, mock_redis_fn, mock_pub, mock_finalize, mock_loop):
        """Loop body/return edges should be filtered out from normal advancement."""
        from services.orchestrator import _advance

        mock_r = _mock_redis()
        mock_r.decr.return_value = 0
        mock_redis_fn.return_value = mock_r

        topo_data = {
            "edges_by_source": {
                "n1": [
                    {"edge_type": "direct", "target_node_id": "body_a", "edge_label": "loop_body", "condition_mapping": None, "condition_value": "", "priority": 0},
                    {"edge_type": "direct", "target_node_id": "n1", "edge_label": "loop_return", "condition_mapping": None, "condition_value": "", "priority": 0},
                ]
            },
            "nodes": {},
            "incoming_count": {},
            "workflow_slug": "wf",
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

        _advance("exec-1", "n1", {}, topo_data, MagicMock())
        # Loop edges should be filtered out — no enqueue
        mock_queue_fn.return_value.enqueue.assert_not_called()


# ── start_execution error paths ──────────────────────────────────────────────

class TestStartExecutionErrors:
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.build_topology", side_effect=RuntimeError("build failed"))
    @patch("services.orchestrator._start_episode")
    def test_build_topology_failure(self, mock_episode, mock_build, mock_pub):
        from services.orchestrator import start_execution

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-1"
        mock_execution.workflow_id = 1
        mock_execution.trigger_node_id = None
        mock_execution.trigger_payload = {}
        mock_execution.user_profile_id = 1
        mock_execution.status = "pending"

        mock_workflow = MagicMock()
        mock_workflow.id = 1
        mock_workflow.slug = "wf"

        mock_db.query.return_value.filter.return_value.first.side_effect = [mock_execution, mock_workflow]

        start_execution("exec-1", db=mock_db)
        assert mock_execution.status == "failed"

    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator._save_topology")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.build_topology")
    @patch("services.orchestrator._start_episode")
    def test_with_trigger_node(self, mock_episode, mock_build, mock_pub, mock_save_topo, mock_save_state, mock_redis_fn, mock_queue_fn):
        """Test start_execution with a trigger_node_id set."""
        from services.orchestrator import start_execution
        from types import SimpleNamespace

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q

        mock_topo = SimpleNamespace(
            entry_node_ids=["agent_1"],
            workflow_slug="wf",
            nodes={},
            edges_by_source={},
            incoming_count={},
            loop_bodies={},
            loop_return_nodes={},
            loop_body_all_nodes={},
        )
        mock_build.return_value = mock_topo

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-1"
        mock_execution.workflow_id = 1
        mock_execution.trigger_node_id = 42
        mock_execution.trigger_payload = {"text": "hi"}
        mock_execution.user_profile_id = 1
        mock_execution.status = "pending"
        mock_execution.parent_execution_id = None

        mock_workflow = MagicMock()
        mock_workflow.id = 1
        mock_workflow.slug = "wf"

        mock_trigger_node = MagicMock()
        mock_trigger_node.component_type = "trigger_telegram"

        mock_db.query.return_value.filter.return_value.first.side_effect = [mock_execution, mock_workflow]
        mock_db.get.return_value = mock_trigger_node

        start_execution("exec-1", db=mock_db)
        assert mock_execution.status == "running"
