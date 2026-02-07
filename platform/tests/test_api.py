"""Tests for the FastAPI workflow REST API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure platform/ is importable
_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.node import BaseComponentConfig, WorkflowNode, WorkflowEdge
from models.execution import WorkflowExecution
from models.workflow import Workflow


# ---------------------------------------------------------------------------
# Override the database dependency for tests
# ---------------------------------------------------------------------------

@pytest.fixture
def app(db):
    """Create a test FastAPI app with DB overridden to use test session."""
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
def node(db, workflow):
    cc = BaseComponentConfig(
        component_type="ai_model",
        extra_config={"temperature": 0.7},
    )
    db.add(cc)
    db.flush()
    n = WorkflowNode(
        workflow_id=workflow.id,
        node_id="chat1",
        component_type="ai_model",
        component_config_id=cc.id,
        is_entry_point=True,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


@pytest.fixture
def edge(db, workflow):
    e = WorkflowEdge(
        workflow_id=workflow.id,
        source_node_id="chat1",
        target_node_id="chat2",
        edge_type="direct",
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


@pytest.fixture
def trigger_node(db, workflow):
    cc = BaseComponentConfig(
        component_type="trigger_manual",
        trigger_config={},
        is_active=True,
        priority=0,
    )
    db.add(cc)
    db.flush()
    n = WorkflowNode(
        workflow_id=workflow.id,
        node_id="manual_trigger_1",
        component_type="trigger_manual",
        component_config_id=cc.id,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


@pytest.fixture
def execution(db, workflow, user_profile):
    ex = WorkflowExecution(
        workflow_id=workflow.id,
        user_profile_id=user_profile.id,
        thread_id="t1",
        status="running",
    )
    db.add(ex)
    db.commit()
    db.refresh(ex)
    return ex


# ── Workflow CRUD ─────────────────────────────────────────────────────────────


class TestWorkflowAPI:
    def test_list_workflows(self, auth_client, workflow):
        resp = auth_client.get("/api/v1/workflows/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["slug"] == "test-workflow"
        assert data["total"] == 1

    def test_create_workflow(self, auth_client, user_profile):
        resp = auth_client.post(
            "/api/v1/workflows/",
            json={"name": "New WF", "slug": "new-wf"},
        )
        assert resp.status_code == 201
        assert resp.json()["slug"] == "new-wf"

    def test_get_workflow_detail(self, auth_client, workflow, node, edge, trigger_node):
        resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 2  # node + trigger_node
        assert len(data["edges"]) == 1

    def test_update_workflow(self, auth_client, workflow):
        resp = auth_client.patch(
            f"/api/v1/workflows/{workflow.slug}/",
            json={"name": "Updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete_workflow(self, auth_client, workflow, db):
        resp = auth_client.delete(f"/api/v1/workflows/{workflow.slug}/")
        assert resp.status_code == 204
        db.refresh(workflow)
        assert workflow.deleted_at is not None

    def test_unauthenticated(self, client):
        resp = client.get("/api/v1/workflows/")
        assert resp.status_code in (401, 403)

    def test_bearer_auth(self, auth_client, workflow):
        resp = auth_client.get("/api/v1/workflows/")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1


# ── Auth Token Endpoint ──────────────────────────────────────────────────────


class TestAuthTokenAPI:
    def test_obtain_token(self, client, user_profile):
        resp = client.post(
            "/api/v1/auth/token/",
            json={"username": "testuser", "password": "testpass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data
        assert len(data["key"]) == 36  # UUID format

    def test_obtain_token_invalid_credentials(self, client):
        resp = client.post(
            "/api/v1/auth/token/",
            json={"username": "bad", "password": "bad"},
        )
        assert resp.status_code == 401

    def test_obtain_token_regenerates_key(self, client, user_profile):
        resp1 = client.post("/api/v1/auth/token/", json={"username": "testuser", "password": "testpass"})
        resp2 = client.post("/api/v1/auth/token/", json={"username": "testuser", "password": "testpass"})
        assert resp1.json()["key"] != resp2.json()["key"]

    def test_token_works_for_auth(self, client, user_profile, workflow):
        resp = client.post("/api/v1/auth/token/", json={"username": "testuser", "password": "testpass"})
        key = resp.json()["key"]
        resp = client.get("/api/v1/workflows/", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 200


# ── Node CRUD ─────────────────────────────────────────────────────────────────


class TestNodeAPI:
    def test_list_nodes(self, auth_client, workflow, node):
        resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/nodes/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_create_node(self, auth_client, workflow):
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/nodes/",
            json={
                "node_id": "agent1",
                "component_type": "agent",
                "is_entry_point": True,
                "config": {"system_prompt": "Be helpful", "extra_config": {}},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["node_id"] == "agent1"
        assert data["config"]["system_prompt"] == "Be helpful"

    def test_create_trigger_node(self, auth_client, workflow):
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/nodes/",
            json={
                "node_id": "tg_trigger_1",
                "component_type": "trigger_telegram",
                "config": {
                    "credential_id": None,
                    "is_active": True,
                    "priority": 5,
                    "trigger_config": {"pattern": "hello"},
                },
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["component_type"] == "trigger_telegram"
        assert data["config"]["is_active"] is True
        assert data["config"]["priority"] == 5
        assert data["config"]["trigger_config"] == {"pattern": "hello"}

    def test_update_node(self, auth_client, workflow, node):
        resp = auth_client.patch(
            f"/api/v1/workflows/{workflow.slug}/nodes/{node.node_id}/",
            json={"position_x": 100, "config": {"model_name": "gpt-4o"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["position_x"] == 100
        assert data["config"]["model_name"] == "gpt-4o"

    def test_delete_node(self, auth_client, workflow, node, edge):
        resp = auth_client.delete(
            f"/api/v1/workflows/{workflow.slug}/nodes/{node.node_id}/"
        )
        assert resp.status_code == 204


# ── Edge CRUD ─────────────────────────────────────────────────────────────────


class TestEdgeAPI:
    def test_list_edges(self, auth_client, workflow, edge):
        resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/edges/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_create_edge(self, auth_client, workflow):
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/edges/",
            json={"source_node_id": "a", "target_node_id": "b", "edge_type": "direct"},
        )
        assert resp.status_code == 201
        assert resp.json()["source_node_id"] == "a"

    def test_update_edge(self, auth_client, workflow, edge):
        resp = auth_client.patch(
            f"/api/v1/workflows/{workflow.slug}/edges/{edge.id}/",
            json={"priority": 5},
        )
        assert resp.status_code == 200
        assert resp.json()["priority"] == 5

    def test_delete_edge(self, auth_client, workflow, edge):
        resp = auth_client.delete(f"/api/v1/workflows/{workflow.slug}/edges/{edge.id}/")
        assert resp.status_code == 204


# ── Execution API ─────────────────────────────────────────────────────────────


class TestExecutionAPI:
    def test_list_executions(self, auth_client, execution):
        resp = auth_client.get("/api/v1/executions/")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_list_executions_filter_status(self, auth_client, execution):
        resp = auth_client.get("/api/v1/executions/?status=running")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

        resp = auth_client.get("/api/v1/executions/?status=completed")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 0

    def test_list_executions_filter_workflow(self, auth_client, execution, workflow):
        resp = auth_client.get(f"/api/v1/executions/?workflow_slug={workflow.slug}")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_get_execution_detail(self, auth_client, execution):
        resp = auth_client.get(f"/api/v1/executions/{execution.execution_id}/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_cancel_execution(self, auth_client, execution):
        resp = auth_client.post(f"/api/v1/executions/{execution.execution_id}/cancel/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_completed_execution_noop(self, auth_client, execution, db):
        execution.status = "completed"
        db.commit()
        resp = auth_client.post(f"/api/v1/executions/{execution.execution_id}/cancel/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


# ── Setup API ────────────────────────────────────────────────────────────────


class TestSetupAPI:
    def test_setup_status_needs_setup(self, client):
        resp = client.get("/api/v1/auth/setup-status/")
        assert resp.status_code == 200
        assert resp.json()["needs_setup"] is True

    def test_setup_status_after_user(self, client, user_profile):
        resp = client.get("/api/v1/auth/setup-status/")
        assert resp.status_code == 200
        assert resp.json()["needs_setup"] is False

    def test_setup_creates_user(self, client):
        resp = client.post(
            "/api/v1/auth/setup/",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data
        assert len(data["key"]) == 36

    def test_setup_rejects_when_user_exists(self, client, user_profile):
        resp = client.post(
            "/api/v1/auth/setup/",
            json={"username": "another", "password": "pass"},
        )
        assert resp.status_code == 409


# ── Edge sub-component linking ───────────────────────────────────────────────


class TestEdgeSubComponentLinking:
    def test_llm_edge_links_model_config(self, auth_client, workflow, db):
        from models.node import BaseComponentConfig, WorkflowNode

        # Create ai_model node
        model_cc = BaseComponentConfig(component_type="ai_model", model_name="gpt-4o")
        db.add(model_cc)
        db.flush()
        model_node = WorkflowNode(workflow_id=workflow.id, node_id="model1", component_type="ai_model", component_config_id=model_cc.id)
        db.add(model_node)

        # Create agent node
        agent_cc = BaseComponentConfig(component_type="agent", system_prompt="test")
        db.add(agent_cc)
        db.flush()
        agent_node = WorkflowNode(workflow_id=workflow.id, node_id="agent1", component_type="agent", component_config_id=agent_cc.id)
        db.add(agent_node)
        db.commit()

        # Create edge with llm label
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/edges/",
            json={"source_node_id": "model1", "target_node_id": "agent1", "edge_label": "llm"},
        )
        assert resp.status_code == 201

        # Verify FK was set
        db.refresh(agent_cc)
        assert agent_cc.llm_model_config_id == model_cc.id

    def test_llm_edge_delete_unlinks_model_config(self, auth_client, workflow, db):
        from models.node import BaseComponentConfig, WorkflowNode

        model_cc = BaseComponentConfig(component_type="ai_model", model_name="gpt-4o")
        db.add(model_cc)
        db.flush()
        model_node = WorkflowNode(workflow_id=workflow.id, node_id="model1", component_type="ai_model", component_config_id=model_cc.id)
        db.add(model_node)

        agent_cc = BaseComponentConfig(component_type="agent", system_prompt="test")
        db.add(agent_cc)
        db.flush()
        agent_node = WorkflowNode(workflow_id=workflow.id, node_id="agent1", component_type="agent", component_config_id=agent_cc.id)
        db.add(agent_node)
        db.commit()

        # Create then delete
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/edges/",
            json={"source_node_id": "model1", "target_node_id": "agent1", "edge_label": "llm"},
        )
        edge_id = resp.json()["id"]

        resp = auth_client.delete(f"/api/v1/workflows/{workflow.slug}/edges/{edge_id}/")
        assert resp.status_code == 204

        db.refresh(agent_cc)
        assert agent_cc.llm_model_config_id is None
