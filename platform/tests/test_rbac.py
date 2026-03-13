"""RBAC (Role-Based Access Control) tests.

Tests that admin users can access all resources while normal users
are scoped to their own resources and blocked from admin-only endpoints.
"""

from __future__ import annotations

import uuid

import bcrypt
import pytest
from fastapi.testclient import TestClient

from models.credential import BaseCredential
from models.execution import WorkflowExecution
from models.scheduled_job import ScheduledJob
from models.user import APIKey, UserProfile, UserRole
from models.workflow import Workflow


# ── Fixtures ─────────────────────────────────────────────────────────────────


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
def admin_user(db):
    user = UserProfile(
        username="admin-user",
        password_hash=bcrypt.hashpw(b"adminpass", bcrypt.gensalt()).decode(),
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_key(db, admin_user):
    raw = str(uuid.uuid4())
    key = APIKey(user_id=admin_user.id, key=raw, name="default", prefix=raw[:8])
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


@pytest.fixture
def admin_client(client, admin_key):
    client.headers["Authorization"] = f"Bearer {admin_key.key}"
    return client


@pytest.fixture
def normal_user(db):
    user = UserProfile(
        username="normal-user",
        password_hash=bcrypt.hashpw(b"normalpass", bcrypt.gensalt()).decode(),
        role=UserRole.NORMAL,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def normal_key(db, normal_user):
    raw = str(uuid.uuid4())
    key = APIKey(user_id=normal_user.id, key=raw, name="default", prefix=raw[:8])
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


@pytest.fixture
def normal_client(client, normal_key):
    c = TestClient(client.app)
    c.headers["Authorization"] = f"Bearer {normal_key.key}"
    return c


@pytest.fixture
def admin_workflow(db, admin_user):
    wf = Workflow(
        name="Admin Workflow",
        slug="admin-workflow",
        owner_id=admin_user.id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture
def normal_workflow(db, normal_user):
    wf = Workflow(
        name="Normal Workflow",
        slug="normal-workflow",
        owner_id=normal_user.id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture
def admin_credential(db, admin_user):
    cred = BaseCredential(
        user_profile_id=admin_user.id,
        name="Admin Credential",
        credential_type="llm",
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


@pytest.fixture
def normal_credential(db, normal_user):
    cred = BaseCredential(
        user_profile_id=normal_user.id,
        name="Normal Credential",
        credential_type="llm",
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


def _make_execution(db, workflow, user_profile, **kwargs):
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        user_profile_id=user_profile.id,
        thread_id=uuid.uuid4().hex,
        trigger_payload={},
        **kwargs,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def _make_schedule(db, workflow, user_profile, **kwargs):
    job = ScheduledJob(
        name=kwargs.get("name", "Test Schedule"),
        workflow_id=workflow.id,
        user_profile_id=user_profile.id,
        interval_seconds=kwargs.get("interval_seconds", 60),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ── Admin Access Tests ───────────────────────────────────────────────────────


class TestAdminAccess:
    """Admin users can see and manage all resources regardless of ownership."""

    def test_admin_lists_all_workflows(
        self, admin_client, admin_workflow, normal_workflow
    ):
        resp = admin_client.get("/api/v1/workflows/")
        assert resp.status_code == 200
        data = resp.json()
        slugs = [w["slug"] for w in data["items"]]
        assert "admin-workflow" in slugs
        assert "normal-workflow" in slugs
        assert data["total"] == 2

    def test_admin_gets_own_workflow(self, admin_client, admin_workflow):
        resp = admin_client.get(f"/api/v1/workflows/{admin_workflow.slug}/")
        assert resp.status_code == 200
        assert resp.json()["slug"] == "admin-workflow"

    def test_admin_gets_other_users_workflow(self, admin_client, normal_workflow):
        resp = admin_client.get(f"/api/v1/workflows/{normal_workflow.slug}/")
        assert resp.status_code == 200
        assert resp.json()["slug"] == "normal-workflow"

    def test_admin_lists_all_credentials(
        self, admin_client, admin_credential, normal_credential
    ):
        resp = admin_client.get("/api/v1/credentials/")
        assert resp.status_code == 200
        data = resp.json()
        names = [c["name"] for c in data["items"]]
        assert "Admin Credential" in names
        assert "Normal Credential" in names
        assert data["total"] == 2

    def test_admin_gets_other_users_credential(
        self, admin_client, normal_credential
    ):
        resp = admin_client.get(f"/api/v1/credentials/{normal_credential.id}/")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Normal Credential"

    def test_admin_lists_all_executions(
        self,
        admin_client,
        db,
        admin_user,
        normal_user,
        admin_workflow,
        normal_workflow,
    ):
        _make_execution(db, admin_workflow, admin_user, status="completed")
        _make_execution(db, normal_workflow, normal_user, status="completed")

        resp = admin_client.get("/api/v1/executions/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_admin_lists_all_schedules(
        self,
        admin_client,
        db,
        admin_user,
        normal_user,
        admin_workflow,
        normal_workflow,
    ):
        _make_schedule(db, admin_workflow, admin_user, name="Admin Schedule")
        _make_schedule(db, normal_workflow, normal_user, name="Normal Schedule")

        resp = admin_client.get("/api/v1/schedules/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_admin_accesses_memory_facts(self, admin_client):
        resp = admin_client.get("/api/v1/memories/facts/")
        assert resp.status_code == 200

    def test_admin_accesses_memory_episodes(self, admin_client):
        resp = admin_client.get("/api/v1/memories/episodes/")
        assert resp.status_code == 200

    def test_admin_accesses_memory_procedures(self, admin_client):
        resp = admin_client.get("/api/v1/memories/procedures/")
        assert resp.status_code == 200

    def test_admin_accesses_memory_users(self, admin_client):
        resp = admin_client.get("/api/v1/memories/users/")
        assert resp.status_code == 200

    def test_admin_accesses_memory_checkpoints(self, admin_client):
        resp = admin_client.get("/api/v1/memories/checkpoints/")
        assert resp.status_code == 200


# ── Normal User Scoping Tests ────────────────────────────────────────────────


class TestNormalUserScoping:
    """Normal users can only see and manage their own resources."""

    def test_normal_user_lists_only_own_workflows(
        self, normal_client, admin_workflow, normal_workflow
    ):
        resp = normal_client.get("/api/v1/workflows/")
        assert resp.status_code == 200
        data = resp.json()
        slugs = [w["slug"] for w in data["items"]]
        assert "normal-workflow" in slugs
        assert "admin-workflow" not in slugs
        assert data["total"] == 1

    def test_normal_user_gets_own_workflow(self, normal_client, normal_workflow):
        resp = normal_client.get(f"/api/v1/workflows/{normal_workflow.slug}/")
        assert resp.status_code == 200
        assert resp.json()["slug"] == "normal-workflow"

    def test_normal_user_cannot_get_other_users_workflow(
        self, normal_client, admin_workflow
    ):
        resp = normal_client.get(f"/api/v1/workflows/{admin_workflow.slug}/")
        assert resp.status_code == 404

    def test_normal_user_lists_only_own_credentials(
        self, normal_client, admin_credential, normal_credential
    ):
        resp = normal_client.get("/api/v1/credentials/")
        assert resp.status_code == 200
        data = resp.json()
        names = [c["name"] for c in data["items"]]
        assert "Normal Credential" in names
        assert "Admin Credential" not in names
        assert data["total"] == 1

    def test_normal_user_cannot_get_other_users_credential(
        self, normal_client, admin_credential
    ):
        resp = normal_client.get(f"/api/v1/credentials/{admin_credential.id}/")
        assert resp.status_code == 404

    def test_normal_user_lists_only_own_executions(
        self,
        normal_client,
        db,
        admin_user,
        normal_user,
        admin_workflow,
        normal_workflow,
    ):
        _make_execution(db, admin_workflow, admin_user, status="completed")
        _make_execution(db, normal_workflow, normal_user, status="completed")

        resp = normal_client.get("/api/v1/executions/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["workflow_slug"] == "normal-workflow"

    def test_normal_user_cannot_get_other_users_execution(
        self, normal_client, db, admin_user, admin_workflow
    ):
        execution = _make_execution(
            db, admin_workflow, admin_user, status="completed"
        )
        resp = normal_client.get(
            f"/api/v1/executions/{execution.execution_id}/"
        )
        assert resp.status_code == 404

    def test_normal_user_lists_only_own_schedules(
        self,
        normal_client,
        db,
        admin_user,
        normal_user,
        admin_workflow,
        normal_workflow,
    ):
        _make_schedule(db, admin_workflow, admin_user, name="Admin Schedule")
        _make_schedule(db, normal_workflow, normal_user, name="Normal Schedule")

        resp = normal_client.get("/api/v1/schedules/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_normal_user_cannot_delete_other_users_workflow(
        self, normal_client, admin_workflow
    ):
        resp = normal_client.delete(
            f"/api/v1/workflows/{admin_workflow.slug}/"
        )
        assert resp.status_code == 404

    def test_normal_user_cannot_update_other_users_workflow(
        self, normal_client, admin_workflow
    ):
        resp = normal_client.patch(
            f"/api/v1/workflows/{admin_workflow.slug}/",
            json={"name": "Hacked"},
        )
        assert resp.status_code == 404

    def test_normal_user_cannot_delete_other_users_credential(
        self, normal_client, admin_credential
    ):
        resp = normal_client.delete(
            f"/api/v1/credentials/{admin_credential.id}/"
        )
        assert resp.status_code == 404

    def test_normal_user_cannot_update_other_users_credential(
        self, normal_client, admin_credential
    ):
        resp = normal_client.patch(
            f"/api/v1/credentials/{admin_credential.id}/",
            json={"name": "Hacked"},
        )
        assert resp.status_code == 404

    def test_normal_user_cannot_cancel_other_users_execution(
        self, normal_client, db, admin_user, admin_workflow
    ):
        execution = _make_execution(
            db, admin_workflow, admin_user, status="running"
        )
        resp = normal_client.post(
            f"/api/v1/executions/{execution.execution_id}/cancel/"
        )
        assert resp.status_code == 404


# ── 403 Forbidden Tests (Memory Endpoints) ───────────────────────────────────


class TestNormalUserForbidden:
    """Normal users get 403 on admin-only endpoints (memory)."""

    def test_normal_user_forbidden_memory_facts(self, normal_client):
        resp = normal_client.get("/api/v1/memories/facts/")
        assert resp.status_code == 403

    def test_normal_user_forbidden_memory_episodes(self, normal_client):
        resp = normal_client.get("/api/v1/memories/episodes/")
        assert resp.status_code == 403

    def test_normal_user_forbidden_memory_procedures(self, normal_client):
        resp = normal_client.get("/api/v1/memories/procedures/")
        assert resp.status_code == 403

    def test_normal_user_forbidden_memory_users(self, normal_client):
        resp = normal_client.get("/api/v1/memories/users/")
        assert resp.status_code == 403

    def test_normal_user_forbidden_memory_checkpoints(self, normal_client):
        resp = normal_client.get("/api/v1/memories/checkpoints/")
        assert resp.status_code == 403

    def test_normal_user_forbidden_batch_delete_facts(self, normal_client):
        resp = normal_client.post(
            "/api/v1/memories/facts/batch-delete/", json={"ids": []}
        )
        assert resp.status_code == 403

    def test_normal_user_forbidden_batch_delete_episodes(self, normal_client):
        resp = normal_client.post(
            "/api/v1/memories/episodes/batch-delete/", json={"ids": []}
        )
        assert resp.status_code == 403

    def test_normal_user_forbidden_batch_delete_procedures(self, normal_client):
        resp = normal_client.post(
            "/api/v1/memories/procedures/batch-delete/", json={"ids": []}
        )
        assert resp.status_code == 403

    def test_normal_user_forbidden_batch_delete_memory_users(
        self, normal_client
    ):
        resp = normal_client.post(
            "/api/v1/memories/users/batch-delete/", json={"ids": []}
        )
        assert resp.status_code == 403

    def test_normal_user_forbidden_batch_delete_checkpoints(
        self, normal_client
    ):
        resp = normal_client.post(
            "/api/v1/memories/checkpoints/batch-delete/", json={"ids": []}
        )
        assert resp.status_code == 403


# ── require_admin Dependency Tests ───────────────────────────────────────────


class TestRequireAdminDependency:
    """The require_admin FastAPI dependency enforces admin role."""

    def test_require_admin_allows_admin(self, admin_client):
        resp = admin_client.get("/api/v1/memories/facts/")
        assert resp.status_code == 200

    def test_require_admin_blocks_normal_user(self, normal_client):
        resp = normal_client.get("/api/v1/memories/facts/")
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"].lower()

    def test_require_admin_blocks_unauthenticated(self, client):
        resp = client.get("/api/v1/memories/facts/")
        assert resp.status_code in (401, 403)
