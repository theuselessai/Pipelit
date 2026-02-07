"""Tests for schemas/node_io.py — NodeStatus, NodeError, NodeResult, NodeInput."""

from __future__ import annotations

from datetime import datetime, timezone

from schemas.node_io import NodeError, NodeInput, NodeResult, NodeStatus


class TestNodeStatus:
    def test_enum_values(self):
        assert NodeStatus.PENDING == "pending"
        assert NodeStatus.RUNNING == "running"
        assert NodeStatus.SUCCESS == "success"
        assert NodeStatus.FAILED == "failed"
        assert NodeStatus.SKIPPED == "skipped"

    def test_is_str_enum(self):
        assert isinstance(NodeStatus.PENDING, str)


class TestNodeError:
    def test_defaults(self):
        err = NodeError()
        assert err.code == ""
        assert err.message == ""
        assert err.details == {}
        assert err.recoverable is False
        assert err.node_id == ""

    def test_with_values(self):
        err = NodeError(
            code="TIMEOUT",
            message="Node timed out",
            details={"timeout_ms": 5000},
            recoverable=True,
            node_id="agent_123",
        )
        assert err.code == "TIMEOUT"
        assert err.message == "Node timed out"
        assert err.details == {"timeout_ms": 5000}
        assert err.recoverable is True
        assert err.node_id == "agent_123"


class TestNodeResult:
    def test_defaults(self):
        r = NodeResult()
        assert r.status == NodeStatus.SUCCESS
        assert r.data == {}
        assert r.error is None
        assert r.metadata == {}
        assert r.started_at is None
        assert r.completed_at is None

    def test_success_factory(self):
        r = NodeResult.success({"output": "hello"})
        assert r.status == NodeStatus.SUCCESS
        assert r.data == {"output": "hello"}
        assert r.error is None

    def test_success_factory_empty(self):
        r = NodeResult.success()
        assert r.data == {}

    def test_success_with_metadata(self):
        ts = datetime.now(timezone.utc)
        r = NodeResult.success({"x": 1}, metadata={"latency_ms": 42}, started_at=ts)
        assert r.metadata == {"latency_ms": 42}
        assert r.started_at == ts

    def test_failed_factory(self):
        r = NodeResult.failed("ERR_CONN", "Connection refused", node_id="n1", recoverable=True)
        assert r.status == NodeStatus.FAILED
        assert r.error is not None
        assert r.error.code == "ERR_CONN"
        assert r.error.message == "Connection refused"
        assert r.error.node_id == "n1"
        assert r.error.recoverable is True

    def test_failed_factory_minimal(self):
        r = NodeResult.failed("ERR", "oops")
        assert r.status == NodeStatus.FAILED
        assert r.error.node_id == ""
        assert r.error.recoverable is False

    def test_skipped_factory(self):
        r = NodeResult.skipped("Not needed")
        assert r.status == NodeStatus.SKIPPED
        assert r.metadata == {"skip_reason": "Not needed"}

    def test_skipped_factory_empty(self):
        r = NodeResult.skipped()
        assert r.metadata == {"skip_reason": ""}


class TestNodeInput:
    def test_defaults(self):
        inp = NodeInput()
        assert inp.trigger_payload == {}
        assert inp.upstream_results == {}
        assert inp.config == {}
        assert inp.execution_id == ""
        assert inp.workflow_id == 0
        assert inp.node_id == ""

    def test_with_upstream_results(self):
        r = NodeResult.success({"out": "data"})
        inp = NodeInput(
            upstream_results={"prev_node": r},
            execution_id="exec-123",
            workflow_id=5,
            node_id="my_node",
        )
        assert inp.upstream_results["prev_node"].status == NodeStatus.SUCCESS
        assert inp.execution_id == "exec-123"
        assert inp.workflow_id == 5
