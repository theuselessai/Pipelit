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

    def test_factory_raises_on_missing_workflow(self, mock_session):
        from components.epic_tools import epic_tools_factory

        node = _make_node("epic_tools", workflow_id=99999)
        with pytest.raises(ValueError, match="workflow 99999 not found"):
            epic_tools_factory(node)

    def test_factory_raises_on_null_owner_id(self, mock_session, workflow):
        from components.epic_tools import epic_tools_factory

        fake_workflow = SimpleNamespace(owner_id=None)
        node = _make_node("epic_tools", workflow.id)
        with patch("database.SessionLocal") as mock_sl:
            mock_db = mock_sl.return_value
            mock_db.query.return_value.filter.return_value.first.return_value = fake_workflow
            mock_db.close = lambda: None
            with pytest.raises(ValueError, match="has no owner_id"):
                epic_tools_factory(node)


class TestCreateEpic:
    def test_create_epic_priority_out_of_range(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_epic")
        # priority too low
        result = json.loads(create_tool.invoke({
            "title": "Bad Priority",
            "priority": 0,
        }))
        assert result["success"] is False
        assert "Priority must be between 1 and 5" in result["error"]

        # priority too high
        result = json.loads(create_tool.invoke({
            "title": "Bad Priority",
            "priority": 6,
        }))
        assert result["success"] is False
        assert "Priority must be between 1 and 5" in result["error"]

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


class TestUpdateEpicAllFields:
    def test_update_all_optional_fields(self, mock_session, workflow, user_profile):
        """Cover description, budget_tokens, budget_usd, result_summary branches."""
        from components.epic_tools import epic_tools_factory

        epic = Epic(title="Full Update", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_epic")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(update_tool.invoke({
                "epic_id": epic.id,
                "description": "New desc",
                "budget_tokens": 5000,
                "budget_usd": 1.50,
                "result_summary": "Done well",
            }))

        assert result["success"] is True
        mock_session.refresh(epic)
        assert epic.description == "New desc"
        assert epic.budget_tokens == 5000
        assert float(epic.budget_usd) == 1.50
        assert epic.result_summary == "Done well"

    def test_update_epic_priority_out_of_range(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        epic = Epic(title="Priority Update", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_epic")
        result = json.loads(update_tool.invoke({
            "epic_id": epic.id,
            "priority": 0,
        }))
        assert result["success"] is False
        assert "Priority must be between 1 and 5" in result["error"]

    def test_update_epic_invalid_status(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        epic = Epic(title="Status Update", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_epic")
        result = json.loads(update_tool.invoke({
            "epic_id": epic.id,
            "status": "bogus",
        }))
        assert result["success"] is False
        assert "Invalid status" in result["error"]

    def test_update_epic_not_found(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_epic")
        result = json.loads(update_tool.invoke({
            "epic_id": "ep-nonexistent",
            "title": "X",
        }))

        assert result["success"] is False
        assert "not found" in result["error"]


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

    def test_search_includes_zero_cost_in_avg(self, mock_session, workflow, user_profile):
        """Verify epics with $0.00 spent_usd are included in avg_cost."""
        from components.epic_tools import epic_tools_factory

        e1 = Epic(title="Free", user_profile_id=user_profile.id, spent_usd=0.0)
        e2 = Epic(title="Paid", user_profile_id=user_profile.id, spent_usd=2.0)
        mock_session.add_all([e1, e2])
        mock_session.commit()

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        search_tool = next(t for t in tools if t.name == "search_epics")
        result = json.loads(search_tool.invoke({}))

        assert result["success"] is True
        # avg_cost should be (0.0 + 2.0) / 2 = 1.0, not 2.0/1 = 2.0
        assert result["avg_cost"] == 1.0

    def test_search_clamps_limit(self, mock_session, workflow, user_profile):
        """Verify limit is clamped to [1, 100]."""
        from components.epic_tools import epic_tools_factory

        mock_session.add(Epic(title="One", user_profile_id=user_profile.id))
        mock_session.commit()

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        search_tool = next(t for t in tools if t.name == "search_epics")
        # Huge limit should still work (clamped to 100)
        result = json.loads(search_tool.invoke({"limit": 999999}))
        assert result["success"] is True

    def test_search_by_status_and_tags(self, mock_session, workflow, user_profile):
        """Cover status filter and tag filter branches in search_epics."""
        from components.epic_tools import epic_tools_factory

        e1 = Epic(title="Active One", user_profile_id=user_profile.id, status="active", tags=["deploy"])
        e2 = Epic(title="Active Two", user_profile_id=user_profile.id, status="active", tags=["test"])
        e3 = Epic(title="Done", user_profile_id=user_profile.id, status="completed", tags=["deploy"])
        mock_session.add_all([e1, e2, e3])
        mock_session.commit()

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        search_tool = next(t for t in tools if t.name == "search_epics")
        result = json.loads(search_tool.invoke({"status": "active", "tags": "deploy"}))

        assert result["success"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Active One"

    def test_search_too_many_tags(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        search_tool = next(t for t in tools if t.name == "search_epics")
        many_tags = ",".join(f"tag{i}" for i in range(21))
        result = json.loads(search_tool.invoke({"tags": many_tags}))

        assert result["success"] is False
        assert "Maximum is 20" in result["error"]


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

    def test_factory_raises_on_missing_workflow(self, mock_session):
        from components.task_tools import task_tools_factory

        node = _make_node("task_tools", workflow_id=99999)
        with pytest.raises(ValueError, match="workflow 99999 not found"):
            task_tools_factory(node)

    def test_factory_raises_on_null_owner_id(self, mock_session, workflow):
        from components.task_tools import task_tools_factory

        fake_workflow = SimpleNamespace(owner_id=None)
        node = _make_node("task_tools", workflow.id)
        with patch("database.SessionLocal") as mock_sl:
            mock_db = mock_sl.return_value
            mock_db.query.return_value.filter.return_value.first.return_value = fake_workflow
            mock_db.close = lambda: None
            with pytest.raises(ValueError, match="has no owner_id"):
                task_tools_factory(node)


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

    def test_create_task_priority_out_of_range(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Priority Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_task")
        # priority too low
        result = json.loads(create_tool.invoke({
            "epic_id": epic.id,
            "title": "Bad Priority",
            "priority": 0,
        }))
        assert result["success"] is False
        assert "Priority must be between 1 and 5" in result["error"]

        # priority too high
        result = json.loads(create_tool.invoke({
            "epic_id": epic.id,
            "title": "Bad Priority",
            "priority": 6,
        }))
        assert result["success"] is False
        assert "Priority must be between 1 and 5" in result["error"]

    def test_create_task_nonexistent_dependency(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Dep Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_task")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(create_tool.invoke({
                "epic_id": epic.id,
                "title": "Bad Deps",
                "depends_on": "tk-nonexistent",
            }))

        assert result["success"] is False
        assert "dependencies do not exist" in result["error"]

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

    def test_list_tasks_filter_tags(self, mock_session, workflow, user_profile):
        """Cover tags filter branch in list_tasks."""
        from components.task_tools import task_tools_factory

        epic = Epic(title="Tag Filter Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        mock_session.add_all([
            Task(epic_id=epic.id, title="Tagged", status="pending", tags=["api"]),
            Task(epic_id=epic.id, title="Untagged", status="pending", tags=["ui"]),
        ])
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        list_tool = next(t for t in tools if t.name == "list_tasks")
        result = json.loads(list_tool.invoke({"epic_id": epic.id, "tags": "api"}))

        assert result["success"] is True
        assert result["total"] == 1
        assert result["tasks"][0]["title"] == "Tagged"

    def test_list_tasks_clamps_limit(self, mock_session, workflow, user_profile):
        """Verify limit is clamped to [1, 100]."""
        from components.task_tools import task_tools_factory

        epic = Epic(title="Limit Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        mock_session.add(Task(epic_id=epic.id, title="T1", status="pending"))
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        list_tool = next(t for t in tools if t.name == "list_tasks")
        result = json.loads(list_tool.invoke({"epic_id": epic.id, "limit": 999999}))
        assert result["success"] is True
        assert result["total"] == 1

    def test_list_tasks_too_many_tags(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Tag Cap Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        list_tool = next(t for t in tools if t.name == "list_tasks")
        many_tags = ",".join(f"tag{i}" for i in range(21))
        result = json.loads(list_tool.invoke({"epic_id": epic.id, "tags": many_tags}))

        assert result["success"] is False
        assert "Maximum is 20" in result["error"]

    def test_list_tasks_epic_not_found(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        list_tool = next(t for t in tools if t.name == "list_tasks")
        result = json.loads(list_tool.invoke({"epic_id": "ep-nonexistent"}))

        assert result["success"] is False
        assert "not found" in result["error"]


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

    def test_update_task_all_optional_fields(self, mock_session, workflow, user_profile):
        """Cover description, priority, result_summary, error_message branches."""
        from components.task_tools import task_tools_factory

        epic = Epic(title="All Fields", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        task = Task(epic_id=epic.id, title="Full Update", status="pending")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_task")
        with patch("ws.broadcast.broadcast"):
            result = json.loads(update_tool.invoke({
                "task_id": task.id,
                "description": "New desc",
                "priority": 1,
                "result_summary": "Great work",
                "error_message": "Minor issue",
                "status": "completed",
            }))

        assert result["success"] is True
        mock_session.refresh(task)
        assert task.description == "New desc"
        assert task.priority == 1
        assert task.result_summary == "Great work"
        assert task.error_message == "Minor issue"
        assert task.status == "completed"

    def test_update_task_priority_out_of_range(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Priority Update", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        task = Task(epic_id=epic.id, title="PrioTask", status="pending")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_task")
        result = json.loads(update_tool.invoke({
            "task_id": task.id,
            "priority": 0,
        }))
        assert result["success"] is False
        assert "Priority must be between 1 and 5" in result["error"]

        result = json.loads(update_tool.invoke({
            "task_id": task.id,
            "priority": 10,
        }))
        assert result["success"] is False
        assert "Priority must be between 1 and 5" in result["error"]

    def test_update_task_invalid_status(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Status Update", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        task = Task(epic_id=epic.id, title="StatusTask", status="pending")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_task")
        result = json.loads(update_tool.invoke({
            "task_id": task.id,
            "status": "bogus",
        }))
        assert result["success"] is False
        assert "Invalid status" in result["error"]

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

    def test_cancel_task_not_found(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        cancel_tool = next(t for t in tools if t.name == "cancel_task")
        result = json.loads(cancel_tool.invoke({"task_id": "tk-nonexistent"}))

        assert result["success"] is False
        assert "not found" in result["error"]

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

    def test_resolve_tools_single_tool_factory(self, mock_session, workflow):
        """Cover the else branch (L176-177) — single tool from factory."""
        from components.agent import _resolve_tools
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        agent_config = BaseComponentConfig(component_type="agent", system_prompt="test")
        mock_session.add(agent_config)
        mock_session.flush()
        agent_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="agent_single",
            component_type="agent",
            component_config_id=agent_config.id,
        )
        mock_session.add(agent_node)

        # calculator returns a single tool (not a list)
        tool_config = BaseComponentConfig(component_type="calculator")
        mock_session.add(tool_config)
        mock_session.flush()
        tool_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="calc_1",
            component_type="calculator",
            component_config_id=tool_config.id,
        )
        mock_session.add(tool_node)

        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id="calc_1",
            target_node_id="agent_single",
            edge_label="tool",
        )
        mock_session.add(edge)
        mock_session.commit()
        mock_session.refresh(agent_node)

        tools = _resolve_tools(agent_node)

        assert len(tools) == 1
        assert tools[0].name == "calculator"

    def test_resolve_tools_exception_returns_empty(self, db, workflow):
        """Cover the except branch in _resolve_tools (L176-177)."""
        from components.agent import _resolve_tools
        from models.node import BaseComponentConfig, WorkflowNode

        agent_config = BaseComponentConfig(component_type="agent", system_prompt="test")
        db.add(agent_config)
        db.flush()
        agent_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="agent_err",
            component_type="agent",
            component_config_id=agent_config.id,
        )
        db.add(agent_node)
        db.commit()
        db.refresh(agent_node)

        # Force an exception by making SessionLocal raise
        with patch("database.SessionLocal", side_effect=RuntimeError("DB down")):
            tools = _resolve_tools(agent_node)

        assert tools == []


# ---------------------------------------------------------------------------
# Broadcast exception handling (catch-and-log branches)
# ---------------------------------------------------------------------------

class TestBroadcastExceptions:
    """Cover the except branches where broadcast fails but tool returns success."""

    def test_create_epic_broadcast_failure(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_epic")
        with patch("ws.broadcast.broadcast", side_effect=RuntimeError("Redis down")):
            result = json.loads(create_tool.invoke({"title": "Broadcast Fail"}))

        # Tool should still succeed despite broadcast failure
        assert result["success"] is True

    def test_update_epic_broadcast_failure(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        epic = Epic(title="Bcast Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_epic")
        with patch("ws.broadcast.broadcast", side_effect=RuntimeError("Redis down")):
            result = json.loads(update_tool.invoke({"epic_id": epic.id, "status": "active"}))

        assert result["success"] is True

    def test_create_task_broadcast_failure(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Task Bcast", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_task")
        with patch("ws.broadcast.broadcast", side_effect=RuntimeError("Redis down")):
            result = json.loads(create_tool.invoke({"epic_id": epic.id, "title": "Bcast fail"}))

        assert result["success"] is True

    def test_update_task_broadcast_failure(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Update Bcast", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        task = Task(epic_id=epic.id, title="Bcast", status="pending")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_task")
        with patch("ws.broadcast.broadcast", side_effect=RuntimeError("Redis down")):
            result = json.loads(update_tool.invoke({"task_id": task.id, "status": "running"}))

        assert result["success"] is True

    def test_cancel_task_broadcast_failure(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Cancel Bcast", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.flush()
        task = Task(epic_id=epic.id, title="Bcast Cancel", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        cancel_tool = next(t for t in tools if t.name == "cancel_task")
        with patch("ws.broadcast.broadcast", side_effect=RuntimeError("Redis down")):
            result = json.loads(cancel_tool.invoke({"task_id": task.id}))

        assert result["success"] is True


# ---------------------------------------------------------------------------
# DB error handling (outer except branches with rollback)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Post-commit refresh failure (verify success despite refresh error)
# ---------------------------------------------------------------------------

class TestPostCommitRefreshFailure:
    """Verify that a failing db.refresh() after successful commit still returns success."""

    def test_create_epic_refresh_failure(self, mock_session, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        node = _make_node("epic_tools", workflow.id)
        tools = epic_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_epic")
        original_refresh = mock_session.refresh

        def broken_refresh(obj):
            raise RuntimeError("refresh exploded")

        mock_session.refresh = broken_refresh
        try:
            with patch("ws.broadcast.broadcast"):
                result = json.loads(create_tool.invoke({"title": "Refresh Fail Epic"}))
        finally:
            mock_session.refresh = original_refresh

        assert result["success"] is True
        assert result["epic_id"].startswith("ep-")

    def test_create_task_refresh_failure(self, mock_session, workflow, user_profile):
        from components.task_tools import task_tools_factory

        epic = Epic(title="Refresh Test", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()

        node = _make_node("task_tools", workflow.id)
        tools = task_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_task")
        original_refresh = mock_session.refresh

        def broken_refresh(obj):
            raise RuntimeError("refresh exploded")

        mock_session.refresh = broken_refresh
        try:
            with patch("ws.broadcast.broadcast"):
                result = json.loads(create_tool.invoke({
                    "epic_id": epic.id,
                    "title": "Refresh Fail Task",
                }))
        finally:
            mock_session.refresh = original_refresh

        assert result["success"] is True
        assert result["task_id"].startswith("tk-")


# ---------------------------------------------------------------------------
# Component type mapping correctness
# ---------------------------------------------------------------------------

class TestComponentTypeMapping:
    """Verify COMPONENT_TYPE_TO_CONFIG uses the correct config classes."""

    def test_epic_tools_maps_to_epic_tools_config(self):
        from models.node import COMPONENT_TYPE_TO_CONFIG, _EpicToolsConfig

        assert COMPONENT_TYPE_TO_CONFIG["epic_tools"] is _EpicToolsConfig

    def test_task_tools_maps_to_task_tools_config(self):
        from models.node import COMPONENT_TYPE_TO_CONFIG, _TaskToolsConfig

        assert COMPONENT_TYPE_TO_CONFIG["task_tools"] is _TaskToolsConfig


class TestDBErrorBranches:
    """Cover except Exception: db.rollback() branches by forcing DB errors."""

    def _make_broken_session(self, db, original_close):
        """Patch db to raise on commit. Returns (db, original_commit)."""
        original_commit = db.commit
        original_rollback = db.rollback

        db.close = lambda: None
        db.commit = lambda: (_ for _ in ()).throw(RuntimeError("DB commit failed"))
        db.rollback = lambda: None
        return db, original_commit, original_rollback, original_close

    def _restore_session(self, db, original_commit, original_rollback, original_close):
        db.commit = original_commit
        db.rollback = original_rollback
        db.close = original_close

    def test_create_epic_db_error(self, db, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        original_close = db.close

        node = _make_node("epic_tools", workflow.id)
        with patch("database.SessionLocal", return_value=db):
            db.close = lambda: None
            tools = epic_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_epic")

        broken_db, orig_commit, orig_rb, orig_close = self._make_broken_session(db, original_close)
        with patch("database.SessionLocal", return_value=broken_db):
            result = json.loads(create_tool.invoke({"title": "Will fail"}))

        self._restore_session(db, orig_commit, orig_rb, orig_close)
        assert result["success"] is False
        assert "error" in result

    def test_epic_status_db_error(self, db, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        original_close = db.close

        node = _make_node("epic_tools", workflow.id)
        with patch("database.SessionLocal", return_value=db):
            db.close = lambda: None
            tools = epic_tools_factory(node)

        status_tool = next(t for t in tools if t.name == "epic_status")

        with patch("database.SessionLocal") as mock_sl:
            mock_db = mock_sl.return_value
            mock_db.query.side_effect = RuntimeError("DB query failed")
            mock_db.close = lambda: None
            result = json.loads(status_tool.invoke({"epic_id": "ep-x"}))

        db.close = original_close
        assert result["success"] is False
        assert "error" in result

    def test_update_epic_db_error(self, db, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        original_close = db.close

        epic = Epic(title="Will Error", user_profile_id=user_profile.id)
        db.add(epic)
        db.commit()
        db.refresh(epic)

        node = _make_node("epic_tools", workflow.id)
        with patch("database.SessionLocal", return_value=db):
            db.close = lambda: None
            tools = epic_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_epic")

        broken_db, orig_commit, orig_rb, orig_close = self._make_broken_session(db, original_close)
        with patch("database.SessionLocal", return_value=broken_db):
            result = json.loads(update_tool.invoke({"epic_id": epic.id, "title": "New"}))

        self._restore_session(db, orig_commit, orig_rb, orig_close)
        assert result["success"] is False
        assert "error" in result

    def test_search_epics_db_error(self, db, workflow, user_profile):
        from components.epic_tools import epic_tools_factory

        original_close = db.close

        node = _make_node("epic_tools", workflow.id)
        with patch("database.SessionLocal", return_value=db):
            db.close = lambda: None
            tools = epic_tools_factory(node)

        search_tool = next(t for t in tools if t.name == "search_epics")

        with patch("database.SessionLocal") as mock_sl:
            mock_db = mock_sl.return_value
            mock_db.query.side_effect = RuntimeError("DB error")
            mock_db.close = lambda: None
            result = json.loads(search_tool.invoke({}))

        db.close = original_close
        assert result["success"] is False
        assert "error" in result

    def test_create_task_db_error(self, db, workflow, user_profile):
        from components.task_tools import task_tools_factory

        original_close = db.close

        epic = Epic(title="Task Error", user_profile_id=user_profile.id)
        db.add(epic)
        db.commit()
        db.refresh(epic)

        node = _make_node("task_tools", workflow.id)
        with patch("database.SessionLocal", return_value=db):
            db.close = lambda: None
            tools = task_tools_factory(node)

        create_tool = next(t for t in tools if t.name == "create_task")

        broken_db, orig_commit, orig_rb, orig_close = self._make_broken_session(db, original_close)
        with patch("database.SessionLocal", return_value=broken_db):
            result = json.loads(create_tool.invoke({"epic_id": epic.id, "title": "Fail"}))

        self._restore_session(db, orig_commit, orig_rb, orig_close)
        assert result["success"] is False
        assert "error" in result

    def test_list_tasks_db_error(self, db, workflow, user_profile):
        from components.task_tools import task_tools_factory

        original_close = db.close

        node = _make_node("task_tools", workflow.id)
        with patch("database.SessionLocal", return_value=db):
            db.close = lambda: None
            tools = task_tools_factory(node)

        list_tool = next(t for t in tools if t.name == "list_tasks")

        with patch("database.SessionLocal") as mock_sl:
            mock_db = mock_sl.return_value
            mock_db.query.side_effect = RuntimeError("DB error")
            mock_db.close = lambda: None
            result = json.loads(list_tool.invoke({"epic_id": "ep-x"}))

        db.close = original_close
        assert result["success"] is False
        assert "error" in result

    def test_update_task_db_error(self, db, workflow, user_profile):
        from components.task_tools import task_tools_factory

        original_close = db.close

        epic = Epic(title="UTask Error", user_profile_id=user_profile.id)
        db.add(epic)
        db.flush()
        task = Task(epic_id=epic.id, title="Will Error", status="pending")
        db.add(task)
        db.commit()
        db.refresh(task)

        node = _make_node("task_tools", workflow.id)
        with patch("database.SessionLocal", return_value=db):
            db.close = lambda: None
            tools = task_tools_factory(node)

        update_tool = next(t for t in tools if t.name == "update_task")

        broken_db, orig_commit, orig_rb, orig_close = self._make_broken_session(db, original_close)
        with patch("database.SessionLocal", return_value=broken_db):
            result = json.loads(update_tool.invoke({"task_id": task.id, "status": "running"}))

        self._restore_session(db, orig_commit, orig_rb, orig_close)
        assert result["success"] is False
        assert "error" in result

    def test_cancel_task_db_error(self, db, workflow, user_profile):
        from components.task_tools import task_tools_factory

        original_close = db.close

        epic = Epic(title="CTask Error", user_profile_id=user_profile.id)
        db.add(epic)
        db.flush()
        task = Task(epic_id=epic.id, title="Will Error", status="running")
        db.add(task)
        db.commit()
        db.refresh(task)

        node = _make_node("task_tools", workflow.id)
        with patch("database.SessionLocal", return_value=db):
            db.close = lambda: None
            tools = task_tools_factory(node)

        cancel_tool = next(t for t in tools if t.name == "cancel_task")

        broken_db, orig_commit, orig_rb, orig_close = self._make_broken_session(db, original_close)
        with patch("database.SessionLocal", return_value=broken_db):
            result = json.loads(cancel_tool.invoke({"task_id": task.id}))

        self._restore_session(db, orig_commit, orig_rb, orig_close)
        assert result["success"] is False
        assert "error" in result
