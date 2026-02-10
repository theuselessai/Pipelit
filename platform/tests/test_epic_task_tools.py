"""Tests for epic_tools and task_tools component factories."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from models.epic import Epic, Task


def _make_node(component_type, workflow_id, node_id="tool_node_1"):
    config = SimpleNamespace(
        component_type=component_type,
        extra_config={},
        system_prompt="",
    )
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
# Epic tools
# ---------------------------------------------------------------------------

class TestEpicToolsFactory:
    def test_returns_list_of_four_tools(self, mock_session, workflow):
        from components.epic_tools import epic_tools_factory

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        assert isinstance(tools, list)
        assert len(tools) == 4
        names = {t.name for t in tools}
        assert names == {"create_epic", "epic_status", "update_epic", "search_epics"}


class TestCreateEpic:
    def test_create_epic_success(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_epic")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(create_tool.invoke({
                "title": "My Epic",
                "description": "Test desc",
                "tags": "backend,urgent",
                "priority": 1,
            }))

        assert result["success"] is True
        assert result["title"] == "My Epic"
        assert result["status"] == "planning"
        assert result["epic_id"].startswith("ep-")

        # Verify in DB
        epic = mock_session.query(Epic).filter(Epic.id == result["epic_id"]).first()
        assert epic is not None
        assert epic.tags == ["backend", "urgent"]
        assert epic.user_profile_id == user_profile.id
        assert epic.created_by_node_id == "tool_node_1"


class TestEpicStatus:
    def test_epic_status_success(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        epic = Epic(title="Status Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        t1 = Task(epic_id=epic.id, title="Task 1", status="completed")
        t2 = Task(epic_id=epic.id, title="Task 2", status="pending")
        mock_session.add_all([t1, t2])
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        status_tool = next(t for t in tools if t.name == "epic_status")
        result = json.loads(status_tool.invoke({"epic_id": epic.id}))

        assert result["success"] is True
        assert result["epic_id"] == epic.id
        assert len(result["tasks"]) == 2

    def test_epic_status_not_found(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        status_tool = next(t for t in tools if t.name == "epic_status")
        result = json.loads(status_tool.invoke({"epic_id": "ep-nonexistent"}))

        assert result["success"] is False
        assert "not found" in result["error"]


class TestUpdateEpic:
    def test_update_epic_fields(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        epic = Epic(title="Original", user_profile_id=user_profile.id, priority=2)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_epic")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(update_tool.invoke({
                "epic_id": epic.id,
                "title": "Updated",
                "priority": 1,
                "status": "active",
            }))

        assert result["success"] is True
        assert result["status"] == "active"
        mock_session.refresh(epic)
        assert epic.title == "Updated"
        assert epic.priority == 1

    def test_cancel_epic_cascades_tasks(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        epic = Epic(title="Cancel Test", user_profile_id=user_profile.id, status="active")
        mock_session.add(epic)
        mock_session.flush()
        t1 = Task(epic_id=epic.id, title="Pending", status="pending")
        t2 = Task(epic_id=epic.id, title="Running", status="running")
        t3 = Task(epic_id=epic.id, title="Completed", status="completed")
        mock_session.add_all([t1, t2, t3])
        mock_session.commit()

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_epic")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(update_tool.invoke({
                "epic_id": epic.id,
                "status": "cancelled",
            }))

        assert result["success"] is True
        mock_session.refresh(t1)
        mock_session.refresh(t2)
        mock_session.refresh(t3)
        assert t1.status == "cancelled"
        assert t2.status == "cancelled"
        assert t3.status == "completed"  # completed tasks stay completed


class TestSearchEpics:
    def test_search_by_text(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        e1 = Epic(title="Deploy backend", user_profile_id=user_profile.id)
        e2 = Epic(title="Fix frontend bug", user_profile_id=user_profile.id)
        mock_session.add_all([e1, e2])
        mock_session.commit()

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        search_tool = next(t for t in tools if t.name == "search_epics")
        result = json.loads(search_tool.invoke({"query": "backend"}))

        assert result["success"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Deploy backend"


# ---------------------------------------------------------------------------
# Task tools
# ---------------------------------------------------------------------------

class TestTaskToolsFactory:
    def test_returns_list_of_four_tools(self, mock_session, workflow):
        from components.task_tools import task_tools_factory

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        assert isinstance(tools, list)
        assert len(tools) == 4
        names = {t.name for t in tools}
        assert names == {"create_task", "list_tasks", "update_task", "cancel_task"}


class TestCreateTask:
    def test_create_task_pending(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_task")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(create_tool.invoke({
                "epic_id": epic.id,
                "title": "My Task",
                "tags": "api,test",
            }))

        assert result["success"] is True
        assert result["status"] == "pending"
        task = mock_session.query(Task).filter(Task.id == result["task_id"]).first()
        assert task is not None
        assert task.tags == ["api", "test"]
        assert task.created_by_node_id == "tool_node_1"

    def test_create_task_blocked_by_deps(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Dep Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        dep_task = Task(epic_id=epic.id, title="Dependency", status="pending")
        mock_session.add(dep_task)
        mock_session.commit()
        mock_session.refresh(dep_task)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_task")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(create_tool.invoke({
                "epic_id": epic.id,
                "title": "Blocked Task",
                "depends_on": dep_task.id,
            }))

        assert result["success"] is True
        assert result["status"] == "blocked"

    def test_create_task_epic_not_found(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_task")
        result = json.loads(create_tool.invoke({
            "epic_id": "ep-nonexistent",
            "title": "Orphan Task",
        }))

        assert result["success"] is False
        assert "not found" in result["error"]


class TestListTasks:
    def test_list_tasks_success(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="List Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        mock_session.add_all([
            Task(epic_id=epic.id, title="Task A", status="pending"),
            Task(epic_id=epic.id, title="Task B", status="completed"),
        ])
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        list_tool = next(t for t in tools if t.name == "list_tasks")
        result = json.loads(list_tool.invoke({"epic_id": epic.id}))

        assert result["success"] is True
        assert result["total"] == 2
        assert len(result["tasks"]) == 2

    def test_list_tasks_filter_status(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Filter Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        mock_session.add_all([
            Task(epic_id=epic.id, title="Pending", status="pending"),
            Task(epic_id=epic.id, title="Done", status="completed"),
        ])
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        list_tool = next(t for t in tools if t.name == "list_tasks")
        result = json.loads(list_tool.invoke({"epic_id": epic.id, "status": "pending"}))

        assert result["total"] == 1
        assert result["tasks"][0]["title"] == "Pending"


class TestUpdateTask:
    def test_update_task_fields(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Update Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        task = Task(epic_id=epic.id, title="Original", status="pending")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_task")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(update_tool.invoke({
                "task_id": task.id,
                "status": "running",
                "title": "Updated",
                "notes": "Started work",
            }))

        assert result["success"] is True
        assert result["status"] == "running"
        mock_session.refresh(task)
        assert task.title == "Updated"
        assert task.notes == ["Started work"]

    def test_update_task_not_found(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_task")
        result = json.loads(update_tool.invoke({
            "task_id": "tk-nonexistent",
            "status": "completed",
        }))

        assert result["success"] is False
        assert "not found" in result["error"]


class TestCancelTask:
    def test_cancel_task_success(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Cancel Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        task = Task(epic_id=epic.id, title="To Cancel", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        cancel_tool = next(t for t in tools if t.name == "cancel_task")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(cancel_tool.invoke({
                "task_id": task.id,
                "reason": "No longer needed",
            }))

        assert result["success"] is True
        mock_session.refresh(task)
        assert task.status == "cancelled"
        assert "Cancelled: No longer needed" in task.notes

    def test_cancel_with_execution(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory
        from models.execution import WorkflowExecution

        epic = Epic(title="Cancel Exec Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            thread_id="test-thread",
            status="running",
        )
        mock_session.add(execution)
        mock_session.flush()

        task = Task(
            epic_id=epic.id,
            title="With Execution",
            status="running",
            execution_id=execution.execution_id,
        )
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        cancel_tool = next(t for t in tools if t.name == "cancel_task")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(cancel_tool.invoke({"task_id": task.id}))

        assert result["success"] is True
        assert result["execution_cancelled"] is True
        mock_session.refresh(execution)
        assert execution.status == "cancelled"


# ---------------------------------------------------------------------------
# Agent list-returning factory support
# ---------------------------------------------------------------------------

class TestAgentListFactorySupport:
    """Test that agent._resolve_tools handles list-returning factories."""

    def test_resolve_tools_list_factory(self, mock_session, workflow):
        from components.agent import _resolve_tools
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        # Create agent node
        agent_config = BaseComponentConfig(component_type="agent", system_prompt="test")
        mock_session.add(agent_config)
        mock_session.flush()
        agent_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="agent_1",
            component_type="agent",
            component_config_id=agent_config.id,
        )
        mock_session.add(agent_node)

        # Create epic_tools node
        tool_config = BaseComponentConfig(component_type="epic_tools")
        mock_session.add(tool_config)
        mock_session.flush()
        tool_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="epic_tools_1",
            component_type="epic_tools",
            component_config_id=tool_config.id,
        )
        mock_session.add(tool_node)

        # Connect them with a tool edge
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id="epic_tools_1",
            target_node_id="agent_1",
            edge_label="tool",
        )
        mock_session.add(edge)
        mock_session.commit()
        mock_session.refresh(agent_node)

        tools = _resolve_tools(agent_node)

        # epic_tools returns 4 tools
        assert len(tools) == 4
        tool_names = {t.name for t in tools}
        assert "create_epic" in tool_names
        assert "epic_status" in tool_names
