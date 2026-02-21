"""Tests for orchestrator core functions: start_execution, execute_node_job, _advance, _finalize."""

from __future__ import annotations

import json
import time
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


# ── _cache_parent_info / _get_parent_info ─────────────────────────────────────


class TestParentInfoCache:
    @patch("services.orchestrator._redis")
    def test_cache_parent_info_stores_json(self, mock_redis_fn):
        from services.orchestrator import _cache_parent_info, _parent_info_key, STATE_TTL

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r

        _cache_parent_info(
            "child-exec", "parent-exec", "agent_1", "parent-wf",
            "root-exec", "root_agent", "root-wf",
        )

        mock_r.set.assert_called_once()
        call_args = mock_r.set.call_args
        assert call_args[0][0] == _parent_info_key("child-exec")
        stored = json.loads(call_args[0][1])
        assert stored["parent_execution_id"] == "parent-exec"
        assert stored["root_execution_id"] == "root-exec"
        assert stored["root_workflow_slug"] == "root-wf"
        assert call_args[1]["ex"] == STATE_TTL

    @patch("services.orchestrator._redis")
    def test_get_parent_info_returns_parsed_dict(self, mock_redis_fn):
        from services.orchestrator import _get_parent_info

        mock_r = _mock_redis()
        mock_r.get.return_value = json.dumps({
            "parent_execution_id": "p-1",
            "root_execution_id": "r-1",
            "root_workflow_slug": "root-wf",
        })
        mock_redis_fn.return_value = mock_r

        result = _get_parent_info("child-exec")
        assert result["parent_execution_id"] == "p-1"
        assert result["root_execution_id"] == "r-1"

    @patch("services.orchestrator._redis")
    def test_get_parent_info_returns_none_when_missing(self, mock_redis_fn):
        from services.orchestrator import _get_parent_info

        mock_r = _mock_redis()
        mock_r.get.return_value = None
        mock_redis_fn.return_value = mock_r

        assert _get_parent_info("nonexistent") is None


# ── _publish_event child forwarding ──────────────────────────────────────────


