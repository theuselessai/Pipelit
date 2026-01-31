"""Tests for the django-ninja workflow REST API."""

import json

import pytest
from django.test import Client

from apps.workflows.models import (
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)
from apps.workflows.models.node import AIComponentConfig, ModelComponentConfig, TriggerComponentConfig


@pytest.fixture
def auth_client(user, user_profile):
    from apps.users.models import APIKey

    api_key = APIKey.objects.create(user=user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {api_key.key}"
    return client


@pytest.fixture
def node(workflow):
    cc = ModelComponentConfig.objects.create(
        component_type="ai_model",
        extra_config={"temperature": 0.7},
    )
    return WorkflowNode.objects.create(
        workflow=workflow,
        node_id="chat1",
        component_type="ai_model",
        component_config=cc,
        is_entry_point=True,
    )


@pytest.fixture
def edge(workflow):
    return WorkflowEdge.objects.create(
        workflow=workflow,
        source_node_id="chat1",
        target_node_id="chat2",
        edge_type="direct",
    )


@pytest.fixture
def trigger_node(workflow):
    cc = TriggerComponentConfig.objects.create(
        component_type="trigger_manual",
        trigger_config={},
        is_active=True,
        priority=0,
    )
    return WorkflowNode.objects.create(
        workflow=workflow,
        node_id="manual_trigger_1",
        component_type="trigger_manual",
        component_config=cc,
    )


@pytest.fixture
def execution(workflow, user_profile):
    return WorkflowExecution.objects.create(
        workflow=workflow,
        user_profile=user_profile,
        thread_id="t1",
        status="running",
    )


# ── Workflow CRUD ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestWorkflowAPI:
    def test_list_workflows(self, auth_client, workflow):
        resp = auth_client.get("/api/v1/workflows/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["slug"] == "test-workflow"

    def test_create_workflow(self, auth_client, user_profile):
        resp = auth_client.post(
            "/api/v1/workflows/",
            data=json.dumps({"name": "New WF", "slug": "new-wf"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.json()["slug"] == "new-wf"
        assert Workflow.objects.filter(slug="new-wf").exists()

    def test_get_workflow_detail(self, auth_client, workflow, node, edge, trigger_node):
        resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 2  # node + trigger_node
        assert len(data["edges"]) == 1

    def test_update_workflow(self, auth_client, workflow):
        resp = auth_client.patch(
            f"/api/v1/workflows/{workflow.slug}/",
            data=json.dumps({"name": "Updated"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete_workflow(self, auth_client, workflow):
        resp = auth_client.delete(f"/api/v1/workflows/{workflow.slug}/")
        assert resp.status_code == 204
        # Soft-deleted: default manager excludes it
        assert not Workflow.objects.filter(slug=workflow.slug).exists()
        assert Workflow.all_objects.filter(slug=workflow.slug).exists()

    def test_unauthenticated(self):
        client = Client()
        resp = client.get("/api/v1/workflows/")
        assert resp.status_code == 401

    def test_bearer_auth(self, auth_client, workflow):
        resp = auth_client.get("/api/v1/workflows/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ── Auth Token Endpoint ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAuthTokenAPI:
    def test_obtain_token(self, user, user_profile):
        client = Client()
        resp = client.post(
            "/api/v1/auth/token/",
            data=json.dumps({"username": "testuser", "password": "testpass"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data
        assert len(data["key"]) == 36  # UUID format

    def test_obtain_token_invalid_credentials(self):
        client = Client()
        resp = client.post(
            "/api/v1/auth/token/",
            data=json.dumps({"username": "bad", "password": "bad"}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_obtain_token_regenerates_key(self, user, user_profile):
        client = Client()
        resp1 = client.post(
            "/api/v1/auth/token/",
            data=json.dumps({"username": "testuser", "password": "testpass"}),
            content_type="application/json",
        )
        resp2 = client.post(
            "/api/v1/auth/token/",
            data=json.dumps({"username": "testuser", "password": "testpass"}),
            content_type="application/json",
        )
        assert resp1.json()["key"] != resp2.json()["key"]

    def test_token_works_for_auth(self, user, user_profile, workflow):
        client = Client()
        resp = client.post(
            "/api/v1/auth/token/",
            data=json.dumps({"username": "testuser", "password": "testpass"}),
            content_type="application/json",
        )
        key = resp.json()["key"]
        bearer_client = Client()
        bearer_client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {key}"
        resp = bearer_client.get("/api/v1/workflows/")
        assert resp.status_code == 200


# ── Node CRUD ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestNodeAPI:
    def test_list_nodes(self, auth_client, workflow, node):
        resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/nodes/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_create_node(self, auth_client, workflow):
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/nodes/",
            data=json.dumps({
                "node_id": "agent1",
                "component_type": "simple_agent",
                "is_entry_point": True,
                "config": {"system_prompt": "Be helpful", "extra_config": {}},
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["node_id"] == "agent1"
        assert data["config"]["system_prompt"] == "Be helpful"
        assert WorkflowNode.objects.filter(workflow=workflow, node_id="agent1").exists()

    def test_create_trigger_node(self, auth_client, workflow):
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/nodes/",
            data=json.dumps({
                "node_id": "tg_trigger_1",
                "component_type": "trigger_telegram",
                "config": {
                    "credential_id": None,
                    "is_active": True,
                    "priority": 5,
                    "trigger_config": {"pattern": "hello"},
                },
            }),
            content_type="application/json",
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
            data=json.dumps({"position_x": 100, "config": {"model_name": "gpt-4o"}}),
            content_type="application/json",
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
        assert not WorkflowNode.objects.filter(workflow=workflow, node_id="chat1").exists()
        # Edge referencing this node should also be deleted
        assert not WorkflowEdge.objects.filter(workflow=workflow, source_node_id="chat1").exists()


# ── Edge CRUD ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestEdgeAPI:
    def test_list_edges(self, auth_client, workflow, edge):
        resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/edges/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_create_edge(self, auth_client, workflow):
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/edges/",
            data=json.dumps({
                "source_node_id": "a",
                "target_node_id": "b",
                "edge_type": "direct",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.json()["source_node_id"] == "a"

    def test_update_edge(self, auth_client, workflow, edge):
        resp = auth_client.patch(
            f"/api/v1/workflows/{workflow.slug}/edges/{edge.id}/",
            data=json.dumps({"priority": 5}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["priority"] == 5

    def test_delete_edge(self, auth_client, workflow, edge):
        resp = auth_client.delete(f"/api/v1/workflows/{workflow.slug}/edges/{edge.id}/")
        assert resp.status_code == 204


# ── Execution API ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestExecutionAPI:
    def test_list_executions(self, auth_client, execution):
        resp = auth_client.get("/api/v1/executions/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_executions_filter_status(self, auth_client, execution):
        resp = auth_client.get("/api/v1/executions/?status=running")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp = auth_client.get("/api/v1/executions/?status=completed")
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_list_executions_filter_workflow(self, auth_client, execution, workflow):
        resp = auth_client.get(f"/api/v1/executions/?workflow_slug={workflow.slug}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_execution_detail(self, auth_client, execution):
        resp = auth_client.get(f"/api/v1/executions/{execution.execution_id}/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_cancel_execution(self, auth_client, execution):
        resp = auth_client.post(f"/api/v1/executions/{execution.execution_id}/cancel/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_completed_execution_noop(self, auth_client, execution):
        execution.status = "completed"
        execution.save(update_fields=["status"])
        resp = auth_client.post(f"/api/v1/executions/{execution.execution_id}/cancel/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
