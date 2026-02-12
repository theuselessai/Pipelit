"""Tests for _clear_stale_checkpoints in the orchestrator."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.execution import WorkflowExecution
from models.node import BaseComponentConfig, WorkflowNode
from models.workflow import Workflow


@pytest.fixture
def exec_workflow(db, user_profile):
    """Create a workflow + execution for checkpoint tests."""
    wf = Workflow(
        name="CP Test Workflow",
        slug="cp-test",
        owner_id=user_profile.id,
        is_active=True,
    )
    db.add(wf)
    db.flush()

    exe = WorkflowExecution(
        execution_id="exec-cp-1",
        workflow_id=wf.id,
        user_profile_id=user_profile.id,
        thread_id="test-thread",
        status="failed",
    )
    db.add(exe)
    db.commit()
    db.refresh(wf)
    db.refresh(exe)
    return wf, exe


def _add_agent_node(db, workflow_id, conversation_memory=True, node_id="agent_1"):
    """Helper to add an agent node with optional conversation_memory."""
    cfg = BaseComponentConfig(
        component_type="agent",
        system_prompt="test",
        extra_config={"conversation_memory": conversation_memory} if conversation_memory else {},
    )
    db.add(cfg)
    db.flush()
    node = WorkflowNode(
        workflow_id=workflow_id,
        node_id=node_id,
        component_type="agent",
        component_config_id=cfg.id,
    )
    db.add(node)
    db.commit()
    return node


class TestClearStaleCheckpoints:
    def test_with_conversation_memory(self, db, user_profile, exec_workflow):
        """Agent with conversation_memory triggers checkpoint deletion."""
        wf, exe = exec_workflow
        _add_agent_node(db, wf.id, conversation_memory=True)

        mock_checkpointer = MagicMock()

        from services.orchestrator import _clear_stale_checkpoints

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            _clear_stale_checkpoints(exe.execution_id, db)

        mock_checkpointer.delete_thread.assert_called_once()
        thread_id = mock_checkpointer.delete_thread.call_args[0][0]
        assert str(user_profile.id) in thread_id
        assert str(wf.id) in thread_id

    def test_with_chat_id(self, db, user_profile, exec_workflow):
        """Trigger payload with chat_id produces three-part thread_id."""
        wf, exe = exec_workflow
        exe.trigger_payload = {"chat_id": "12345"}
        db.commit()

        _add_agent_node(db, wf.id, conversation_memory=True)

        mock_checkpointer = MagicMock()

        from services.orchestrator import _clear_stale_checkpoints

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            _clear_stale_checkpoints(exe.execution_id, db)

        mock_checkpointer.delete_thread.assert_called_once()
        thread_id = mock_checkpointer.delete_thread.call_args[0][0]
        assert "12345" in thread_id
        # Three-part: user_id:chat_id:workflow_id
        assert thread_id.count(":") == 2

    def test_no_conversation_memory_noop(self, db, user_profile, exec_workflow):
        """Agent without conversation_memory doesn't trigger checkpoint cleanup."""
        wf, exe = exec_workflow
        _add_agent_node(db, wf.id, conversation_memory=False)

        from services.orchestrator import _clear_stale_checkpoints

        with patch("components.agent._get_checkpointer") as mock_get_cp:
            _clear_stale_checkpoints(exe.execution_id, db)

        mock_get_cp.assert_not_called()

    def test_no_agent_nodes_noop(self, db, user_profile, exec_workflow):
        """Execution with only non-agent nodes returns early."""
        wf, exe = exec_workflow
        # Add a code node instead of agent
        cfg = BaseComponentConfig(
            component_type="code",
            extra_config={"code": "pass", "language": "python"},
        )
        db.add(cfg)
        db.flush()
        node = WorkflowNode(
            workflow_id=wf.id,
            node_id="code_1",
            component_type="code",
            component_config_id=cfg.id,
        )
        db.add(node)
        db.commit()

        from services.orchestrator import _clear_stale_checkpoints

        with patch("components.agent._get_checkpointer") as mock_get_cp:
            _clear_stale_checkpoints(exe.execution_id, db)

        mock_get_cp.assert_not_called()

    def test_nonexistent_execution_returns_early(self, db):
        """Non-existent execution_id causes early return."""
        from services.orchestrator import _clear_stale_checkpoints

        # Should not raise, just return silently
        _clear_stale_checkpoints("nonexistent-exec-id", db)

    def test_fallback_sql_on_attribute_error(self, db, user_profile, exec_workflow):
        """When delete_thread raises AttributeError, falls back to SQL."""
        wf, exe = exec_workflow
        _add_agent_node(db, wf.id, conversation_memory=True)

        mock_checkpointer = MagicMock()
        mock_checkpointer.delete_thread.side_effect = AttributeError("no delete_thread")

        mock_conn = MagicMock()

        from services.orchestrator import _clear_stale_checkpoints

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            with patch("sqlite3.connect", return_value=mock_conn):
                _clear_stale_checkpoints(exe.execution_id, db)

        # SQL fallback should execute DELETE statements inside context manager
        assert mock_conn.execute.call_count >= 2
        mock_conn.__enter__.assert_called_once()
        mock_conn.close.assert_called_once()