class TestPublishEventChildForwarding:
    @patch("services.orchestrator._get_parent_info")
    @patch("services.orchestrator._redis")
    def test_forwards_node_status_to_root_parent(self, mock_redis_fn, mock_get_parent):
        from services.orchestrator import _publish_event

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_get_parent.return_value = {
            "root_execution_id": "root-exec",
            "root_node_id": "root_agent",
            "root_workflow_slug": "root-wf",
        }

        _publish_event("child-exec", "node_status", {"node_id": "n1", "status": "success"}, workflow_slug="child-wf")

        # Verify publish was called for: child exec channel, child workflow channel,
        # root exec channel, and root workflow channel
        publish_calls = mock_r.publish.call_args_list
        channels = [c[0][0] for c in publish_calls]
        assert "execution:child-exec" in channels
        assert "workflow:child-wf" in channels
        assert "execution:root-exec" in channels
        assert "workflow:root-wf" in channels

        # The root exec publish should be child_node_status type
        root_exec_call = [c for c in publish_calls if c[0][0] == "execution:root-exec"][0]
        payload = json.loads(root_exec_call[0][1])
        assert payload["type"] == "child_node_status"
        assert payload["data"]["is_child_event"] is True
        assert payload["data"]["child_execution_id"] == "child-exec"

    @patch("services.orchestrator._get_parent_info")
    @patch("services.orchestrator._redis")
    def test_skips_forwarding_without_parent_info(self, mock_redis_fn, mock_get_parent):
        from services.orchestrator import _publish_event

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_get_parent.return_value = None

        _publish_event("child-exec", "node_status", {"node_id": "n1"}, workflow_slug="wf")

        # Only the normal 2 publishes (exec channel + workflow channel), no forwarding
        assert mock_r.publish.call_count == 2

    @patch("services.orchestrator._get_parent_info")
    @patch("services.orchestrator._redis")
    def test_skips_forwarding_for_non_node_status_events(self, mock_redis_fn, mock_get_parent):
        from services.orchestrator import _publish_event

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_get_parent.return_value = {
            "root_execution_id": "root-exec",
            "root_node_id": "root_agent",
            "root_workflow_slug": "root-wf",
        }

        _publish_event("child-exec", "execution_completed", {"output": "done"}, workflow_slug="wf")

        # _get_parent_info should not be called for non-node_status events
        mock_get_parent.assert_not_called()
        # Only the normal 2 publishes
        assert mock_r.publish.call_count == 2


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

    @patch("services.orchestrator._cache_parent_info")
    @patch("services.orchestrator._get_parent_info")
    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator._save_topology")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.build_topology")
    @patch("services.orchestrator._start_episode")
    def test_caches_parent_info_for_child_execution(
        self, mock_episode, mock_build_topo, mock_pub, mock_save_topo,
        mock_save_state, mock_redis_fn, mock_queue_fn,
        mock_get_parent, mock_cache_parent,
    ):
        from services.orchestrator import start_execution

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_queue_fn.return_value = MagicMock()
        mock_get_parent.return_value = None  # parent is not itself a child

        mock_topo = SimpleNamespace(
            entry_node_ids=["trigger_1"], workflow_slug="child-wf",
            nodes={}, edges_by_source={}, incoming_count={},
            loop_bodies={}, loop_return_nodes={}, loop_body_all_nodes={},
        )
        mock_build_topo.return_value = mock_topo
        mock_episode.return_value = None

        mock_db = MagicMock()
        exec_id = "child-exec-1"
        mock_execution = MagicMock()
        mock_execution.execution_id = exec_id
        mock_execution.workflow_id = 1
        mock_execution.trigger_node_id = None
        mock_execution.trigger_payload = {"text": "hi"}
        mock_execution.user_profile_id = 1
        mock_execution.status = "pending"
        mock_execution.parent_execution_id = "parent-exec-1"
        mock_execution.parent_node_id = "agent_1"

        mock_workflow = MagicMock()
        mock_workflow.id = 1
        mock_workflow.slug = "child-wf"

        # Mock parent execution lookup for root_slug resolution
        mock_parent_exec = MagicMock()
        mock_parent_exec.workflow_id = 2
        mock_parent_wf = MagicMock()
        mock_parent_wf.slug = "parent-wf"

        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_execution, mock_workflow,  # start_execution lookups
            mock_parent_exec, mock_parent_wf,  # parent resolution
        ]

        start_execution(exec_id, db=mock_db)

        # First-level child: root = parent, parent_slug resolved from DB
        mock_cache_parent.assert_called_once_with(
            exec_id, "parent-exec-1", "agent_1", "parent-wf",
            "parent-exec-1", "agent_1", "parent-wf",
        )

    @patch("services.orchestrator._cache_parent_info")
    @patch("services.orchestrator._get_parent_info")
    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator._save_topology")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.build_topology")
    @patch("services.orchestrator._start_episode")
    def test_caches_grandchild_info_from_grandparent(
        self, mock_episode, mock_build_topo, mock_pub, mock_save_topo,
        mock_save_state, mock_redis_fn, mock_queue_fn,
        mock_get_parent, mock_cache_parent,
    ):
        from services.orchestrator import start_execution

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_queue_fn.return_value = MagicMock()

        # Parent is itself a child → grandchild scenario
        mock_get_parent.return_value = {
            "root_execution_id": "grandparent-exec",
            "root_node_id": "gp_agent",
            "root_workflow_slug": "gp-wf",
        }

        mock_topo = SimpleNamespace(
            entry_node_ids=["trigger_1"], workflow_slug="grandchild-wf",
            nodes={}, edges_by_source={}, incoming_count={},
            loop_bodies={}, loop_return_nodes={}, loop_body_all_nodes={},
        )
        mock_build_topo.return_value = mock_topo
        mock_episode.return_value = None

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "grandchild-exec"
        mock_execution.workflow_id = 1
        mock_execution.trigger_node_id = None
        mock_execution.trigger_payload = {"text": "hi"}
        mock_execution.user_profile_id = 1
        mock_execution.status = "pending"
        mock_execution.parent_execution_id = "parent-exec"
        mock_execution.parent_node_id = "agent_1"

        mock_workflow = MagicMock()
        mock_workflow.id = 1
        mock_workflow.slug = "grandchild-wf"

        # Parent execution/workflow lookup for parent_slug resolution
        mock_parent_exec = MagicMock()
        mock_parent_exec.workflow_id = 2
        mock_parent_wf = MagicMock()
        mock_parent_wf.slug = "parent-wf"

        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_execution, mock_workflow,
            mock_parent_exec, mock_parent_wf,  # parent resolution
        ]

        start_execution("grandchild-exec", db=mock_db)

        mock_cache_parent.assert_called_once_with(
            "grandchild-exec", "parent-exec", "agent_1", "parent-wf",
            "grandparent-exec", "gp_agent", "gp-wf",
        )


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

    @patch("services.orchestrator._advance")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_subworkflow_parallel_stores_wait_data(
        self, mock_load_topo, mock_load_state, mock_save_state,
        mock_redis_fn, mock_pub, mock_advance,
    ):
        from services.orchestrator import _child_wait_key, execute_node_job

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

        mock_config = MagicMock()
        mock_config.system_prompt = ""
        mock_config.extra_config = {}
        mock_db_node = MagicMock()
        mock_db_node.component_config = mock_config

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-sw"
        mock_execution.trigger_payload = {}
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution
        mock_db.get.return_value = mock_db_node

        # Component returns parallel subworkflow data
        mock_fn = MagicMock(return_value={
            "_subworkflow": {"child_execution_ids": ["c1", "c2"], "parallel": True, "count": 2},
            "output": "spawning",
        })
        with patch("components.get_component_factory", return_value=lambda node: mock_fn):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-sw", "agent_1")

        # Verify wait data stored in Redis
        wait_key = _child_wait_key("exec-sw", "agent_1")
        set_calls = [c for c in mock_r.set.call_args_list if c[0][0] == wait_key]
        assert len(set_calls) == 1
        wait_data = json.loads(set_calls[0][0][1])
        assert wait_data["parallel"] is True
        assert wait_data["total"] == 2
        assert wait_data["child_ids"] == ["c1", "c2"]

        # _advance should NOT be called
        mock_advance.assert_not_called()

    @patch("services.orchestrator._advance")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_subworkflow_legacy_single_child(
        self, mock_load_topo, mock_load_state, mock_save_state,
        mock_redis_fn, mock_pub, mock_advance,
    ):
        from services.orchestrator import _child_wait_key, execute_node_job

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

        mock_config = MagicMock()
        mock_config.system_prompt = ""
        mock_config.extra_config = {}
        mock_db_node = MagicMock()
        mock_db_node.component_config = mock_config

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-legacy"
        mock_execution.trigger_payload = {}
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution
        mock_db.get.return_value = mock_db_node

        # Legacy single-child format (no child_execution_ids)
        mock_fn = MagicMock(return_value={
            "_subworkflow": {"child_execution_id": "c1"},
            "output": "spawning",
        })
        with patch("components.get_component_factory", return_value=lambda node: mock_fn):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-legacy", "agent_1")

        # Verify wait data uses fallback child_ids=["c1"], count=1
        wait_key = _child_wait_key("exec-legacy", "agent_1")
        set_calls = [c for c in mock_r.set.call_args_list if c[0][0] == wait_key]
        assert len(set_calls) == 1
        wait_data = json.loads(set_calls[0][0][1])
        assert wait_data["child_ids"] == ["c1"]
        assert wait_data["total"] == 1
        mock_advance.assert_not_called()


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

    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._get_workflow_slug", return_value="wf")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._sync_task_costs")
    def test_child_cost_rollup(
        self, mock_sync, mock_load_state, mock_pub, mock_slug,
        mock_episode, mock_cleanup,
    ):
        from services.orchestrator import _finalize

        mock_load_state.return_value = {
            "output": "done",
            "messages": [],
            "node_results": {"n1": {}, "n2": {}},
            "_execution_token_usage": {
                "input_tokens": 50,
                "output_tokens": 50,
                "total_tokens": 100,
                "cost_usd": 0.01,
                "llm_calls": 2,
            },
        }

        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-parent"
        mock_execution.status = "running"
        mock_execution.started_at = datetime(2025, 1, 1, 0, 0, 0)
        # completed_at will be overwritten by _finalize, but we need started_at for duration

        # Mock child executions for BFS cost rollup
        child1 = MagicMock()
        child1.total_tokens = 50
        child1.total_cost_usd = 0.005
        child1.llm_calls = 1
        child1.execution_id = "child-1"

        child2 = MagicMock()
        child2.total_tokens = 30
        child2.total_cost_usd = 0.003
        child2.llm_calls = 1
        child2.execution_id = "child-2"

        # Use side_effect on filter to differentiate query chains
        # _finalize calls: filter(execution_id==...).first() and filter(parent_execution_id==pid).all()
        filter_results = {}

        def mock_filter(*args, **kwargs):
            inner = MagicMock()
            # Intercept filter args to determine call purpose
            # If .first() is called: return execution
            inner.first.return_value = mock_execution
            # If .all() is called: return children for BFS
            if not hasattr(mock_filter, "_all_calls"):
                mock_filter._all_calls = iter([
                    [child1, child2],  # children of parent
                    [],  # children of child1
                    [],  # children of child2
                ])
            inner.all.side_effect = lambda: next(mock_filter._all_calls, [])
            return inner

        mock_db = MagicMock()
        mock_db.query.return_value.filter = mock_filter

        with patch("services.delivery.output_delivery") as mock_delivery:
            _finalize("exec-parent", mock_db)

        # Verify activity_summary in the published event
        pub_calls = mock_pub.call_args_list
        completed_call = [c for c in pub_calls if c[0][1] == "execution_completed"]
        assert len(completed_call) == 1
        event_data = completed_call[0][0][2]
        summary = event_data["activity_summary"]
        assert summary["child_count"] == 2
        # _persist_execution_costs sets execution.total_tokens from state usage
        assert summary["total_tokens"] == 100 + 50 + 30  # parent(100) + child1(50) + child2(30)
        assert summary["total_cost_usd"] == pytest.approx(0.01 + 0.005 + 0.003)
        assert summary["llm_calls"] == 2 + 1 + 1  # parent(2) + child1(1) + child2(1)

    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._get_workflow_slug", return_value="wf")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._sync_task_costs")
    def test_child_cost_rollup_exception_logged(
        self, mock_sync, mock_load_state, mock_pub, mock_slug,
        mock_episode, mock_cleanup,
    ):
        from services.orchestrator import _finalize

        mock_load_state.return_value = {
            "output": "done",
            "messages": [],
            "node_results": {},
            "_execution_token_usage": {},
        }

        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-err"
        mock_execution.status = "running"
        mock_execution.started_at = datetime(2025, 1, 1, 0, 0, 0)
        mock_execution.completed_at = datetime(2025, 1, 1, 0, 0, 5)
        mock_execution.total_tokens = 100
        mock_execution.total_cost_usd = 0.01
        mock_execution.llm_calls = 2

        def mock_filter(*args, **kwargs):
            inner = MagicMock()
            inner.first.return_value = mock_execution
            inner.all.side_effect = RuntimeError("DB error")
            return inner

        mock_db = MagicMock()
        mock_db.query.return_value.filter = mock_filter

        with patch("services.delivery.output_delivery"):
            _finalize("exec-err", mock_db)

        # Execution should still complete despite the exception
        assert mock_execution.status == "completed"
        # Event should still be published
        pub_calls = mock_pub.call_args_list
        completed_call = [c for c in pub_calls if c[0][1] == "execution_completed"]
        assert len(completed_call) == 1


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


