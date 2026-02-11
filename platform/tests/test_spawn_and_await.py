"""Tests for spawn_and_await tool, checkpointer selection, interrupt/resume flow, and cost sync."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from models.epic import Epic, Task
from models.execution import WorkflowExecution


def _make_node(component_type, workflow_id, node_id="tool_node_1"):
    config = SimpleNamespace(
        component_type=component_type,
        extra_config={},
        system_prompt="",
        concrete=SimpleNamespace(
            system_prompt="",
            extra_config={},
        ),
    )
    # Make config.concrete return config itself for attribute access
    config.concrete = config
    return SimpleNamespace(
        node_id=node_id,
        workflow_id=workflow_id,
        component_type=component_type,
        component_config=config,
    )


@pytest.fixture
def mock_session(db):
    """Patch SessionLocal to return the test db session with close() as no-op."""
    original_close = db.close
    db.close = lambda: None
    with patch("database.SessionLocal", return_value=db):
        yield db
    db.close = original_close


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


class TestSpawnAndAwaitFactory:
    def test_returns_list_with_one_tool(self):
        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tools = spawn_and_await_factory(node)

        assert isinstance(tools, list)
        assert len(tools) == 1
        assert tools[0].name == "spawn_and_await"

    def test_tool_has_correct_signature(self):
        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tools = spawn_and_await_factory(node)
        tool = tools[0]

        # Check that tool has expected parameters in its schema
        schema = tool.args_schema.schema() if hasattr(tool, "args_schema") else {}
        props = schema.get("properties", {})
        assert "workflow_slug" in props
        assert "input_text" in props
        assert "task_id" in props
        assert "input_data" in props


# ---------------------------------------------------------------------------
# Checkpointer selection
# ---------------------------------------------------------------------------


class TestCheckpointerSelection:
    """Test dual checkpointer selection logic in agent_factory."""

    def _build_agent(self, conversation_memory=False, has_spawn_tool=False):
        """Call real agent_factory and capture the checkpointer it selected."""
        from components.agent import agent_factory

        mock_tools = []
        if has_spawn_tool:
            mock_spawn = MagicMock()
            mock_spawn.name = "spawn_and_await"
            mock_tools.append(mock_spawn)

        mock_sqlite = MagicMock(name="sqlite_checkpointer")
        mock_redis = MagicMock(name="redis_checkpointer")

        node = _make_node("agent", workflow_id=1)
        node.component_config.extra_config = {"conversation_memory": conversation_memory}
        node.component_config.concrete.extra_config = {"conversation_memory": conversation_memory}

        captured = {}

        def capture_create_agent(**kwargs):
            captured["checkpointer"] = kwargs.get("checkpointer")
            return MagicMock()

        with patch("components.agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.agent._resolve_tools", return_value=mock_tools), \
             patch("components.agent.create_react_agent", side_effect=capture_create_agent), \
             patch("components.agent._get_checkpointer", return_value=mock_sqlite), \
             patch("components.agent._get_redis_checkpointer", return_value=mock_redis):
            agent_factory(node)

        return captured.get("checkpointer"), mock_sqlite, mock_redis

    def test_no_memory_no_spawn_returns_none(self):
        checkpointer, _, _ = self._build_agent(conversation_memory=False, has_spawn_tool=False)
        assert checkpointer is None

    def test_conversation_memory_returns_sqlite(self):
        checkpointer, mock_sqlite, _ = self._build_agent(conversation_memory=True, has_spawn_tool=False)
        assert checkpointer is mock_sqlite

    def test_spawn_tool_returns_redis(self):
        checkpointer, _, mock_redis = self._build_agent(conversation_memory=False, has_spawn_tool=True)
        assert checkpointer is mock_redis

    def test_both_prefers_sqlite(self):
        checkpointer, mock_sqlite, _ = self._build_agent(conversation_memory=True, has_spawn_tool=True)
        assert checkpointer is mock_sqlite


# ---------------------------------------------------------------------------
# Interrupt flow
# ---------------------------------------------------------------------------


class TestInterruptFlow:
    """Test that GraphInterrupt from spawn_and_await is caught and creates child execution."""

    def test_graph_interrupt_returns_subworkflow(self, mock_session, workflow, user_profile):
        from components.agent import _create_child_from_interrupt

        # Create a target workflow
        from models.workflow import Workflow
        target_wf = Workflow(
            name="Child Workflow",
            slug="child-workflow",
            owner_id=user_profile.id,
            is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()
        mock_session.refresh(target_wf)

        # Create parent execution
        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={"text": "test"},
            thread_id="test-thread",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
        }
        interrupt_data = {
            "action": "spawn_workflow",
            "workflow_slug": "child-workflow",
            "input_text": "Do something",
            "task_id": None,
            "input_data": {"key": "value"},
        }

        # Mock RQ enqueue to avoid actual job dispatch
        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            child_id = _create_child_from_interrupt(interrupt_data, state, "agent_1")

        # Verify child execution was created
        child_exec = (
            mock_session.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == child_id)
            .first()
        )
        assert child_exec is not None
        assert child_exec.parent_execution_id == str(parent_exec.execution_id)
        assert child_exec.parent_node_id == "agent_1"
        assert child_exec.workflow_id == target_wf.id
        assert child_exec.trigger_payload["text"] == "Do something"

    def test_interrupt_raises_on_missing_workflow(self, mock_session, workflow, user_profile):
        from components.agent import _create_child_from_interrupt

        state = {
            "execution_id": "test-exec-id",
            "user_context": {"user_profile_id": user_profile.id},
        }
        interrupt_data = {
            "workflow_slug": "nonexistent-workflow",
        }

        with pytest.raises(ValueError, match="target workflow not found"):
            _create_child_from_interrupt(interrupt_data, state, "agent_1")


# ---------------------------------------------------------------------------
# Task linkage in child creation
# ---------------------------------------------------------------------------


class TestTaskLinkage:
    def test_task_linked_when_task_id_provided(self, mock_session, workflow, user_profile):
        from components.agent import _create_child_from_interrupt
        from models.workflow import Workflow

        # Create target workflow
        target_wf = Workflow(
            name="Child WF",
            slug="child-wf",
            owner_id=user_profile.id,
            is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()

        # Create epic and task
        epic = Epic(
            title="Test Epic",
            user_profile_id=user_profile.id,
        )
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(
            epic_id=epic.id,
            title="Test Task",
            status="pending",
        )
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        # Create parent execution
        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="test",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
        }
        interrupt_data = {
            "workflow_slug": "child-wf",
            "input_text": "run task",
            "task_id": task.id,
            "input_data": {},
        }

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            child_id = _create_child_from_interrupt(interrupt_data, state, "agent_1")

        # Verify task was linked
        mock_session.refresh(task)
        assert task.execution_id == child_id
        assert task.status == "running"


# ---------------------------------------------------------------------------
# Cost sync
# ---------------------------------------------------------------------------


class TestCostSync:
    def test_sync_completed_execution(self, mock_session, workflow, user_profile):
        from services.orchestrator import _sync_task_costs

        # Create epic + task
        epic = Epic(title="E", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(epic_id=epic.id, title="T", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        # Create execution linked to task
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
            final_output={"message": "done"},
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        task.execution_id = str(execution.execution_id)
        mock_session.commit()

        _sync_task_costs(str(execution.execution_id), mock_session)

        mock_session.refresh(task)
        assert task.status == "completed"
        assert task.duration_ms == 5000
        assert task.result_summary is not None
        assert task.completed_at is not None

    def test_sync_failed_execution(self, mock_session, workflow, user_profile):
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="E", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(epic_id=epic.id, title="T", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="failed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
            error_message="Node agent_1: something went wrong",
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        task.execution_id = str(execution.execution_id)
        mock_session.commit()

        _sync_task_costs(str(execution.execution_id), mock_session)

        mock_session.refresh(task)
        assert task.status == "failed"
        assert task.duration_ms == 3000
        assert task.error_message is not None

    def test_no_op_when_no_linked_task(self, mock_session, workflow, user_profile):
        from services.orchestrator import _sync_task_costs

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        # Should not raise — just a no-op
        _sync_task_costs(str(execution.execution_id), mock_session)

    def test_epic_progress_synced(self, mock_session, workflow, user_profile):
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="E", user_profile_id=user_profile.id, total_tasks=0, completed_tasks=0)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        # Add two tasks — one completed, one to be synced
        done_task = Task(epic_id=epic.id, title="Done", status="completed")
        mock_session.add(done_task)
        pending_task = Task(epic_id=epic.id, title="Pending", status="running")
        mock_session.add(pending_task)
        mock_session.commit()
        mock_session.refresh(pending_task)

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        pending_task.execution_id = str(execution.execution_id)
        mock_session.commit()

        _sync_task_costs(str(execution.execution_id), mock_session)

        mock_session.refresh(epic)
        assert epic.total_tasks == 2
        assert epic.completed_tasks == 2  # both should be completed now


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_spawn_and_await_in_node_type_registry(self):
        import schemas.node_type_defs  # noqa: F401 — triggers registration
        from schemas.node_types import NODE_TYPE_REGISTRY

        assert "spawn_and_await" in NODE_TYPE_REGISTRY
        spec = NODE_TYPE_REGISTRY["spawn_and_await"]
        assert spec.display_name == "Spawn & Await"
        assert spec.category == "agent"

    def test_spawn_and_await_in_builder_sub_component_types(self):
        from services.builder import SUB_COMPONENT_TYPES

        assert "spawn_and_await" in SUB_COMPONENT_TYPES

    def test_spawn_and_await_in_topology_sub_component_types(self):
        from services.topology import SUB_COMPONENT_TYPES

        assert "spawn_and_await" in SUB_COMPONENT_TYPES

    def test_spawn_and_await_in_component_registry(self):
        from components import COMPONENT_REGISTRY

        assert "spawn_and_await" in COMPONENT_REGISTRY

    def test_spawn_and_await_polymorphic_identity(self):
        from models.node import COMPONENT_TYPE_TO_CONFIG

        assert "spawn_and_await" in COMPONENT_TYPE_TO_CONFIG


# ---------------------------------------------------------------------------
# Tool invocation (spawn_and_await.py lines 47–60)
# ---------------------------------------------------------------------------


class TestToolInvocation:
    """Test spawn_and_await tool body: interrupt call and result serialization."""

    def test_tool_returns_json_when_interrupt_returns_dict(self):
        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tool = spawn_and_await_factory(node)[0]

        child_output = {"result": "done", "score": 42}

        with patch("langgraph.types.interrupt", return_value=child_output):
            result = tool.invoke({
                "workflow_slug": "child-wf",
                "input_text": "hello",
            })

        assert result == json.dumps(child_output, default=str)

    def test_tool_returns_string_passthrough_when_interrupt_returns_string(self):
        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tool = spawn_and_await_factory(node)[0]

        with patch("langgraph.types.interrupt", return_value="child completed"):
            result = tool.invoke({
                "workflow_slug": "child-wf",
                "input_text": "hello",
            })

        assert result == "child completed"


# ---------------------------------------------------------------------------
# _create_child_from_interrupt edge cases (agent.py)
# ---------------------------------------------------------------------------


class TestCreateChildEdgeCases:
    """Cover uncovered branches in _create_child_from_interrupt."""

    def test_user_profile_id_fallback_from_parent_execution(
        self, mock_session, workflow, user_profile
    ):
        """When user_context has no user_profile_id, fall back to the parent execution's user_profile_id."""
        from components.agent import _create_child_from_interrupt
        from models.workflow import Workflow

        target_wf = Workflow(
            name="Target", slug="target-wf", owner_id=user_profile.id, is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()

        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        # user_context has NO user_profile_id — should fall back to parent exec
        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {},
        }
        interrupt_data = {
            "workflow_slug": "target-wf",
            "input_text": "test fallback",
            "task_id": None,
            "input_data": {},
        }

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            child_id = _create_child_from_interrupt(interrupt_data, state, "agent_1")

        child_exec = (
            mock_session.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == child_id)
            .first()
        )
        assert child_exec is not None
        assert child_exec.user_profile_id == user_profile.id

    def test_raises_when_no_user_profile_id(self, mock_session, workflow, user_profile):
        """Raises ValueError when user_profile_id cannot be determined at all."""
        from components.agent import _create_child_from_interrupt
        from models.workflow import Workflow

        target_wf = Workflow(
            name="Target", slug="target-wf2", owner_id=user_profile.id, is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()

        # No user_profile_id in context, no parent execution to fall back to
        state = {
            "execution_id": "nonexistent-exec-id",
            "user_context": {},
        }
        interrupt_data = {
            "workflow_slug": "target-wf2",
            "input_text": "test",
            "task_id": None,
            "input_data": {},
        }

        with pytest.raises(ValueError, match="cannot determine user_profile_id"):
            _create_child_from_interrupt(interrupt_data, state, "agent_1")

    def test_task_linkage_exception_swallowed(
        self, mock_session, workflow, user_profile
    ):
        """When task linkage fails, the exception is logged but not raised."""
        from components.agent import _create_child_from_interrupt
        from models.workflow import Workflow

        target_wf = Workflow(
            name="Target", slug="target-wf3", owner_id=user_profile.id, is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()

        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
        }
        interrupt_data = {
            "workflow_slug": "target-wf3",
            "input_text": "test",
            "task_id": "tk-fake123",
            "input_data": {},
        }

        # Patch Task query inside the linkage try/except to raise
        original_query = mock_session.query
        call_count = {"task_queries": 0}

        def patched_query(model):
            from models.epic import Task as TaskModel
            if model is TaskModel:
                call_count["task_queries"] += 1
                raise RuntimeError("DB error during task linkage")
            return original_query(model)

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            # Temporarily replace mock_session.query so that the Task query
            # inside the linkage block raises, while other queries still work.
            # We swap it in only after the child execution is committed.
            original_commit = mock_session.commit
            commit_calls = {"count": 0}

            def commit_then_patch():
                commit_calls["count"] += 1
                original_commit()
                # After the child execution is committed (2nd commit inside the function),
                # swap in the patched query for the task linkage block
                if commit_calls["count"] == 1:
                    mock_session.query = patched_query

            mock_session.commit = commit_then_patch
            try:
                child_id = _create_child_from_interrupt(interrupt_data, state, "agent_1")
            finally:
                mock_session.commit = original_commit
                mock_session.query = original_query

        # Should succeed despite task linkage exception — child was still created
        assert child_id is not None
        assert call_count["task_queries"] == 1


# ---------------------------------------------------------------------------
# _sync_task_costs edge cases (orchestrator.py)
# ---------------------------------------------------------------------------


class TestSyncTaskCostsEdgeCases:
    """Cover uncovered branches in _sync_task_costs."""

    def test_no_op_when_execution_not_found(self, mock_session, workflow, user_profile):
        """Early return when execution_id has a linked task but no matching execution."""
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="E", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(
            epic_id=epic.id,
            title="T",
            status="running",
            execution_id="orphan-exec-id",
        )
        mock_session.add(task)
        mock_session.commit()

        # Call with the task's execution_id, but no WorkflowExecution row exists
        _sync_task_costs("orphan-exec-id", mock_session)

        mock_session.refresh(task)
        assert task.status == "running"  # unchanged

    def test_task_committed_when_epic_sync_raises(
        self, mock_session, workflow, user_profile
    ):
        """Task status is persisted even if sync_epic_progress raises."""
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="E", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(epic_id=epic.id, title="T", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        task.execution_id = str(execution.execution_id)
        mock_session.commit()

        with patch(
            "api.epic_helpers.sync_epic_progress",
            side_effect=RuntimeError("boom"),
        ):
            _sync_task_costs(str(execution.execution_id), mock_session)

        mock_session.refresh(task)
        # Task status should still be committed despite epic sync failure
        assert task.status == "completed"
        assert task.duration_ms == 2000

    def test_no_epic_sync_when_task_has_no_epic(
        self, mock_session, workflow, user_profile
    ):
        """When task.epic is falsy, sync_epic_progress is not called."""
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="Placeholder", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        # task.epic will be patched to None later
        task = Task(epic_id=epic.id, title="Orphan Task", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 4, tzinfo=timezone.utc),
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        task.execution_id = str(execution.execution_id)
        mock_session.commit()

        with patch(
            "api.epic_helpers.sync_epic_progress",
        ) as mock_sync:
            # Override the epic relationship at class level so task.epic is None
            with patch.object(Task, "epic", None):
                _sync_task_costs(str(execution.execution_id), mock_session)

        mock_sync.assert_not_called()

        mock_session.refresh(task)
        assert task.status == "completed"
        assert task.duration_ms == 4000


# ---------------------------------------------------------------------------
# Redis checkpointer singleton (agent.py lines 23-24, 46-57)
# ---------------------------------------------------------------------------


class TestRedisCheckpointer:
    """Test _get_redis_checkpointer() creates and caches a RedisSaver singleton."""

    def test_creates_and_caches_redis_saver(self):
        import sys
        import components.agent as agent_mod
        from components.agent import _get_redis_checkpointer

        original = agent_mod._redis_checkpointer
        agent_mod._redis_checkpointer = None
        try:
            mock_saver_instance = MagicMock()
            mock_saver_cls = MagicMock(return_value=mock_saver_instance)
            mock_redis_module = MagicMock(RedisSaver=mock_saver_cls)

            with patch.dict(sys.modules, {"langgraph.checkpoint.redis": mock_redis_module}), \
                 patch("config.settings") as mock_settings:
                mock_settings.REDIS_URL = "redis://test:6379/0"

                first = _get_redis_checkpointer()
                second = _get_redis_checkpointer()

                assert first is second
                mock_saver_cls.assert_called_once_with(redis_url="redis://test:6379/0")
                mock_saver_instance.setup.assert_called_once()
        finally:
            agent_mod._redis_checkpointer = original


# ---------------------------------------------------------------------------
# Agent node: spawn resume / interrupt flow (agent.py lines 91, 99-100,
# 116-117, 140, 150-154, 157-161, 167-176)
# ---------------------------------------------------------------------------


class TestAgentNodeSpawnResume:
    """Test resume-from-child-result path through agent_node()."""

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_react_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_resume_from_child_result(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        from components.agent import agent_factory

        # Mock LLM
        mock_resolve_llm.return_value = MagicMock()

        # Mock tools list with a spawn_and_await tool
        mock_spawn_tool = MagicMock()
        mock_spawn_tool.name = "spawn_and_await"
        mock_resolve_tools.return_value = [mock_spawn_tool]

        # Mock redis checkpointer
        mock_checkpointer = MagicMock()
        mock_get_redis.return_value = mock_checkpointer

        # Mock agent
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="resumed output", additional_kwargs={})],
        }
        mock_create_agent.return_value = mock_agent

        # Build the agent_node closure
        node = _make_node("agent", workflow_id=1, node_id="test_node_1")
        agent_node = agent_factory(node)

        # Verify create_react_agent was called with checkpointer
        create_kwargs = mock_create_agent.call_args
        assert create_kwargs.kwargs.get("checkpointer") is mock_checkpointer

        # Invoke with _subworkflow_results present (resume path)
        state = {
            "messages": [],
            "execution_id": "exec-123",
            "_subworkflow_results": {
                "test_node_1": {"result": "child output"},
            },
        }
        result = agent_node(state)

        # Verify agent.invoke was called with Command(resume=...) and ephemeral thread config
        invoke_args = mock_agent.invoke.call_args
        command_arg = invoke_args[0][0]
        # Check it's a Command with resume data
        from langgraph.types import Command
        assert isinstance(command_arg, Command)
        assert command_arg.resume == {"result": "child output"}

        # Check ephemeral thread config
        config_arg = invoke_args[1].get("config") or invoke_args[0][1]
        assert config_arg == {"configurable": {"thread_id": "exec:exec-123:test_node_1"}}

        # Verify output
        assert "output" in result


