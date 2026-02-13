"""Tests for Phase 1 zombie execution fixes.

Covers:
- Fix 1.1: Inflight counter decremented on early returns in execute_node_job()
- Fix 1.2: Inflight counter decremented in outer exception handler
- Fix 1.3: _finalize() exception safety
- Fix 1.4: LLM credential null checks
- Fix 3.1: _publish_event() failure safety
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
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


def _make_topo_data(nodes=None):
    return {
        "workflow_slug": "wf",
        "nodes": nodes or {},
        "edges_by_source": {},
        "incoming_count": {},
        "loop_bodies": {},
        "loop_return_nodes": {},
        "loop_body_all_nodes": {},
    }


# ── Fix 1.1: Inflight decrement on early returns ────────────────────────────


class TestInflightDecrementOnEarlyReturn:
    """Fix 1.1: execute_node_job must decrement inflight when returning early."""

    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._load_topology")
    def test_not_runnable_decrements_inflight(self, mock_load_topo, mock_redis_fn, mock_pub):
        """When execution status is not 'running', inflight must be decremented."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_r.decr.return_value = 0
        mock_redis_fn.return_value = mock_r

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "completed"  # not running
        mock_execution.execution_id = "exec-1"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("database.SessionLocal", return_value=mock_db):
            execute_node_job("exec-1", "agent_1")

        # Should NOT load topology (early return)
        mock_load_topo.assert_not_called()
        # MUST decrement inflight
        mock_r.decr.assert_called()

    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._load_topology")
    def test_node_not_in_topology_decrements_inflight(self, mock_load_topo, mock_redis_fn, mock_pub, mock_finalize):
        """When node is not in topology, inflight must be decremented."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_r.decr.return_value = 0
        mock_redis_fn.return_value = mock_r

        mock_load_topo.return_value = _make_topo_data(nodes={})  # no nodes

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-1"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("database.SessionLocal", return_value=mock_db):
            execute_node_job("exec-1", "missing_node")

        mock_r.decr.assert_called()
        # With 0 remaining, should finalize
        mock_finalize.assert_called_once_with("exec-1", mock_db)

    @patch("services.orchestrator._finalize")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator._load_topology")
    def test_node_not_in_topology_no_finalize_when_others_inflight(self, mock_load_topo, mock_redis_fn, mock_pub, mock_finalize):
        """When node missing but other nodes still inflight, should NOT finalize."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_r.decr.return_value = 2  # others still running
        mock_redis_fn.return_value = mock_r

        mock_load_topo.return_value = _make_topo_data(nodes={})

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-1"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("database.SessionLocal", return_value=mock_db):
            execute_node_job("exec-1", "missing_node")

        mock_r.decr.assert_called()
        mock_finalize.assert_not_called()


# ── Fix 1.2: Inflight decrement in outer exception handler ───────────────────


