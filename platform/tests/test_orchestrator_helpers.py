"""Tests for orchestrator helper/utility functions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── Redis key helpers ─────────────────────────────────────────────────────────

class TestRedisKeyHelpers:
    def test_state_key(self):
        from services.orchestrator import _state_key
        assert _state_key("exec-1") == "execution:exec-1:state"

    def test_fanin_key(self):
        from services.orchestrator import _fanin_key
        assert _fanin_key("exec-1", "merge_1") == "execution:exec-1:fanin:merge_1"

    def test_lock_key(self):
        from services.orchestrator import _lock_key
        assert _lock_key("exec-1") == "execution:exec-1:lock"

    def test_topo_key(self):
        from services.orchestrator import _topo_key
        assert _topo_key("exec-1") == "execution:exec-1:topo"

    def test_completed_key(self):
        from services.orchestrator import _completed_key
        assert _completed_key("exec-1") == "execution:exec-1:completed"

    def test_episode_key(self):
        from services.orchestrator import _episode_key
        assert _episode_key("exec-1") == "execution:exec-1:episode_id"

    def test_inflight_key(self):
        from services.orchestrator import _inflight_key
        assert _inflight_key("exec-1") == "execution:exec-1:inflight"

    def test_loop_key(self):
        from services.orchestrator import _loop_key
        assert _loop_key("exec-1", "loop_1") == "execution:exec-1:loop:loop_1"

    def test_loop_iter_done_key_with_index(self):
        from services.orchestrator import _loop_iter_done_key
        assert _loop_iter_done_key("exec-1", "loop_1", 3) == "execution:exec-1:loop:loop_1:iter:3:done"

    def test_loop_iter_done_key_legacy(self):
        from services.orchestrator import _loop_iter_done_key
        assert _loop_iter_done_key("exec-1", "loop_1") == "execution:exec-1:loop:loop_1:iter_done"


# ── State helpers ─────────────────────────────────────────────────────────────

class TestStateHelpers:
    @patch("services.orchestrator._redis")
    def test_load_state_empty(self, mock_redis_fn):
        from services.orchestrator import load_state
        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_redis_fn.return_value = mock_r

        result = load_state("exec-1")
        assert result == {}

    @patch("services.orchestrator._redis")
    def test_load_and_save_roundtrip(self, mock_redis_fn):
        from services.orchestrator import load_state, save_state

        stored = {}
        mock_r = MagicMock()

        def mock_set(key, value, **kwargs):
            stored["data"] = value

        def mock_get(key):
            return stored.get("data")

        mock_r.set.side_effect = mock_set
        mock_r.get.side_effect = mock_get
        mock_redis_fn.return_value = mock_r

        save_state("exec-1", {"route": "a", "node_outputs": {"n1": {"output": "hi"}}})
        result = load_state("exec-1")
        assert result["route"] == "a"
        assert result["node_outputs"]["n1"]["output"] == "hi"


# ── _safe_json ────────────────────────────────────────────────────────────────

class TestSafeJson:
    def test_none(self):
        from services.orchestrator import _safe_json
        assert _safe_json(None) is None

    def test_dict_serializable(self):
        from services.orchestrator import _safe_json
        d = {"key": "value", "num": 42}
        assert _safe_json(d) == d

    def test_dict_not_serializable(self):
        from services.orchestrator import _safe_json
        d = {"fn": lambda x: x}
        result = _safe_json(d)
        assert "repr" in result

    def test_non_dict(self):
        from services.orchestrator import _safe_json
        result = _safe_json([1, 2, 3])
        assert "repr" in result


# ── _truncate_output ──────────────────────────────────────────────────────────

class TestTruncateOutput:
    def test_none(self):
        from services.orchestrator import _truncate_output
        assert _truncate_output(None) is None

    def test_short_string(self):
        from services.orchestrator import _truncate_output
        assert _truncate_output("hello") == "hello"

    def test_long_string(self):
        from services.orchestrator import _truncate_output
        result = _truncate_output("x" * 5000, max_str_len=100)
        assert len(result) == 100

    def test_dict_with_short_values(self):
        from services.orchestrator import _truncate_output
        d = {"a": "short", "b": 42}
        assert _truncate_output(d) == d

    def test_dict_with_long_values(self):
        from services.orchestrator import _truncate_output
        d = {"a": "x" * 5000}
        result = _truncate_output(d, max_str_len=100)
        assert result["a"].endswith("...")
        assert len(result["a"]) == 103  # 100 + "..."

    def test_non_dict_non_string(self):
        from services.orchestrator import _truncate_output
        result = _truncate_output([1, 2, 3])
        assert "repr" in result

    def test_non_serializable_dict(self):
        from services.orchestrator import _truncate_output
        d = {"fn": object()}
        result = _truncate_output(d)
        assert "repr" in result


# ── _extract_output ───────────────────────────────────────────────────────────

class TestExtractOutput:
    def test_with_output_key(self):
        from services.orchestrator import _extract_output
        state = {"output": "final result"}
        assert _extract_output(state) == {"output": "final result"}

    def test_with_ai_message(self):
        from services.orchestrator import _extract_output
        msg = SimpleNamespace(type="ai", content="AI response")
        state = {"messages": [msg]}
        assert _extract_output(state) == {"message": "AI response"}

    def test_prefers_last_ai_message(self):
        from services.orchestrator import _extract_output
        msg1 = SimpleNamespace(type="human", content="Hi")
        msg2 = SimpleNamespace(type="ai", content="Hello")
        msg3 = SimpleNamespace(type="ai", content="Final answer")
        state = {"messages": [msg1, msg2, msg3]}
        assert _extract_output(state) == {"message": "Final answer"}

    def test_with_node_outputs(self):
        from services.orchestrator import _extract_output
        state = {"node_outputs": {"n1": {"out": "data"}}}
        assert _extract_output(state) == {"node_outputs": {"n1": {"out": "data"}}}

    def test_fallback_to_last_message(self):
        from services.orchestrator import _extract_output
        msg = SimpleNamespace(type="human", content="Hello")
        state = {"messages": [msg]}
        assert _extract_output(state) == {"message": "Hello"}

    def test_message_without_content(self):
        from services.orchestrator import _extract_output
        state = {"messages": ["raw string"]}
        assert _extract_output(state) == {"message": "raw string"}

    def test_empty_state(self):
        from services.orchestrator import _extract_output
        assert _extract_output({}) is None

    def test_output_none(self):
        from services.orchestrator import _extract_output
        state = {"output": None}
        # output is None → skip to messages
        assert _extract_output(state) is None

    def test_empty_ai_messages_skipped(self):
        from services.orchestrator import _extract_output
        msg = SimpleNamespace(type="ai", content="")
        state = {"messages": [msg]}
        # Empty content AI messages should be skipped
        result = _extract_output(state)
        # Falls through to last message fallback
        assert result == {"message": ""}


# ── _build_initial_state ──────────────────────────────────────────────────────

class TestBuildInitialState:
    def test_with_text(self):
        from services.orchestrator import _build_initial_state

        execution = SimpleNamespace(
            trigger_payload={"text": "Hello", "chat_id": 12345},
            user_profile_id=1,
            execution_id="exec-abc",
        )
        state = _build_initial_state(execution)
        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "Hello"
        assert state["trigger"]["text"] == "Hello"
        assert state["execution_id"] == "exec-abc"
        assert state["user_context"]["user_profile_id"] == 1
        assert state["route"] == ""
        assert state["node_outputs"] == {}

    def test_without_text(self):
        from services.orchestrator import _build_initial_state

        execution = SimpleNamespace(
            trigger_payload={"key": "value"},
            user_profile_id=2,
            execution_id="exec-def",
        )
        state = _build_initial_state(execution)
        assert state["messages"] == []
        assert state["trigger"]["key"] == "value"

    def test_empty_payload(self):
        from services.orchestrator import _build_initial_state

        execution = SimpleNamespace(
            trigger_payload=None,
            user_profile_id=3,
            execution_id="exec-ghi",
        )
        state = _build_initial_state(execution)
        assert state["messages"] == []
        assert state["trigger"] == {}


# ── _write_log ────────────────────────────────────────────────────────────────

class TestWriteLog:
    def test_writes_log(self, db):
        from services.orchestrator import _write_log
        from models.execution import WorkflowExecution, ExecutionLog

        # Need a workflow + execution first
        from models.workflow import Workflow
        from models.user import UserProfile
        from passlib.hash import pbkdf2_sha256

        user = UserProfile(username="logtest", password_hash=pbkdf2_sha256.hash("p"))
        db.add(user)
        db.flush()

        wf = Workflow(name="Log Test", slug="log-test", owner_id=user.id)
        db.add(wf)
        db.flush()

        ex = WorkflowExecution(
            workflow_id=wf.id,
            user_profile_id=user.id,
            thread_id="test-thread-1",
            trigger_payload={},
        )
        db.add(ex)
        db.commit()

        _write_log(db, str(ex.execution_id), "node_1", "completed",
                    duration_ms=42, output={"result": "ok"})

        log = db.query(ExecutionLog).first()
        assert log.node_id == "node_1"
        assert log.status == "completed"
        assert log.duration_ms == 42

    def test_truncates_error(self, db):
        from services.orchestrator import _write_log
        from models.execution import WorkflowExecution, ExecutionLog
        from models.workflow import Workflow
        from models.user import UserProfile
        from passlib.hash import pbkdf2_sha256

        user = UserProfile(username="logtest2", password_hash=pbkdf2_sha256.hash("p"))
        db.add(user)
        db.flush()

        wf = Workflow(name="Err Test", slug="err-test", owner_id=user.id)
        db.add(wf)
        db.flush()

        ex = WorkflowExecution(workflow_id=wf.id, user_profile_id=user.id, thread_id="t2", trigger_payload={})
        db.add(ex)
        db.commit()

        _write_log(db, str(ex.execution_id), "n1", "failed", error="x" * 5000, error_code="TIMEOUT")
        log = db.query(ExecutionLog).first()
        assert len(log.error) <= 2000
        assert log.error_code == "TIMEOUT"


# ── _publish_event ────────────────────────────────────────────────────────────

class TestPublishEvent:
    @patch("services.orchestrator._redis")
    def test_publishes_to_execution_channel(self, mock_redis_fn):
        from services.orchestrator import _publish_event

        mock_r = MagicMock()
        mock_redis_fn.return_value = mock_r

        _publish_event("exec-1", "node_status", {"node_id": "n1"})
        mock_r.publish.assert_called_once()
        channel, payload_str = mock_r.publish.call_args[0]
        assert channel == "execution:exec-1"
        payload = json.loads(payload_str)
        assert payload["type"] == "node_status"
        assert payload["data"]["node_id"] == "n1"

    @patch("services.orchestrator._redis")
    def test_publishes_to_workflow_channel(self, mock_redis_fn):
        from services.orchestrator import _publish_event

        mock_r = MagicMock()
        mock_redis_fn.return_value = mock_r

        _publish_event("exec-1", "node_status", {"node_id": "n1"}, workflow_slug="my-wf")
        assert mock_r.publish.call_count == 2
        # Second publish to workflow channel
        second_call = mock_r.publish.call_args_list[1]
        assert second_call[0][0] == "workflow:my-wf"


# ── _save_topology / _load_topology ──────────────────────────────────────────

class TestTopologyStorage:
    @patch("services.orchestrator._redis")
    def test_save_and_load(self, mock_redis_fn):
        from services.orchestrator import _save_topology, _load_topology

        stored = {}
        mock_r = MagicMock()

        def mock_set(key, value, **kwargs):
            stored[key] = value

        def mock_get(key):
            return stored.get(key)

        mock_r.set.side_effect = mock_set
        mock_r.get.side_effect = mock_get
        mock_redis_fn.return_value = mock_r

        topo = SimpleNamespace(
            workflow_slug="my-wf",
            entry_node_ids=["trigger_1"],
            nodes={
                "trigger_1": SimpleNamespace(
                    node_id="trigger_1",
                    component_type="trigger_manual",
                    db_id=1,
                    component_config_id=1,
                    interrupt_before=False,
                    interrupt_after=False,
                ),
            },
            edges_by_source={
                "trigger_1": [
                    SimpleNamespace(
                        source_node_id="trigger_1",
                        target_node_id="agent_1",
                        edge_type="direct",
                        edge_label="",
                        condition_mapping=None,
                        condition_value="",
                        priority=0,
                    )
                ],
            },
            incoming_count={"agent_1": 1},
            loop_bodies={},
            loop_return_nodes={},
            loop_body_all_nodes={},
        )

        _save_topology("exec-1", topo)
        result = _load_topology("exec-1")
        assert result["workflow_slug"] == "my-wf"
        assert result["entry_node_ids"] == ["trigger_1"]
        assert "trigger_1" in result["nodes"]
        assert result["incoming_count"]["agent_1"] == 1

    @patch("services.orchestrator._redis")
    def test_load_missing_raises(self, mock_redis_fn):
        from services.orchestrator import _load_topology

        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_redis_fn.return_value = mock_r

        with pytest.raises(RuntimeError, match="Topology not found"):
            _load_topology("nonexistent")


# ── _cleanup_redis ────────────────────────────────────────────────────────────

class TestCleanupRedis:
    @patch("services.orchestrator._redis")
    def test_deletes_keys(self, mock_redis_fn):
        from services.orchestrator import _cleanup_redis

        mock_r = MagicMock()
        mock_r.keys.return_value = ["execution:e1:state", "execution:e1:topo"]
        mock_redis_fn.return_value = mock_r

        _cleanup_redis("e1")
        mock_r.delete.assert_called_once_with("execution:e1:state", "execution:e1:topo")

    @patch("services.orchestrator._redis")
    def test_no_keys(self, mock_redis_fn):
        from services.orchestrator import _cleanup_redis

        mock_r = MagicMock()
        mock_r.keys.return_value = []
        mock_redis_fn.return_value = mock_r

        _cleanup_redis("e1")
        mock_r.delete.assert_not_called()


# ── _get_workflow_slug ────────────────────────────────────────────────────────

class TestGetWorkflowSlug:
    @patch("services.orchestrator._load_topology")
    def test_from_topology(self, mock_load):
        from services.orchestrator import _get_workflow_slug
        mock_load.return_value = {"workflow_slug": "my-wf"}
        assert _get_workflow_slug("exec-1") == "my-wf"

    @patch("services.orchestrator._load_topology", side_effect=RuntimeError)
    def test_from_db(self, mock_load):
        from services.orchestrator import _get_workflow_slug
        mock_db = MagicMock()
        mock_exec = MagicMock()
        mock_exec.workflow_id = 1
        mock_wf = MagicMock()
        mock_wf.slug = "db-slug"
        mock_db.query.return_value.filter.return_value.first.side_effect = [mock_exec, mock_wf]

        assert _get_workflow_slug("exec-1", db=mock_db) == "db-slug"

    @patch("services.orchestrator._load_topology", side_effect=RuntimeError)
    def test_none_when_not_found(self, mock_load):
        from services.orchestrator import _get_workflow_slug
        assert _get_workflow_slug("exec-1") is None


# ── start_execution_job ───────────────────────────────────────────────────────

class TestStartExecutionJob:
    @patch("services.orchestrator.start_execution")
    def test_delegates(self, mock_start):
        from services.orchestrator import start_execution_job
        start_execution_job("exec-1")
        mock_start.assert_called_once_with("exec-1")


# ── _handle_interrupt ─────────────────────────────────────────────────────────

class TestHandleInterrupt:
    def test_creates_pending_task(self, db):
        from services.orchestrator import _handle_interrupt
        from models.execution import PendingTask, WorkflowExecution
        from models.workflow import Workflow
        from models.user import UserProfile
        from passlib.hash import pbkdf2_sha256

        user = UserProfile(username="inttest", password_hash=pbkdf2_sha256.hash("p"))
        db.add(user)
        db.flush()

        wf = Workflow(name="Int Test", slug="int-test", owner_id=user.id)
        db.add(wf)
        db.flush()

        ex = WorkflowExecution(
            workflow_id=wf.id,
            user_profile_id=user.id,
            thread_id="int-thread",
            trigger_payload={"chat_id": 12345},
        )
        db.add(ex)
        db.commit()

        with patch("services.orchestrator._get_workflow_slug", return_value="int-test"):
            with patch("services.orchestrator._publish_event"):
                _handle_interrupt(ex, "human_1", "before", db)

        assert ex.status == "interrupted"
        pending = db.query(PendingTask).first()
        assert pending is not None
        assert pending.node_id == "human_1"
        assert "before" in pending.prompt


# ── _start_episode / _complete_episode ────────────────────────────────────────

class TestEpisodeHelpers:
    @patch("services.orchestrator._redis")
    def test_start_episode_telegram(self, mock_redis_fn):
        from services.orchestrator import _start_episode

        mock_r = MagicMock()
        mock_redis_fn.return_value = mock_r

        mock_memory = MagicMock()
        mock_episode = MagicMock()
        mock_episode.id = 42
        mock_memory.log_episode.return_value = mock_episode

        # _start_episode does: from services.memory import MemoryService
        with patch("services.memory.MemoryService", return_value=mock_memory):
            result = _start_episode(
                execution_id="exec-1",
                workflow_id=1,
                trigger_type="telegram",
                trigger_payload={"message": {"from": {"id": 999}}},
                db=MagicMock(),
            )

        assert result == 42
        mock_r.set.assert_called_once()
        call_args = mock_memory.log_episode.call_args
        assert call_args[1]["user_id"] == "telegram:999"

    @patch("services.orchestrator._redis")
    def test_start_episode_user_id_payload(self, mock_redis_fn):
        from services.orchestrator import _start_episode

        mock_r = MagicMock()
        mock_redis_fn.return_value = mock_r

        mock_memory = MagicMock()
        mock_episode = MagicMock()
        mock_episode.id = 99
        mock_memory.log_episode.return_value = mock_episode

        with patch("services.memory.MemoryService", return_value=mock_memory):
            result = _start_episode("exec-2", 2, "webhook", {"user_id": "u123"}, MagicMock())

        assert result == 99
        call_args = mock_memory.log_episode.call_args
        assert call_args[1]["user_id"] == "u123"

    @patch("services.orchestrator._redis")
    def test_start_episode_failure(self, mock_redis_fn):
        from services.orchestrator import _start_episode

        with patch("services.memory.MemoryService", side_effect=RuntimeError("fail")):
            result = _start_episode("exec-1", 1, "manual", None, MagicMock())

        assert result is None

    @patch("services.orchestrator._redis")
    @patch("services.orchestrator.load_state")
    def test_complete_episode(self, mock_load_state, mock_redis_fn):
        from services.orchestrator import _complete_episode

        mock_r = MagicMock()
        mock_r.get.return_value = "42"
        mock_redis_fn.return_value = mock_r

        mock_load_state.return_value = {
            "messages": [],
            "node_results": {"n1": {"status": "success"}},
        }

        mock_memory = MagicMock()
        mock_db = MagicMock()
        # _complete_episode does: from database import SessionLocal
        with patch("database.SessionLocal", return_value=mock_db):
            with patch("services.memory.MemoryService", return_value=mock_memory):
                _complete_episode("exec-1", True, {"output": "done"})

        mock_memory.complete_episode.assert_called_once()

    @patch("services.orchestrator._redis")
    def test_complete_episode_no_episode_id(self, mock_redis_fn):
        from services.orchestrator import _complete_episode

        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_redis_fn.return_value = mock_r

        # Should return early without error
        _complete_episode("exec-1", True, None)

    @patch("services.orchestrator._redis")
    def test_complete_episode_failure(self, mock_redis_fn):
        from services.orchestrator import _complete_episode

        mock_r = MagicMock()
        mock_r.get.return_value = "42"
        mock_redis_fn.return_value = mock_r

        with patch("database.SessionLocal", side_effect=RuntimeError("db fail")):
            # Should not raise
            _complete_episode("exec-1", False, None, error_code="ERR", error_message="boom")
