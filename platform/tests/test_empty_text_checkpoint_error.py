"""Tests for auto-clearing checkpoints on 'text cannot be empty' errors."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)


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


def _make_topo_data(node_id="agent_1"):
    return {
        "workflow_slug": "wf",
        "nodes": {
            node_id: {
                "node_id": node_id, "component_type": "agent",
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


def _make_mock_db(mock_execution=None):
    mock_config = MagicMock()
    mock_config.system_prompt = ""
    mock_config.extra_config = {}
    mock_db_node = MagicMock()
    mock_db_node.component_config = mock_config

    mock_db = MagicMock()
    if mock_execution is None:
        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_execution.execution_id = "exec-1"
        mock_execution.started_at = None
    mock_db.query.return_value.filter.return_value.first.return_value = mock_execution
    mock_db.get.return_value = mock_db_node
    return mock_db, mock_execution


class TestEmptyTextCheckpointError:
    """Verify that 'text cannot be empty' errors trigger checkpoint clearing and skip retries."""

    @patch("services.orchestrator._clear_stale_checkpoints")
    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_clears_checkpoints_on_empty_text_error(
        self, mock_load_topo, mock_load_state, mock_save_state,
        mock_redis_fn, mock_pub, mock_queue_fn, mock_clear_cp,
    ):
        """When 'text cannot be empty' is in the error, _clear_stale_checkpoints is called."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_load_topo.return_value = _make_topo_data()
        mock_load_state.return_value = {"messages": [], "node_outputs": {}, "trigger": {}}

        mock_db, mock_execution = _make_mock_db()

        def _raise(*args, **kwargs):
            raise RuntimeError("Error code: 1214, text cannot be empty")

        with patch("components.get_component_factory", return_value=lambda node: _raise):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-1", "agent_1", retry_count=0)

        # Called twice: once in detection block, once in permanent failure path (idempotent)
        assert mock_clear_cp.call_count >= 1
        mock_clear_cp.assert_any_call("exec-1", mock_db)

    @patch("services.orchestrator._clear_stale_checkpoints")
    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_skips_retries_on_empty_text_error(
        self, mock_load_topo, mock_load_state, mock_save_state,
        mock_redis_fn, mock_pub, mock_queue_fn, mock_clear_cp,
    ):
        """Retries are skipped — enqueue_in is NOT called even at retry_count=0."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q
        mock_load_topo.return_value = _make_topo_data()
        mock_load_state.return_value = {"messages": [], "node_outputs": {}, "trigger": {}}

        mock_db, mock_execution = _make_mock_db()

        def _raise(*args, **kwargs):
            raise RuntimeError("text cannot be empty")

        with patch("components.get_component_factory", return_value=lambda node: _raise):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-1", "agent_1", retry_count=0)

        # Retry queue should NOT be called
        mock_q.enqueue_in.assert_not_called()
        # Execution should be marked as failed
        assert mock_execution.status == "failed"

    @patch("services.orchestrator._clear_stale_checkpoints")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_enhanced_error_message_in_publish_event(
        self, mock_load_topo, mock_load_state, mock_save_state,
        mock_redis_fn, mock_pub, mock_clear_cp,
    ):
        """The published error message includes the 'Checkpoints cleared' text."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_load_topo.return_value = _make_topo_data()
        mock_load_state.return_value = {"messages": [], "node_outputs": {}, "trigger": {}}

        mock_db, mock_execution = _make_mock_db()

        def _raise(*args, **kwargs):
            raise RuntimeError("Text cannot be empty for this provider")

        with patch("components.get_component_factory", return_value=lambda node: _raise):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log") as mock_write_log:
                    execute_node_job("exec-1", "agent_1", retry_count=0)

        # Check _write_log was called with enhanced error message
        write_log_calls = mock_write_log.call_args_list
        assert len(write_log_calls) >= 1
        # The error kwarg should contain the checkpoint cleared message
        error_arg = write_log_calls[0][1].get("error", "")
        assert "Checkpoints cleared automatically" in error_arg

        # Check _publish_event node_status call includes enhanced error
        node_status_calls = [
            c for c in mock_pub.call_args_list
            if len(c[0]) >= 3 and isinstance(c[0][2], dict)
            and c[0][2].get("status") == "failed"
        ]
        assert len(node_status_calls) >= 1
        assert "Checkpoints cleared automatically" in node_status_calls[0][0][2]["error"]

    @patch("services.orchestrator._clear_stale_checkpoints")
    @patch("services.orchestrator._queue")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_normal_error_still_retries(
        self, mock_load_topo, mock_load_state, mock_save_state,
        mock_redis_fn, mock_pub, mock_queue_fn, mock_clear_cp,
    ):
        """Errors NOT containing 'text cannot be empty' still go through normal retry logic."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q
        mock_load_topo.return_value = _make_topo_data()
        mock_load_state.return_value = {"messages": [], "node_outputs": {}, "trigger": {}}

        mock_db, mock_execution = _make_mock_db()

        def _raise(*args, **kwargs):
            raise RuntimeError("some other error")

        with patch("components.get_component_factory", return_value=lambda node: _raise):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-1", "agent_1", retry_count=0)

        # Normal error should still retry
        mock_q.enqueue_in.assert_called_once()
        # _clear_stale_checkpoints should NOT be called in the error detection block
        # (it may be called later in the permanent failure path, but not here)
        mock_clear_cp.assert_not_called()

    @patch("services.orchestrator._clear_stale_checkpoints")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.save_state")
    @patch("services.orchestrator.load_state")
    @patch("services.orchestrator._load_topology")
    def test_case_insensitive_detection(
        self, mock_load_topo, mock_load_state, mock_save_state,
        mock_redis_fn, mock_pub, mock_clear_cp,
    ):
        """Detection is case-insensitive (GLM may use different casing)."""
        from services.orchestrator import execute_node_job

        mock_r = _mock_redis()
        mock_redis_fn.return_value = mock_r
        mock_load_topo.return_value = _make_topo_data()
        mock_load_state.return_value = {"messages": [], "node_outputs": {}, "trigger": {}}

        mock_db, mock_execution = _make_mock_db()

        def _raise(*args, **kwargs):
            raise RuntimeError("TEXT CANNOT BE EMPTY")

        with patch("components.get_component_factory", return_value=lambda node: _raise):
            with patch("database.SessionLocal", return_value=mock_db):
                with patch("services.orchestrator._write_log"):
                    execute_node_job("exec-1", "agent_1", retry_count=0)

        assert mock_clear_cp.call_count >= 1