# ── _resume_from_child lock edge cases ────────────────────────────────────────


class TestResumeFromChildLock:
    def test_lock_acquisition_failure_returns_early(self):
        """When lock.acquire returns False, no state updates or enqueuing."""
        from services.orchestrator import _resume_from_child

        mock_redis = MagicMock()
        wait_data = json.dumps({
            "parallel": True,
            "total": 2,
            "child_ids": ["c1", "c2"],
            "results": {},
        })
        mock_redis.get.return_value = wait_data

        mock_lock = MagicMock()
        mock_lock.acquire.return_value = False  # Lock acquisition fails
        mock_redis.lock.return_value = mock_lock

        mock_parent = MagicMock()
        mock_parent.status = "running"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_parent

        with patch("services.orchestrator._redis", return_value=mock_redis), \
             patch("services.orchestrator.load_state") as mock_load, \
             patch("services.orchestrator.save_state") as mock_save, \
             patch("services.orchestrator._queue", return_value=MagicMock()) as mock_q, \
             patch("database.SessionLocal", return_value=mock_db):
            _resume_from_child("parent-exec", "agent_1", {"result": "ok"}, child_execution_id="c1")

        # No state updates or enqueuing
        mock_load.assert_not_called()
        mock_save.assert_not_called()
        mock_q.return_value.enqueue.assert_not_called()

    def test_wait_key_consumed_under_lock(self):
        """When wait key is consumed between initial read and locked read, return early."""
        from services.orchestrator import _resume_from_child

        mock_redis = MagicMock()
        wait_data = json.dumps({
            "parallel": True,
            "total": 2,
            "child_ids": ["c1", "c2"],
            "results": {},
        })
        # First get returns data, second (under lock) returns None
        mock_redis.get.side_effect = [wait_data, None]

        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_redis.lock.return_value = mock_lock

        mock_parent = MagicMock()
        mock_parent.status = "running"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_parent

        with patch("services.orchestrator._redis", return_value=mock_redis), \
             patch("services.orchestrator.load_state") as mock_load, \
             patch("services.orchestrator.save_state") as mock_save, \
             patch("services.orchestrator._queue", return_value=MagicMock()) as mock_q, \
             patch("database.SessionLocal", return_value=mock_db):
            _resume_from_child("parent-exec", "agent_1", {"result": "ok"}, child_execution_id="c1")

        # Should have returned early — no state or enqueue
        mock_load.assert_not_called()
        mock_save.assert_not_called()
        mock_q.return_value.enqueue.assert_not_called()
        # Lock should have been released
        mock_lock.release.assert_called_once()