class TestAgentNodeGraphInterrupt:
    """Test GraphInterrupt handling in agent_node()."""

    def _setup_agent(self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm):
        """Shared setup for interrupt tests — returns (agent_node, mock_agent)."""
        from components.agent import agent_factory

        mock_resolve_llm.return_value = MagicMock()

        mock_spawn_tool = MagicMock()
        mock_spawn_tool.name = "spawn_and_await"
        mock_resolve_tools.return_value = [mock_spawn_tool]

        mock_checkpointer = MagicMock()
        mock_get_redis.return_value = mock_checkpointer

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent

        node = _make_node("agent", workflow_id=1, node_id="test_node_1")
        agent_node = agent_factory(node)
        return agent_node, mock_agent

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_react_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_graph_interrupt_creates_child(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        from langgraph.errors import GraphInterrupt

        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        # Make agent.invoke raise GraphInterrupt with .interrupts attribute
        interrupt_value = {
            "action": "spawn_workflow",
            "workflow_slug": "child-wf",
            "input_text": "do something",
            "task_id": None,
            "input_data": {},
        }
        interrupt_obj = MagicMock()
        interrupt_obj.value = interrupt_value

        # GraphInterrupt stores interrupts in args[0]; the agent code accesses
        # exc.interrupts, so we create the exception and attach the attribute.
        exc = GraphInterrupt([interrupt_obj])
        exc.interrupts = [interrupt_obj]
        mock_agent.invoke.side_effect = exc

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-789",
        }

        with patch("components.agent._create_child_from_interrupt", return_value="child-exec-456") as mock_create_child:
            result = agent_node(state)

        assert result == {"_subworkflow": {"child_execution_id": "child-exec-456"}}
        mock_create_child.assert_called_once_with(interrupt_value, state, "test_node_1")

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_react_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_interrupt_in_return_value_creates_child(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        """When checkpointer is present, invoke() returns __interrupt__ instead of raising."""
        from langgraph.types import Interrupt

        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        interrupt_value = {
            "action": "spawn_workflow",
            "workflow_slug": "child-wf",
            "input_text": "do something",
            "task_id": None,
            "input_data": {},
        }
        interrupt_obj = Interrupt(value=interrupt_value)

        # invoke() returns dict with __interrupt__ key (checkpointer present)
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="partial", additional_kwargs={})],
            "__interrupt__": (interrupt_obj,),
        }

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-789",
        }

        with patch("components.agent._create_child_from_interrupt", return_value="child-456") as mock_create:
            result = agent_node(state)

        assert result == {"_subworkflow": {"child_execution_id": "child-456"}}
        mock_create.assert_called_once_with(interrupt_value, state, "test_node_1")

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_react_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_interrupt_in_return_value_ignored_without_spawn_action(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        """__interrupt__ with non-spawn action (e.g. human_confirmation) is not intercepted."""
        from langgraph.types import Interrupt

        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        interrupt_obj = Interrupt(value={"action": "human_confirmation", "message": "approve?"})

        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="waiting", additional_kwargs={})],
            "__interrupt__": (interrupt_obj,),
        }

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-100",
        }

        result = agent_node(state)

        # Should NOT create a child — falls through to normal output extraction
        assert "output" in result
        assert result["output"] == "waiting"

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_react_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_non_interrupt_exception_reraises(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        mock_agent.invoke.side_effect = RuntimeError("LLM error")

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-999",
        }

        with pytest.raises(RuntimeError, match="LLM error"):
            agent_node(state)

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_react_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_interrupt_child_creation_error_returns_output(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        """When _create_child_from_interrupt fails, return error output instead of raising."""
        from langgraph.types import Interrupt

        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        interrupt_value = {
            "action": "spawn_workflow",
            "workflow_slug": "nonexistent",
            "input_text": "test",
            "task_id": None,
            "input_data": {},
        }
        interrupt_obj = Interrupt(value=interrupt_value)

        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="partial", additional_kwargs={})],
            "__interrupt__": (interrupt_obj,),
        }

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-err",
        }

        with patch(
            "components.agent._create_child_from_interrupt",
            side_effect=ValueError("target workflow not found"),
        ):
            result = agent_node(state)

        # Should return error output, NOT raise
        assert "output" in result
        assert "spawn_and_await failed" in result["output"]
        assert "target workflow not found" in result["output"]