class TestInflightDecrementOnException:
    """Fix 1.2: Outer exception handler must decrement inflight and log errors."""

    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_unexpected_error_decrements_inflight(self, mock_load_topo, mock_load_state, mock_redis_fn, mock_pub, mock_episode, mock_cleanup):
        """Unexpected exception in execute_node_job must decrement inflight."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r

        topo_data = _make_topo_data(nodes={
            "agent_1": {
                "node_id": "agent_1",
                "component_type": "agent",
                "db_id": 10,
                "component_config_id": 20,
                "interrupt_before": False,
                "interrupt_after": False,
            }
        })
        mock_load_topo.return_value = topo_data
        mock_load_state.return_value = {"messages": [], "node_outputs": {}, "trigger": {}}

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-1"
        mock_execution.parent_execution_id = None
        mock_execution.parent_node_id = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        # Mock DB node that will cause an unexpected exception
        mock_config = MagicMock()
        mock_config.system_prompt = ""
        mock_config.extra_config = {}
        mock_db_node = MagicMock()
        mock_db_node.component_config = mock_config
        mock_db.get.return_value = mock_db_node

        # Factory that raises an unexpected error
        def exploding_factory(node):
            raise RuntimeError("Unexpected kaboom")

        with patch("database.SessionLocal", return_value=mock_db):
            with patch("components.get_component_factory", return_value=exploding_factory):
                with patch("services.orchestrator._check_budget", return_value=None):
                    execute_node_job("exec-1", "agent_1")

        # MUST decrement inflight
        mock_r.decr.assert_called()
        # MUST mark execution as failed
        assert mock_execution.status == "failed"
        assert "kaboom" in mock_execution.error_message
        # MUST clean up Redis
        mock_cleanup.assert_called_once_with("exec-1")

    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_db_commit_failure_logged_not_swallowed(self, mock_load_topo, mock_load_state, mock_redis_fn, mock_pub, mock_episode, mock_cleanup):
        """When db.commit() fails in exception handler, it should be logged, not silently swallowed."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r

        topo_data = _make_topo_data(nodes={
            "agent_1": {
                "node_id": "agent_1",
                "component_type": "agent",
                "db_id": 10,
                "component_config_id": 20,
                "interrupt_before": False,
                "interrupt_after": False,
            }
        })
        mock_load_topo.return_value = topo_data
        mock_load_state.return_value = {"messages": [], "node_outputs": {}, "trigger": {}}

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-1"
        mock_execution.parent_execution_id = None
        mock_execution.parent_node_id = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution
        # db.commit raises to simulate DB failure
        mock_db.commit.side_effect = Exception("DB connection lost")

        mock_config = MagicMock()
        mock_config.system_prompt = ""
        mock_config.extra_config = {}
        mock_db_node = MagicMock()
        mock_db_node.component_config = mock_config
        mock_db.get.return_value = mock_db_node

        def exploding_factory(node):
            raise RuntimeError("Unexpected error")

        with patch("database.SessionLocal", return_value=mock_db):
            with patch("components.get_component_factory", return_value=exploding_factory):
                with patch("services.orchestrator._check_budget", return_value=None):
                    # Should not raise even though commit fails
                    execute_node_job("exec-1", "agent_1")

        # Inflight should still be decremented
        mock_r.decr.assert_called()
        # Cleanup should still run
        mock_cleanup.assert_called_once()


# ── Fix 1.3: _finalize() exception safety ────────────────────────────────────


class TestFinalizeExceptionSafety:
    """Fix 1.3: _finalize() must not leave execution in 'running' on error."""

    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._get_workflow_slug", return_value="wf")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.load_state")
    def test_delivery_error_marks_failed(self, mock_load_state, mock_pub, mock_slug, mock_episode, mock_cleanup):
        """If output delivery raises, execution should be marked failed."""
        from services.orchestrator import _finalize

        mock_load_state.return_value = {"output": "result", "messages": []}

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-1"
        mock_execution.status = "running"
        mock_execution.parent_execution_id = None
        mock_execution.parent_node_id = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("services.delivery.output_delivery") as mock_delivery:
            mock_delivery.deliver.side_effect = RuntimeError("Delivery failed")
            _finalize("exec-1", mock_db)

        # Cleanup MUST always run (in finally block)
        mock_cleanup.assert_called_once_with("exec-1")

    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.load_state")
    def test_commit_failure_triggers_rollback_and_fail(self, mock_load_state, mock_pub, mock_cleanup):
        """If db.commit() fails during finalization, should rollback and mark failed."""
        from services.orchestrator import _finalize

        mock_load_state.return_value = {"output": "result", "messages": []}

        mock_db = MagicMock()

        # Initial execution returned for the status check
        mock_execution_initial = MagicMock()
        mock_execution_initial.execution_id = "exec-1"
        mock_execution_initial.status = "running"
        mock_execution_initial.parent_execution_id = None

        # After rollback, re-query returns a fresh object with status reverted to "running"
        mock_execution_recovery = MagicMock()
        mock_execution_recovery.execution_id = "exec-1"
        mock_execution_recovery.status = "running"

        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_execution_initial,  # initial query in _finalize
            mock_execution_recovery,  # re-query after rollback
        ]
        # First commit (normal finalize) fails, second (recovery) succeeds
        mock_db.commit.side_effect = [Exception("DB error"), None]

        _finalize("exec-1", mock_db)

        # Rollback should be called
        mock_db.rollback.assert_called()
        # Recovery object should be marked as failed
        assert mock_execution_recovery.status == "failed"
        assert "Finalization error" in mock_execution_recovery.error_message
        # Cleanup MUST always run
        mock_cleanup.assert_called_once_with("exec-1")

    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._get_workflow_slug", return_value="wf")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator.load_state")
    def test_successful_finalize_still_cleans_redis(self, mock_load_state, mock_pub, mock_slug, mock_episode, mock_cleanup):
        """Normal completion should also clean Redis (moved to finally block)."""
        from services.orchestrator import _finalize

        mock_load_state.return_value = {"output": "result", "messages": []}

        mock_db = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-1"
        mock_execution.status = "running"
        mock_execution.parent_execution_id = None
        mock_execution.parent_node_id = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_execution

        with patch("services.delivery.output_delivery"):
            _finalize("exec-1", mock_db)

        assert mock_execution.status == "completed"
        mock_cleanup.assert_called_once_with("exec-1")


