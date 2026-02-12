"""Tests for the Epic and Task REST API."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.epic import Epic, Task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app(db):
    from main import app as _app
    from database import get_db

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_client(client, api_key):
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


@pytest.fixture
def epic(db, user_profile):
    e = Epic(
        title="Test Epic",
        description="A test epic",
        tags=["test"],
        user_profile_id=user_profile.id,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


@pytest.fixture
def task(db, epic):
    t = Task(
        epic_id=epic.id,
        title="Test Task",
        description="A test task",
        tags=["backend"],
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ---------------------------------------------------------------------------
# Epic API Tests
# ---------------------------------------------------------------------------

class TestEpicCRUD:
    @patch("api.epics.broadcast")
    def test_create_epic(self, mock_broadcast, auth_client):
        resp = auth_client.post("/api/v1/epics/", json={
            "title": "My Epic",
            "description": "Build something",
            "tags": ["feature"],
            "priority": 1,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Epic"
        assert data["description"] == "Build something"
        assert data["tags"] == ["feature"]
        assert data["priority"] == 1
        assert data["status"] == "planning"
        assert data["id"].startswith("ep-")

    @patch("api.epics.broadcast")
    def test_list_epics(self, mock_broadcast, auth_client, epic):
        resp = auth_client.get("/api/v1/epics/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(e["id"] == epic.id for e in data["items"])

    @patch("api.epics.broadcast")
    def test_list_epics_filter_status(self, mock_broadcast, auth_client, epic):
        resp = auth_client.get("/api/v1/epics/?status=planning")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        resp2 = auth_client.get("/api/v1/epics/?status=completed")
        assert resp2.status_code == 200
        assert resp2.json()["total"] == 0

    @patch("api.epics.broadcast")
    def test_get_epic(self, mock_broadcast, auth_client, epic):
        resp = auth_client.get(f"/api/v1/epics/{epic.id}/")
        assert resp.status_code == 200
        assert resp.json()["id"] == epic.id
        assert resp.json()["title"] == "Test Epic"

    def test_get_epic_not_found(self, auth_client):
        resp = auth_client.get("/api/v1/epics/nonexistent/")
        assert resp.status_code == 404

    @patch("api.epics.broadcast")
    def test_update_epic(self, mock_broadcast, auth_client, epic):
        resp = auth_client.patch(f"/api/v1/epics/{epic.id}/", json={
            "title": "Updated Epic",
            "status": "active",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated Epic"
        assert data["status"] == "active"

    @patch("api.epics.broadcast")
    def test_update_epic_cancel_cascades_tasks(self, mock_broadcast, auth_client, epic, task):
        resp = auth_client.patch(f"/api/v1/epics/{epic.id}/", json={
            "status": "cancelled",
        })
        assert resp.status_code == 200
        # Check that the task was cancelled too
        task_resp = auth_client.get(f"/api/v1/tasks/{task.id}/")
        assert task_resp.json()["status"] == "cancelled"

    @patch("api.epics.broadcast")
    def test_delete_epic(self, mock_broadcast, auth_client, epic):
        resp = auth_client.delete(f"/api/v1/epics/{epic.id}/")
        assert resp.status_code == 204
        # Verify it's gone
        resp2 = auth_client.get(f"/api/v1/epics/{epic.id}/")
        assert resp2.status_code == 404

    @patch("api.epics.broadcast")
    def test_batch_delete_epics(self, mock_broadcast, auth_client, epic):
        resp = auth_client.post("/api/v1/epics/batch-delete/", json={
            "epic_ids": [epic.id],
        })
        assert resp.status_code == 204

    @patch("api.epics.broadcast")
    def test_list_epic_tasks(self, mock_broadcast, auth_client, epic, task):
        resp = auth_client.get(f"/api/v1/epics/{epic.id}/tasks/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(t["id"] == task.id for t in data["items"])


# ---------------------------------------------------------------------------
# Task API Tests
# ---------------------------------------------------------------------------

class TestTaskCRUD:
    @patch("api.tasks.broadcast")
    def test_create_task(self, mock_broadcast, auth_client, epic):
        resp = auth_client.post("/api/v1/tasks/", json={
            "epic_id": epic.id,
            "title": "New Task",
            "description": "Do something",
            "tags": ["frontend"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "New Task"
        assert data["epic_id"] == epic.id
        assert data["status"] == "pending"
        assert data["id"].startswith("tk-")

    @patch("api.tasks.broadcast")
    def test_create_task_blocked_by_deps(self, mock_broadcast, auth_client, epic, task):
        resp = auth_client.post("/api/v1/tasks/", json={
            "epic_id": epic.id,
            "title": "Dependent Task",
            "depends_on": [task.id],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "blocked"
        assert data["depends_on"] == [task.id]

    @patch("api.tasks.broadcast")
    def test_list_tasks(self, mock_broadcast, auth_client, task):
        resp = auth_client.get("/api/v1/tasks/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @patch("api.tasks.broadcast")
    def test_list_tasks_filter_epic(self, mock_broadcast, auth_client, epic, task):
        resp = auth_client.get(f"/api/v1/tasks/?epic_id={epic.id}")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    @patch("api.tasks.broadcast")
    def test_get_task(self, mock_broadcast, auth_client, task):
        resp = auth_client.get(f"/api/v1/tasks/{task.id}/")
        assert resp.status_code == 200
        assert resp.json()["id"] == task.id

    def test_get_task_not_found(self, auth_client):
        resp = auth_client.get("/api/v1/tasks/nonexistent/")
        assert resp.status_code == 404

    @patch("api.tasks.broadcast")
    def test_update_task(self, mock_broadcast, auth_client, task):
        resp = auth_client.patch(f"/api/v1/tasks/{task.id}/", json={
            "title": "Updated Task",
            "status": "running",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated Task"
        assert data["status"] == "running"

    @patch("api.tasks.broadcast")
    def test_update_task_syncs_epic_progress(self, mock_broadcast, auth_client, epic, task):
        # Complete the task
        auth_client.patch(f"/api/v1/tasks/{task.id}/", json={"status": "completed"})
        # Check epic progress
        resp = auth_client.get(f"/api/v1/epics/{epic.id}/")
        data = resp.json()
        assert data["completed_tasks"] == 1
        assert data["total_tasks"] == 1

    @patch("api.tasks.broadcast")
    def test_delete_task(self, mock_broadcast, auth_client, task):
        resp = auth_client.delete(f"/api/v1/tasks/{task.id}/")
        assert resp.status_code == 204
        resp2 = auth_client.get(f"/api/v1/tasks/{task.id}/")
        assert resp2.status_code == 404

    @patch("api.tasks.broadcast")
    def test_batch_delete_tasks(self, mock_broadcast, auth_client, task):
        resp = auth_client.post("/api/v1/tasks/batch-delete/", json={
            "task_ids": [task.id],
        })
        assert resp.status_code == 204

    @patch("api.tasks.broadcast")
    def test_delete_task_cleans_depends_on(self, mock_broadcast, auth_client, epic, task):
        # Create a second task that depends on the first
        resp = auth_client.post("/api/v1/tasks/", json={
            "epic_id": epic.id,
            "title": "Dependent Task",
            "depends_on": [task.id],
        })
        dep_task_id = resp.json()["id"]
        assert resp.json()["depends_on"] == [task.id]

        # Delete the dependency
        auth_client.delete(f"/api/v1/tasks/{task.id}/")

        # Verify depends_on was cleaned up
        resp2 = auth_client.get(f"/api/v1/tasks/{dep_task_id}/")
        assert resp2.json()["depends_on"] == []

    @patch("api.tasks.broadcast")
    @patch("api.epic_helpers.broadcast", create=True)
    def test_complete_task_unblocks_dependent(self, mock_helper_bc, mock_tasks_bc, auth_client, epic):
        """Completing a task unblocks dependents whose deps are all completed."""
        # Create task A (pending)
        resp_a = auth_client.post("/api/v1/tasks/", json={
            "epic_id": epic.id,
            "title": "Task A",
        })
        assert resp_a.status_code == 201
        task_a_id = resp_a.json()["id"]

        # Create task B that depends on A — should start as blocked
        resp_b = auth_client.post("/api/v1/tasks/", json={
            "epic_id": epic.id,
            "title": "Task B",
            "depends_on": [task_a_id],
        })
        assert resp_b.status_code == 201
        task_b_id = resp_b.json()["id"]
        assert resp_b.json()["status"] == "blocked"

        # Complete task A
        resp_a_complete = auth_client.patch(f"/api/v1/tasks/{task_a_id}/", json={"status": "completed"})
        assert resp_a_complete.status_code == 200

        # Task B should now be pending (auto-unblocked)
        resp_b2 = auth_client.get(f"/api/v1/tasks/{task_b_id}/")
        assert resp_b2.json()["status"] == "pending"

    @patch("api.tasks.broadcast")
    @patch("api.epic_helpers.broadcast", create=True)
    def test_complete_task_partial_deps_stays_blocked(self, mock_helper_bc, mock_tasks_bc, auth_client, epic):
        """If only some deps are completed, dependent task stays blocked."""
        resp_a = auth_client.post("/api/v1/tasks/", json={
            "epic_id": epic.id, "title": "Dep A",
        })
        assert resp_a.status_code == 201
        task_a_id = resp_a.json()["id"]

        resp_b = auth_client.post("/api/v1/tasks/", json={
            "epic_id": epic.id, "title": "Dep B",
        })
        assert resp_b.status_code == 201
        task_b_id = resp_b.json()["id"]

        resp_c = auth_client.post("/api/v1/tasks/", json={
            "epic_id": epic.id,
            "title": "Blocked Task",
            "depends_on": [task_a_id, task_b_id],
        })
        assert resp_c.status_code == 201
        task_c_id = resp_c.json()["id"]
        assert resp_c.json()["status"] == "blocked"

        # Complete only task A
        resp_a_complete = auth_client.patch(f"/api/v1/tasks/{task_a_id}/", json={"status": "completed"})
        assert resp_a_complete.status_code == 200

        # Task C should still be blocked (B is not completed)
        resp_c2 = auth_client.get(f"/api/v1/tasks/{task_c_id}/")
        assert resp_c2.json()["status"] == "blocked"

    @patch("api.tasks.broadcast")
    def test_complete_task_no_dependents_noop(self, mock_broadcast, auth_client, epic, task):
        """Completing a task with no dependents doesn't error."""
        resp = auth_client.patch(f"/api/v1/tasks/{task.id}/", json={
            "status": "completed",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_create_task_epic_not_found(self, auth_client):
        resp = auth_client.post("/api/v1/tasks/", json={
            "epic_id": "nonexistent",
            "title": "Orphan Task",
        })
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_epic_defaults(self, db, user_profile):
        epic = Epic(title="Defaults Test", user_profile_id=user_profile.id)
        db.add(epic)
        db.commit()
        db.refresh(epic)
        assert epic.id.startswith("ep-")
        assert epic.status == "planning"
        assert epic.priority == 2
        assert epic.spent_tokens == 0
        assert epic.total_tasks == 0

    def test_task_defaults(self, db, user_profile):
        epic = Epic(title="Parent", user_profile_id=user_profile.id)
        db.add(epic)
        db.commit()
        db.refresh(epic)

        task = Task(epic_id=epic.id, title="Defaults Test")
        db.add(task)
        db.commit()
        db.refresh(task)
        assert task.id.startswith("tk-")
        assert task.status == "pending"
        assert task.priority == 2
        assert task.retry_count == 0
        assert task.max_retries == 2

    def test_epic_cascade_delete(self, db, user_profile):
        epic = Epic(title="Cascade Test", user_profile_id=user_profile.id)
        db.add(epic)
        db.commit()
        db.refresh(epic)

        task = Task(epic_id=epic.id, title="Child Task")
        db.add(task)
        db.commit()
        task_id = task.id

        db.delete(epic)
        db.commit()
        assert db.query(Task).filter(Task.id == task_id).first() is None

    def test_workflow_tags_column(self, db, workflow):
        workflow.tags = ["automation", "llm"]
        db.commit()
        db.refresh(workflow)
        assert workflow.tags == ["automation", "llm"]
