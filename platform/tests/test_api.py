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
        slug = workflow.slug
        resp = auth_client.delete(f"/api/v1/workflows/{slug}/")
        assert resp.status_code == 204
        assert db.query(Workflow).filter(Workflow.slug == slug).first() is None

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

    def test_obtain_token_malformed_hash(self, client, db):
        from models.user import UserProfile

        user = UserProfile(
            username="badhashuser",
            password_hash="$2b$invalid",
        )
        db.add(user)
        db.commit()

        resp = client.post(
            "/api/v1/auth/token/",
            json={"username": "badhashuser", "password": "anypass"},
        )
        assert resp.status_code == 401


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

    def test_create_node_without_node_id(self, auth_client, workflow):
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/nodes/",
            json={"component_type": "agent", "config": {"system_prompt": "test"}},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["node_id"].startswith("agent_")
        assert len(data["node_id"]) > len("agent_")

    def test_create_node_without_node_id_loop_exhaustion(self, auth_client, workflow, db):
        """All 10 candidates collide → falls back to 8-byte hex."""
        from unittest.mock import patch
        from models.node import BaseComponentConfig, WorkflowNode

        # Pre-create a node with the ID that token_hex(4) will always generate
        cc = BaseComponentConfig(component_type="agent", system_prompt="x")
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(
            workflow_id=workflow.id, node_id="agent_aaaa",
            component_type="agent", component_config_id=cc.id,
        ))
        db.commit()

        def fake_token_hex(n):
            return "aaaa" if n == 4 else "bbbbbbbbbbbbbbbb"

        with patch("api.nodes.secrets.token_hex", side_effect=fake_token_hex):
            resp = auth_client.post(
                f"/api/v1/workflows/{workflow.slug}/nodes/",
                json={"component_type": "agent", "config": {"system_prompt": "test"}},
            )
        assert resp.status_code == 201
        assert resp.json()["node_id"] == "agent_bbbbbbbbbbbbbbbb"

    def test_create_node_auto_id_integrity_error_retry(self, auth_client, workflow, db):
        """IntegrityError on auto-generated ID retries with longer hex."""
        from unittest.mock import patch
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        original_commit = db.commit
        calls = []

        def mock_commit():
            calls.append(1)
            if len(calls) == 1:
                raise SAIntegrityError("dup", {}, None)
            return original_commit()

        with patch.object(db, "commit", side_effect=mock_commit):
            resp = auth_client.post(
                f"/api/v1/workflows/{workflow.slug}/nodes/",
                json={"component_type": "agent", "config": {"system_prompt": "test"}},
            )
        assert resp.status_code == 201

    def test_create_node_auto_id_double_collision_returns_409(self, auth_client, workflow, db):
        """IntegrityError on both attempts returns 409."""
        from unittest.mock import patch
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        original_commit = db.commit

        def mock_commit():
            raise SAIntegrityError("dup", {}, None)

        with patch.object(db, "commit", side_effect=mock_commit):
            resp = auth_client.post(
                f"/api/v1/workflows/{workflow.slug}/nodes/",
                json={"component_type": "agent", "config": {"system_prompt": "test"}},
            )
        assert resp.status_code == 409

    def test_create_node_with_label(self, auth_client, workflow):
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/nodes/",
            json={"component_type": "agent", "label": "My Agent", "config": {"system_prompt": "test"}},
        )
        assert resp.status_code == 201
        assert resp.json()["label"] == "My Agent"

    def test_create_node_duplicate_id_returns_409(self, auth_client, workflow):
        payload = {"node_id": "dup1", "component_type": "agent", "config": {"system_prompt": "test"}}
        resp1 = auth_client.post(f"/api/v1/workflows/{workflow.slug}/nodes/", json=payload)
        assert resp1.status_code == 201
        resp2 = auth_client.post(f"/api/v1/workflows/{workflow.slug}/nodes/", json=payload)
        assert resp2.status_code == 409

    def test_update_node_label(self, auth_client, workflow, node):
        resp = auth_client.patch(
            f"/api/v1/workflows/{workflow.slug}/nodes/{node.node_id}/",
            json={"label": "Renamed"},
        )
        assert resp.status_code == 200
        assert resp.json()["label"] == "Renamed"

    def test_create_human_confirmation_forces_interrupt_before(self, auth_client, workflow):
        """Creating a human_confirmation node auto-sets interrupt_before=True."""
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/nodes/",
            json={
                "node_id": "hc_1",
                "component_type": "human_confirmation",
                "config": {"extra_config": {"prompt": "Approve?"}},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["interrupt_before"] is True

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
    def _mock_env_report(self):
        return {
            "os": "Linux",
            "arch": "x86_64",
            "container": None,
            "bwrap_available": True,
            "rootfs_ready": False,
            "sandbox_mode": "bwrap",
            "capabilities": {
                "runtimes": {
                    "python3": {"available": True, "version": "3.12.0", "path": "/usr/bin/python3"},
                    "node": {"available": True, "version": "v20.0.0", "path": "/usr/bin/node"},
                    "pip3": {"available": True, "version": "pip 24.0", "path": "/usr/bin/pip3"},
                },
                "shell_tools": {"bash": {"available": True, "tier": 1}},
                "network": {"dns": True, "http": True},
            },
            "tier1_met": True,
            "tier2_warnings": [],
            "gate": {"passed": True, "blocked_reason": None},
        }

    def test_setup_status_needs_setup(self, client):
        from unittest.mock import patch

        with patch("api.auth.build_environment_report", return_value=self._mock_env_report()):
            resp = client.get("/api/v1/auth/setup-status/")
        assert resp.status_code == 200
        assert resp.json()["needs_setup"] is True

    def test_setup_status_after_user(self, client, user_profile):
        resp = client.get("/api/v1/auth/setup-status/")
        assert resp.status_code == 200
        assert resp.json()["needs_setup"] is False

    def test_setup_creates_user(self, client, tmp_path):
        from unittest.mock import patch

        with patch("api.auth.build_environment_report", return_value=self._mock_env_report()), \
             patch("api.auth.save_conf"), \
             patch("api.auth.get_pipelit_dir", return_value=tmp_path / "pipelit"):
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

    def test_setup_status_includes_environment(self, client):
        from unittest.mock import patch

        with patch("api.auth.build_environment_report", return_value=self._mock_env_report()):
            resp = client.get("/api/v1/auth/setup-status/")
        data = resp.json()
        assert data["needs_setup"] is True
        env = data["environment"]
        assert env is not None
        assert env["os"] == "Linux"
        assert env["gate"]["passed"] is True
        assert "capabilities" in env

    def test_setup_status_no_environment_after_setup(self, client, user_profile):
        resp = client.get("/api/v1/auth/setup-status/")
        data = resp.json()
        assert data["needs_setup"] is False
        assert data["environment"] is None

    def test_setup_writes_conf_json(self, client, tmp_path):
        from unittest.mock import patch, MagicMock

        mock_save = MagicMock()
        with patch("api.auth.build_environment_report", return_value=self._mock_env_report()), \
             patch("api.auth.save_conf", mock_save), \
             patch("api.auth.get_pipelit_dir", return_value=tmp_path / "pipelit"):
            resp = client.post(
                "/api/v1/auth/setup/",
                json={
                    "username": "admin",
                    "password": "admin123",
                    "log_level": "DEBUG",
                },
            )
        assert resp.status_code == 200
        mock_save.assert_called_once()
        conf = mock_save.call_args[0][0]
        assert conf.setup_completed is True
        assert conf.log_level == "DEBUG"
        assert conf.sandbox_mode == "bwrap"

    def test_setup_creates_workspace_dir(self, client, tmp_path):
        from unittest.mock import patch

        pipelit_dir = tmp_path / "pipelit"
        with patch("api.auth.build_environment_report", return_value=self._mock_env_report()), \
             patch("api.auth.save_conf"), \
             patch("api.auth.get_pipelit_dir", return_value=pipelit_dir):
            resp = client.post(
                "/api/v1/auth/setup/",
                json={"username": "admin", "password": "admin123"},
            )
        assert resp.status_code == 200
        assert (pipelit_dir / "workspaces" / "default").is_dir()

    def test_setup_recheck(self, client):
        from unittest.mock import patch

        with patch("api.auth.build_environment_report", return_value=self._mock_env_report()), \
             patch("api.auth.refresh_capabilities"):
            resp = client.post("/api/v1/auth/setup/recheck/")
        assert resp.status_code == 200
        data = resp.json()
        assert "environment" in data
        assert data["environment"]["os"] == "Linux"

    def test_setup_recheck_blocked_after_setup(self, client, user_profile):
        resp = client.post("/api/v1/auth/setup/recheck/")
        assert resp.status_code == 409

    def test_rootfs_status(self, client, tmp_path):
        from unittest.mock import patch

        with patch("api.auth.is_rootfs_ready", return_value=False), \
             patch("api.auth.get_golden_dir", return_value=tmp_path / "rootfs"):
            # Create lock file to simulate preparing
            lock_path = tmp_path / ".rootfs.lock"
            lock_path.touch()
            resp = client.get("/api/v1/auth/setup/rootfs-status/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is False
        assert data["preparing"] is True

    def test_rootfs_status_blocked_after_setup(self, client, user_profile):
        resp = client.get("/api/v1/auth/setup/rootfs-status/")
        assert resp.status_code == 409

    def test_setup_conf_write_failure(self, client, tmp_path):
        """Setup succeeds (returns API key) even if conf.json write fails."""
        from unittest.mock import patch

        with patch("api.auth.build_environment_report", return_value=self._mock_env_report()), \
             patch("api.auth.save_conf", side_effect=RuntimeError("disk full")), \
             patch("api.auth.get_pipelit_dir", return_value=tmp_path / "pipelit"):
            resp = client.post(
                "/api/v1/auth/setup/",
                json={"username": "admin", "password": "admin123"},
            )
        assert resp.status_code == 200
        assert len(resp.json()["key"]) == 36

    def test_setup_rootfs_enqueue_failure(self, client, tmp_path):
        """Setup succeeds even if rootfs enqueue fails."""
        from unittest.mock import patch, MagicMock

        with patch("api.auth.build_environment_report", return_value=self._mock_env_report()), \
             patch("api.auth.save_conf"), \
             patch("api.auth.get_pipelit_dir", return_value=tmp_path / "pipelit"), \
             patch.dict("sys.modules", {"redis": None}):
            resp = client.post(
                "/api/v1/auth/setup/",
                json={"username": "admin", "password": "admin123"},
            )
        assert resp.status_code == 200
        assert len(resp.json()["key"]) == 36


class TestPrepareRootfsJob:
    def test_prepare_rootfs_job(self):
        from unittest.mock import patch, MagicMock

        mock_result = MagicMock()
        mock_result.__str__ = lambda self: "/path/to/rootfs"

        with patch("services.rootfs.prepare_golden_image", return_value=mock_result):
            from tasks import prepare_rootfs_job
            result = prepare_rootfs_job(tier=2)

        assert result == "/path/to/rootfs"


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

    def test_delete_ai_model_node_clears_linked_config(self, auth_client, workflow, db):
        """Deleting an ai_model node should not cause StaleDataError on
        agent configs that reference it via llm_model_config_id."""
        model_cc = BaseComponentConfig(component_type="ai_model", model_name="gpt-4o")
        db.add(model_cc)
        db.flush()
        model_node = WorkflowNode(
            workflow_id=workflow.id, node_id="model1",
            component_type="ai_model", component_config_id=model_cc.id,
        )
        db.add(model_node)

        agent_cc = BaseComponentConfig(component_type="agent", system_prompt="test")
        db.add(agent_cc)
        db.flush()
        agent_node = WorkflowNode(
            workflow_id=workflow.id, node_id="agent1",
            component_type="agent", component_config_id=agent_cc.id,
        )
        db.add(agent_node)
        db.commit()

        # Link model to agent via llm edge
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/edges/",
            json={"source_node_id": "model1", "target_node_id": "agent1", "edge_label": "llm"},
        )
        assert resp.status_code == 201

        # Delete the ai_model node — should NOT raise StaleDataError
        resp = auth_client.delete(f"/api/v1/workflows/{workflow.slug}/nodes/model1/")
        assert resp.status_code == 204

        # Agent config should still exist with llm_model_config_id cleared
        db.expire_all()
        refreshed = db.query(BaseComponentConfig).filter(BaseComponentConfig.id == agent_cc.id).first()
        assert refreshed is not None
        assert refreshed.llm_model_config_id is None


# ── Credential models listing (Anthropic) ────────────────────────────────────


class TestCredentialModelsAnthropic:
    @pytest.fixture
    def llm_credential(self, db, user_profile):
        from models.credential import BaseCredential, LLMProviderCredential

        base = BaseCredential(
            user_profile_id=user_profile.id,
            name="Anthropic Key",
            credential_type="llm",
        )
        db.add(base)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=base.id,
            provider_type="anthropic",
            api_key="sk-ant-test",
        )
        db.add(llm)
        db.commit()
        db.refresh(base)
        return base

    def test_anthropic_models_live_api_success(self, auth_client, llm_credential):
        from unittest.mock import patch, MagicMock

        mock_model1 = MagicMock()
        mock_model1.id = "claude-opus-4-0-20250514"
        mock_model2 = MagicMock()
        mock_model2.id = "claude-sonnet-4-20250514"

        mock_page = MagicMock()
        mock_page.data = [mock_model2, mock_model1]  # unsorted

        mock_client = MagicMock()
        mock_client.models.list.return_value = mock_page

        mock_anthropic_cls = MagicMock(return_value=mock_client)

        # Anthropic is imported locally inside the endpoint, so patch at the module level
        with patch.dict("sys.modules", {"anthropic": MagicMock(Anthropic=mock_anthropic_cls)}):
            resp = auth_client.get(f"/api/v1/credentials/{llm_credential.id}/models/")

        assert resp.status_code == 200
        models = resp.json()
        # Should be sorted by id
        assert models[0]["id"] == "claude-opus-4-0-20250514"
        assert models[1]["id"] == "claude-sonnet-4-20250514"

    def test_anthropic_models_api_failure_falls_back(self, auth_client, llm_credential):
        from unittest.mock import patch, MagicMock

        mock_anthropic_cls = MagicMock(side_effect=RuntimeError("network error"))

        with patch.dict("sys.modules", {"anthropic": MagicMock(Anthropic=mock_anthropic_cls)}):
            resp = auth_client.get(f"/api/v1/credentials/{llm_credential.id}/models/")

        assert resp.status_code == 200
        models = resp.json()
        # Should return fallback ANTHROPIC_MODELS list
        assert len(models) >= 1
        model_ids = [m["id"] for m in models]
        assert "claude-sonnet-4-20250514" in model_ids


# ── Checkpoint metadata parsing ──────────────────────────────────────────────


class TestCheckpointMetadataParsing:
    def test_checkpoint_metadata_bytes_parsed(self, auth_client):
        """Verify list_checkpoints correctly parses bytes metadata."""
        import json
        import sqlite3
        from unittest.mock import patch, MagicMock

        # Create an in-memory SQLite DB with checkpoint data
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.execute("""
                CREATE TABLE checkpoints (
                    thread_id TEXT,
                    checkpoint_ns TEXT,
                    checkpoint_id TEXT,
                    parent_checkpoint_id TEXT,
                    type TEXT,
                    checkpoint BLOB,
                    metadata TEXT
                )
            """)
            # Insert with bytes metadata (the isinstance(metadata_raw, (str, bytes)) branch)
            meta = json.dumps({"step": 3, "source": "loop"})
            conn.execute(
                "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("thread-1", "", "cp-1", None, "json", b"blob-data", meta),
            )
            conn.commit()

            mock_checkpointer = MagicMock()
            mock_checkpointer.conn = conn

            with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
                resp = auth_client.get("/api/v1/memories/checkpoints/")

            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            item = data["items"][0]
            assert item["step"] == 3
            assert item["source"] == "loop"
        finally:
            conn.close()