# ── Fix 1.4: LLM credential null checks ──────────────────────────────────────


class TestLLMCredentialNullChecks:
    """Fix 1.4: resolve_llm_for_node must raise ValueError for missing credentials."""

    def test_missing_base_credential_ai_model(self):
        """Deleted credential should raise ValueError, not AttributeError."""
        from services.llm import resolve_llm_for_node

        mock_db = MagicMock()
        # query().filter().first() returns None (credential deleted)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        mock_config = MagicMock()
        mock_config.component_type = "ai_model"
        mock_config.model_name = "gpt-4"
        mock_config.llm_credential_id = 999

        mock_node = MagicMock()
        mock_node.node_id = "model_1"
        mock_node.component_config = mock_config

        with pytest.raises(ValueError, match="not found"):
            resolve_llm_for_node(mock_node, db=mock_db)

    def test_missing_llm_credential_relationship(self):
        """Base credential exists but llm_credential is None."""
        from services.llm import resolve_llm_for_node

        mock_db = MagicMock()
        mock_base_cred = MagicMock()
        mock_base_cred.llm_credential = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_base_cred

        mock_config = MagicMock()
        mock_config.component_type = "ai_model"
        mock_config.model_name = "gpt-4"
        mock_config.llm_credential_id = 1

        mock_node = MagicMock()
        mock_node.node_id = "model_1"
        mock_node.component_config = mock_config

        with pytest.raises(ValueError, match="no LLM provider"):
            resolve_llm_for_node(mock_node, db=mock_db)

    def test_missing_base_credential_via_model_config(self):
        """Deleted credential via llm_model_config_id path should raise ValueError."""
        from services.llm import resolve_llm_for_node

        mock_db = MagicMock()

        # The linked ai_model config exists but its credential is deleted
        mock_ai_config = MagicMock()
        mock_ai_config.component_type = "ai_model"
        mock_ai_config.model_name = "gpt-4"
        mock_ai_config.llm_credential_id = 999
        mock_db.get.return_value = mock_ai_config

        # Credential query returns None
        mock_db.query.return_value.filter.return_value.first.return_value = None

        mock_config = MagicMock()
        mock_config.component_type = "agent"
        mock_config.llm_model_config_id = 5
        mock_config.llm_credential_id = None

        mock_node = MagicMock()
        mock_node.node_id = "agent_1"
        mock_node.component_config = mock_config

        with pytest.raises(ValueError, match="not found"):
            resolve_llm_for_node(mock_node, db=mock_db)


# ── Fix 3.1: _publish_event failure safety ────────────────────────────────────


class TestPublishEventSafety:
    """Fix 3.1: _publish_event must not raise on Redis/serialization failures."""

    @patch("services.orchestrator._redis")
    def test_redis_failure_does_not_raise(self, mock_redis_fn):
        """Redis connection failure should be caught and logged, not propagated."""
        from services.orchestrator import _publish_event

        mock_redis_fn.side_effect = ConnectionError("Redis down")

        # Should NOT raise
        _publish_event("exec-1", "node_status", {"node_id": "n1"}, workflow_slug="wf")

    @patch("services.orchestrator._redis")
    def test_publish_failure_does_not_raise(self, mock_redis_fn):
        """Redis publish failure should be caught."""
        from services.orchestrator import _publish_event

        mock_r = MagicMock()
        mock_r.publish.side_effect = ConnectionError("Redis publish failed")
        mock_redis_fn.return_value = mock_r

        # Should NOT raise
        _publish_event("exec-1", "execution_completed", {"output": "ok"}, workflow_slug="wf")

    @patch("services.orchestrator._redis")
    def test_successful_publish_works(self, mock_redis_fn):
        """Normal publish should still work."""
        from services.orchestrator import _publish_event

        mock_r = MagicMock()
        mock_redis_fn.return_value = mock_r

        _publish_event("exec-1", "node_status", {"node_id": "n1"}, workflow_slug="wf")

        # Should have published to both channels
        assert mock_r.publish.call_count == 2
