"""Extended API tests for credentials, executions, users, workflows, and memory endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.credential import BaseCredential, GatewayCredential, LLMProviderCredential
from models.execution import ExecutionLog, WorkflowExecution
from models.user import APIKey, UserProfile
from models.workflow import Workflow


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


# ── Credentials ──────────────────────────────────────────────────────────────

class TestCredentialsAPI:
    def test_list_credentials_empty(self, auth_client):
        resp = auth_client.get("/api/v1/credentials/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_create_llm_credential(self, auth_client):
        resp = auth_client.post("/api/v1/credentials/", json={
            "name": "My OpenAI",
            "credential_type": "llm",
            "detail": {
                "provider_type": "openai",
                "api_key": "sk-1234567890abcdef",
                "base_url": "",
            },
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My OpenAI"
        assert data["credential_type"] == "llm"

    def test_create_gateway_credential(self, auth_client):
        mock_client = MagicMock()
        mock_client.create_credential.return_value = {"id": "Gateway Bot", "status": "created"}
        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post("/api/v1/credentials/", json={
                "name": "Gateway Bot",
                "credential_type": "gateway",
                "detail": {
                    "adapter_type": "telegram",
                    "token": "bot456:TOKEN",
                },
            })
        assert resp.status_code == 201

    def test_create_tool_credential(self, auth_client):
        resp = auth_client.post("/api/v1/credentials/", json={
            "name": "SearXNG",
            "credential_type": "tool",
            "detail": {
                "tool_type": "searxng",
                "config": {"url": "http://searx.local"},
            },
        })
        assert resp.status_code == 201

    def test_list_credentials(self, auth_client, db, user_profile):
        cred = BaseCredential(user_profile_id=user_profile.id, name="Test", credential_type="llm")
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id,
            provider_type="openai",
            api_key="sk-1234567890abcdef",
        )
        db.add(llm)
        db.commit()

        resp = auth_client.get("/api/v1/credentials/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        item = data["items"][0]
        assert item["detail"]["provider_type"] == "openai"
        assert "****" in item["detail"]["api_key"]

    def test_get_credential(self, auth_client, db, user_profile):
        cred = BaseCredential(user_profile_id=user_profile.id, name="Test", credential_type="llm")
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id,
            provider_type="openai",
            api_key="sk-1234567890abcdef",
        )
        db.add(llm)
        db.commit()

        resp = auth_client.get(f"/api/v1/credentials/{cred.id}/")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test"

    def test_get_credential_not_found(self, auth_client):
        resp = auth_client.get("/api/v1/credentials/99999/")
        assert resp.status_code == 404

    def test_update_credential(self, auth_client, db, user_profile):
        cred = BaseCredential(user_profile_id=user_profile.id, name="Old Name", credential_type="llm")
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id,
            provider_type="openai",
            api_key="sk-old",
        )
        db.add(llm)
        db.commit()

        resp = auth_client.patch(f"/api/v1/credentials/{cred.id}/", json={
            "name": "New Name",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_delete_credential(self, auth_client, db, user_profile):
        cred = BaseCredential(user_profile_id=user_profile.id, name="To Delete", credential_type="llm")
        db.add(cred)
        db.commit()

        resp = auth_client.delete(f"/api/v1/credentials/{cred.id}/")
        assert resp.status_code == 204

    def test_batch_delete_credentials(self, auth_client, db, user_profile):
        cred1 = BaseCredential(user_profile_id=user_profile.id, name="A", credential_type="llm")
        cred2 = BaseCredential(user_profile_id=user_profile.id, name="B", credential_type="llm")
        db.add_all([cred1, cred2])
        db.commit()

        resp = auth_client.post("/api/v1/credentials/batch-delete/", json={
            "ids": [cred1.id, cred2.id],
        })
        assert resp.status_code == 204

    def test_mask_function(self):
        from api.credentials import _mask
        assert _mask("") == "****"
        assert _mask("short") == "****"
        assert _mask("abcdefghijklmnop") == "abcd****mnop"

    def _make_llm_cred(self, db, user_profile, provider_type="openai", base_url="", api_key="sk-test"):
        cred = BaseCredential(user_profile_id=user_profile.id, name="Test LLM", credential_type="llm")
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id,
            provider_type=provider_type,
            api_key=api_key,
            base_url=base_url,
        )
        db.add(llm)
        db.commit()
        db.refresh(cred)
        return cred

    def test_list_models_openai_dict_response(self, auth_client, db, user_profile):
        """OpenAI-compatible /models returns dict with 'data' key — lines 345-346."""
        cred = self._make_llm_cred(db, user_profile, provider_type="openai")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "data": [{"id": "gpt-4"}, {"id": "gpt-3.5-turbo"}]
        }

        with patch("api.credentials.httpx.get", return_value=mock_resp):
            resp = auth_client.get(f"/api/v1/credentials/{cred.id}/models/")

        assert resp.status_code == 200
        data = resp.json()
        ids = [m["id"] for m in data]
        assert "gpt-4" in ids
        assert "gpt-3.5-turbo" in ids

    def test_list_models_openai_list_response(self, auth_client, db, user_profile):
        """OpenAI-compatible /models returns a list directly — lines 347-348."""
        cred = self._make_llm_cred(db, user_profile, provider_type="openai",
                                   base_url="https://custom.openai.com/v1")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = [{"id": "custom-model-1"}, {"id": "custom-model-2"}]

        with patch("api.credentials.httpx.get", return_value=mock_resp):
            resp = auth_client.get(f"/api/v1/credentials/{cred.id}/models/")

        assert resp.status_code == 200
        data = resp.json()
        ids = [m["id"] for m in data]
        assert "custom-model-1" in ids

    def test_list_models_unexpected_format_returns_empty(self, auth_client, db, user_profile):
        """Unexpected /models response format (not dict, not list) — lines 349-351."""
        cred = self._make_llm_cred(db, user_profile, provider_type="openai")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = "unexpected string response"

        with patch("api.credentials.httpx.get", return_value=mock_resp):
            resp = auth_client.get(f"/api/v1/credentials/{cred.id}/models/")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_models_openai_default_url_on_exception(self, auth_client, db, user_profile):
        """Non-MiniMax exception returns [] — line 357."""
        cred = self._make_llm_cred(db, user_profile, provider_type="openai", base_url="")

        with patch("api.credentials.httpx.get", side_effect=Exception("connection error")):
            resp = auth_client.get(f"/api/v1/credentials/{cred.id}/models/")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_models_minimax_fallback_on_exception(self, auth_client, db, user_profile):
        """MiniMax base_url exception returns MINIMAX_MODELS — lines 355-356."""
        from api.credentials import MINIMAX_MODELS
        cred = self._make_llm_cred(
            db, user_profile, provider_type="openai",
            base_url="https://api.minimax.io/v1",
        )

        with patch("api.credentials.httpx.get", side_effect=Exception("timeout")):
            resp = auth_client.get(f"/api/v1/credentials/{cred.id}/models/")

        assert resp.status_code == 200
        data = resp.json()
        returned_ids = [m["id"] for m in data]
        assert returned_ids == MINIMAX_MODELS

    def test_list_models_no_base_url_uses_openai_default(self, auth_client, db, user_profile):
        """No base_url defaults to https://api.openai.com/v1 — line 336."""
        cred = self._make_llm_cred(db, user_profile, provider_type="openai", base_url="")

        captured_url = []

        def mock_get(url, **kwargs):
            captured_url.append(url)
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"data": [{"id": "gpt-4"}]}
            return resp

        with patch("api.credentials.httpx.get", side_effect=mock_get):
            resp = auth_client.get(f"/api/v1/credentials/{cred.id}/models/")

        assert resp.status_code == 200
        assert captured_url[0] == "https://api.openai.com/v1/models"


# ── Executions ───────────────────────────────────────────────────────────────

class TestExecutionsAPI:
    def test_list_executions_empty(self, auth_client):
        resp = auth_client.get("/api/v1/executions/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_executions(self, auth_client, db, workflow, user_profile):
        _make_execution(db, workflow, user_profile, status="completed")
        resp = auth_client.get("/api/v1/executions/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_executions_with_filter(self, auth_client, db, workflow, user_profile):
        _make_execution(db, workflow, user_profile, status="completed")
        _make_execution(db, workflow, user_profile, status="failed")

        resp = auth_client.get("/api/v1/executions/?status=completed")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_executions_by_slug(self, auth_client, db, workflow, user_profile):
        _make_execution(db, workflow, user_profile, status="completed")
        resp = auth_client.get(f"/api/v1/executions/?workflow_slug={workflow.slug}")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_get_execution(self, auth_client, db, workflow, user_profile):
        execution = _make_execution(db, workflow, user_profile, status="completed")
        resp = auth_client.get(f"/api/v1/executions/{execution.execution_id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_id"] == str(execution.execution_id)

    def test_get_execution_not_found(self, auth_client):
        resp = auth_client.get("/api/v1/executions/nonexistent-id/")
        assert resp.status_code == 404

    def test_cancel_execution(self, auth_client, db, workflow, user_profile):
        execution = _make_execution(db, workflow, user_profile, status="running")
        resp = auth_client.post(f"/api/v1/executions/{execution.execution_id}/cancel/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_execution_not_found(self, auth_client):
        resp = auth_client.post("/api/v1/executions/nonexistent-id/cancel/")
        assert resp.status_code == 404

    def test_batch_delete_executions(self, auth_client, db, workflow, user_profile):
        e1 = _make_execution(db, workflow, user_profile, status="completed")
        e2 = _make_execution(db, workflow, user_profile, status="failed")

        resp = auth_client.post("/api/v1/executions/batch-delete/", json={
            "execution_ids": [str(e1.execution_id), str(e2.execution_id)],
        })
        assert resp.status_code == 204

    def test_batch_delete_empty(self, auth_client):
        resp = auth_client.post("/api/v1/executions/batch-delete/", json={
            "execution_ids": [],
        })
        assert resp.status_code == 204

    def test_batch_delete_only_deletes_owned_executions(self, auth_client, db, workflow, user_profile):
        """Only executions from workflows owned by the current user are deleted.

        Exercises the Workflow ownership join in batch_delete_executions.
        Uses normal role so admin bypass doesn't apply.
        """
        import bcrypt

        from models.user import UserRole
        user_profile.role = UserRole.NORMAL
        db.commit()

        # Execution from the authenticated user's workflow
        owned_exec = _make_execution(db, workflow, user_profile, status="completed")

        # Create a second user with their own workflow and execution
        other_user = UserProfile(
            username="other-user",
            password_hash=bcrypt.hashpw(b"pass", bcrypt.gensalt()).decode(),
        )
        db.add(other_user)
        db.flush()
        other_wf = Workflow(name="Other WF", slug="other-wf", owner_id=other_user.id, is_active=True)
        db.add(other_wf)
        db.flush()
        other_exec = _make_execution(db, other_wf, other_user, status="completed")

        resp = auth_client.post("/api/v1/executions/batch-delete/", json={
            "execution_ids": [
                str(owned_exec.execution_id),
                str(other_exec.execution_id),
            ],
        })
        assert resp.status_code == 204

        # Owned execution should be deleted
        from models.execution import WorkflowExecution as WE
        assert db.query(WE).filter(WE.execution_id == owned_exec.execution_id).first() is None
        # Other user's execution must remain (not owned by auth user)
        assert db.query(WE).filter(WE.execution_id == other_exec.execution_id).first() is not None


# ── Workflows ────────────────────────────────────────────────────────────────

class TestWorkflowsExtendedAPI:
    def test_list_workflows(self, auth_client, workflow):
        resp = auth_client.get("/api/v1/workflows/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_get_workflow(self, auth_client, workflow):
        resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/")
        assert resp.status_code == 200
        assert resp.json()["slug"] == workflow.slug

    def test_get_workflow_not_found(self, auth_client):
        resp = auth_client.get("/api/v1/workflows/nonexistent/")
        assert resp.status_code == 404

    def test_create_workflow(self, auth_client):
        resp = auth_client.post("/api/v1/workflows/", json={
            "name": "New Workflow",
            "slug": "new-workflow",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "New Workflow"
        assert data["slug"] == "new-workflow"

    def test_delete_workflow(self, auth_client, db, user_profile):
        wf = Workflow(name="To Delete", slug="to-delete", owner_id=user_profile.id, is_active=True)
        db.add(wf)
        db.commit()

        resp = auth_client.delete(f"/api/v1/workflows/{wf.slug}/")
        assert resp.status_code == 204

    def test_node_types(self, auth_client):
        resp = auth_client.get("/api/v1/workflows/node-types/")
        assert resp.status_code == 200
        data = resp.json()
        # Returns a dict of node type specs
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_validate_workflow(self, auth_client, workflow):
        resp = auth_client.post(f"/api/v1/workflows/{workflow.slug}/validate/")
        assert resp.status_code == 200


# ── Auth ─────────────────────────────────────────────────────────────────────

class TestAuthAPI:
    def test_me_unauthorized(self, client):
        resp = client.get("/api/v1/auth/me/")
        assert resp.status_code in (401, 403)

    def test_me_authorized(self, auth_client, user_profile):
        resp = auth_client.get("/api/v1/auth/me/")
        assert resp.status_code == 200
        assert resp.json()["username"] == user_profile.username

    def test_login_wrong_credentials(self, client):
        resp = client.post("/api/v1/auth/token/", json={
            "username": "wrong",
            "password": "wrong",
        })
        assert resp.status_code in (401, 422)


# ── Memory API ───────────────────────────────────────────────────────────────

class TestMemoryAPI:
    def test_list_facts_empty(self, auth_client):
        resp = auth_client.get("/api/v1/memories/facts/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_list_facts(self, auth_client, db):
        from models.memory import MemoryFact
        fact = MemoryFact(
            agent_id="global", scope="global", key="favorite_color",
            value="blue", fact_type="preference",
        )
        db.add(fact)
        db.commit()

        resp = auth_client.get("/api/v1/memories/facts/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_facts_with_filter(self, auth_client, db):
        from models.memory import MemoryFact
        fact = MemoryFact(
            agent_id="global", scope="global", key="test",
            value="val", fact_type="preference",
        )
        db.add(fact)
        db.commit()

        resp = auth_client.get("/api/v1/memories/facts/?scope=global&fact_type=preference")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_batch_delete_facts(self, auth_client, db):
        from models.memory import MemoryFact
        fact = MemoryFact(
            agent_id="global", scope="global", key="temp",
            value="v", fact_type="preference",
        )
        db.add(fact)
        db.commit()
        db.refresh(fact)

        resp = auth_client.post("/api/v1/memories/facts/batch-delete/", json={
            "ids": [str(fact.id)],
        })
        assert resp.status_code == 204

    def test_batch_delete_facts_empty(self, auth_client):
        resp = auth_client.post("/api/v1/memories/facts/batch-delete/", json={"ids": []})
        assert resp.status_code == 204

    def test_list_episodes_empty(self, auth_client):
        resp = auth_client.get("/api/v1/memories/episodes/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_episodes(self, auth_client, db):
        from models.memory import MemoryEpisode
        ep = MemoryEpisode(agent_id="global")
        db.add(ep)
        db.commit()

        resp = auth_client.get("/api/v1/memories/episodes/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_episodes_filter_agent(self, auth_client, db):
        from models.memory import MemoryEpisode
        ep = MemoryEpisode(agent_id="agent-1")
        db.add(ep)
        db.commit()

        resp = auth_client.get("/api/v1/memories/episodes/?agent_id=agent-1")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_batch_delete_episodes(self, auth_client, db):
        from models.memory import MemoryEpisode
        ep = MemoryEpisode(agent_id="global")
        db.add(ep)
        db.commit()
        db.refresh(ep)

        resp = auth_client.post("/api/v1/memories/episodes/batch-delete/", json={
            "ids": [str(ep.id)],
        })
        assert resp.status_code == 204

    def test_list_procedures_empty(self, auth_client):
        resp = auth_client.get("/api/v1/memories/procedures/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_procedures(self, auth_client, db):
        from models.memory import MemoryProcedure
        proc = MemoryProcedure(agent_id="global", name="test_proc", procedure_content="do something", procedure_type="manual")
        db.add(proc)
        db.commit()

        resp = auth_client.get("/api/v1/memories/procedures/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_batch_delete_procedures(self, auth_client, db):
        from models.memory import MemoryProcedure
        proc = MemoryProcedure(agent_id="global", name="test_proc", procedure_content="do something", procedure_type="manual")
        db.add(proc)
        db.commit()
        db.refresh(proc)

        resp = auth_client.post("/api/v1/memories/procedures/batch-delete/", json={
            "ids": [str(proc.id)],
        })
        assert resp.status_code == 204

    def test_list_users_empty(self, auth_client):
        resp = auth_client.get("/api/v1/memories/users/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_users(self, auth_client, db):
        from models.memory import MemoryUser
        user = MemoryUser(display_name="Test User", canonical_id="tg_123")
        db.add(user)
        db.commit()

        resp = auth_client.get("/api/v1/memories/users/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_batch_delete_users(self, auth_client, db):
        from models.memory import MemoryUser
        user = MemoryUser(display_name="Test User", canonical_id="tg_456")
        db.add(user)
        db.commit()
        db.refresh(user)

        resp = auth_client.post("/api/v1/memories/users/batch-delete/", json={
            "ids": [str(user.id)],
        })
        assert resp.status_code == 204


# ── Credential serialization ────────────────────────────────────────────────

class TestCredentialSerialization:
    def test_serialize_telegram(self, auth_client, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="TG Bot",
            credential_type="gateway",
        )
        db.add(cred)
        db.flush()
        gw = GatewayCredential(
            base_credentials_id=cred.id,
            gateway_credential_id="tg_mybot",
            adapter_type="telegram",
        )
        db.add(gw)
        db.commit()

        resp = auth_client.get(f"/api/v1/credentials/{cred.id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["detail"]["gateway_credential_id"] == "tg_mybot"

    def test_update_credential_detail(self, auth_client, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="LLM Cred",
            credential_type="llm",
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id,
            provider_type="openai",
            api_key="sk-old1234567890",
        )
        db.add(llm)
        db.commit()

        resp = auth_client.patch(f"/api/v1/credentials/{cred.id}/", json={
            "detail": {"api_key": "sk-new1234567890"},
        })
        assert resp.status_code == 200

    def test_create_git_credential(self, auth_client):
        resp = auth_client.post("/api/v1/credentials/", json={
            "name": "GitHub",
            "credential_type": "git",
            "detail": {
                "provider": "github",
                "credential_type": "token",
                "access_token": "ghp_1234567890abcdef",
            },
        })
        assert resp.status_code == 201


# ── Gateway credential sync ──────────────────────────────────────────────────

class TestGatewayCredentialSync:
    """Tests for gateway credential CRUD synced with msg-gateway admin API."""

    def _make_gateway_cred(self, db, user_profile, name="My Bot", gw_id="tg_mybot", adapter="telegram"):
        cred = BaseCredential(
            user_profile_id=user_profile.id,
            name=name,
            credential_type="gateway",
        )
        db.add(cred)
        db.flush()
        gw = GatewayCredential(
            base_credentials_id=cred.id,
            gateway_credential_id=gw_id,
            adapter_type=adapter,
        )
        db.add(gw)
        db.commit()
        db.refresh(cred)
        return cred

    # -- create ---------------------------------------------------------------

    def test_create_gateway_credential_calls_gateway(self, auth_client):
        """Creating a gateway credential should call gateway.create_credential()."""
        mock_client = MagicMock()
        mock_client.create_credential.return_value = {"id": "tg_newbot", "status": "created"}

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post("/api/v1/credentials/", json={
                "name": "New Bot",
                "credential_type": "gateway",
                "detail": {
                    "adapter_type": "telegram",
                    "token": "bot123:TOKEN",
                    "config": {"webhook_url": "https://example.com/hook"},
                },
            })

        assert resp.status_code == 201
        data = resp.json()
        assert data["credential_type"] == "gateway"
        assert data["detail"]["adapter_type"] == "telegram"
        mock_client.create_credential.assert_called_once()
        call_kwargs = mock_client.create_credential.call_args
        assert call_kwargs.kwargs.get("adapter") == "telegram" or call_kwargs.args[1] == "telegram"

    def test_create_gateway_credential_gateway_unavailable_returns_502(self, auth_client):
        """If gateway is unavailable during create, return 502."""
        from services.gateway_client import GatewayUnavailableError

        mock_client = MagicMock()
        mock_client.create_credential.side_effect = GatewayUnavailableError("connection refused")

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post("/api/v1/credentials/", json={
                "name": "Bot",
                "credential_type": "gateway",
                "detail": {
                    "adapter_type": "telegram",
                    "token": "bot123:TOKEN",
                },
            })

        assert resp.status_code == 502

    def test_create_gateway_credential_gateway_api_error_returns_502(self, auth_client):
        """If gateway returns 4xx/5xx during create, return 502."""
        from services.gateway_client import GatewayAPIError

        mock_client = MagicMock()
        mock_client.create_credential.side_effect = GatewayAPIError(409, "already exists")

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post("/api/v1/credentials/", json={
                "name": "Bot",
                "credential_type": "gateway",
                "detail": {
                    "adapter_type": "telegram",
                    "token": "bot123:TOKEN",
                },
            })

        assert resp.status_code == 502

    def test_create_gateway_credential_token_not_stored_locally(self, auth_client, db):
        """Token must NOT be stored in local DB — only sent to gateway."""
        mock_client = MagicMock()
        mock_client.create_credential.return_value = {"id": "tg_bot", "status": "created"}

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post("/api/v1/credentials/", json={
                "name": "Secret Bot",
                "credential_type": "gateway",
                "detail": {
                    "adapter_type": "telegram",
                    "token": "super_secret_token",
                },
            })

        assert resp.status_code == 201
        cred_id = resp.json()["id"]

        # Verify token is NOT in the serialized response
        get_resp = auth_client.get(f"/api/v1/credentials/{cred_id}/")
        assert "super_secret_token" not in str(get_resp.json())

        # Verify GatewayCredential in DB has no token field
        gw = db.query(GatewayCredential).filter_by(base_credentials_id=cred_id).first()
        assert gw is not None
        assert not hasattr(gw, "token") or not getattr(gw, "token", None)

    # -- delete ---------------------------------------------------------------

    def test_delete_gateway_credential_calls_gateway(self, auth_client, db, user_profile):
        """Deleting a gateway credential should call gateway.delete_credential()."""
        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.delete_credential.return_value = {"id": "tg_mybot", "status": "deleted"}

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.delete(f"/api/v1/credentials/{cred.id}/")

        assert resp.status_code == 204
        mock_client.delete_credential.assert_called_once_with("tg_mybot")

    def test_delete_gateway_credential_gateway_fails_returns_502(self, auth_client, db, user_profile):
        """If gateway delete fails, return 502 and do NOT delete local record."""
        from services.gateway_client import GatewayAPIError

        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.delete_credential.side_effect = GatewayAPIError(500, "internal error")

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.delete(f"/api/v1/credentials/{cred.id}/")

        assert resp.status_code == 502
        # Local record should still exist
        still_exists = db.query(BaseCredential).filter_by(id=cred.id).first()
        assert still_exists is not None

    def test_delete_non_gateway_credential_no_gateway_call(self, auth_client, db, user_profile):
        """Deleting a non-gateway credential should NOT call gateway."""
        cred = BaseCredential(user_profile_id=user_profile.id, name="LLM", credential_type="llm")
        db.add(cred)
        db.commit()

        mock_client = MagicMock()
        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.delete(f"/api/v1/credentials/{cred.id}/")

        assert resp.status_code == 204
        mock_client.delete_credential.assert_not_called()

    # -- update ---------------------------------------------------------------

    def test_update_gateway_credential_token_calls_gateway(self, auth_client, db, user_profile):
        """Updating token on a gateway credential should call gateway.update_credential()."""
        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.update_credential.return_value = {"id": "tg_mybot", "status": "updated"}

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.patch(f"/api/v1/credentials/{cred.id}/", json={
                "detail": {"token": "new_bot_token"},
            })

        assert resp.status_code == 200
        mock_client.update_credential.assert_called_once()
        call_args = mock_client.update_credential.call_args
        assert call_args.args[0] == "tg_mybot"
        assert call_args.kwargs.get("token") == "new_bot_token"

    def test_update_gateway_credential_adapter_type_updates_local_and_gateway(self, auth_client, db, user_profile):
        """Updating adapter_type should update local DB and call gateway."""
        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.update_credential.return_value = {"id": "tg_mybot", "status": "updated"}

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.patch(f"/api/v1/credentials/{cred.id}/", json={
                "detail": {"adapter_type": "whatsapp"},
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["detail"]["adapter_type"] == "whatsapp"
        mock_client.update_credential.assert_called_once()

    def test_update_gateway_credential_gateway_fails_returns_502(self, auth_client, db, user_profile):
        """If gateway update fails, return 502."""
        from services.gateway_client import GatewayUnavailableError

        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.update_credential.side_effect = GatewayUnavailableError("timeout")

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.patch(f"/api/v1/credentials/{cred.id}/", json={
                "detail": {"token": "new_token"},
            })

        assert resp.status_code == 502

    # -- test -----------------------------------------------------------------

    def test_test_gateway_credential_health_found(self, auth_client, db, user_profile):
        """Testing a gateway credential returns health info when found."""
        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.check_credential_health.return_value = {
            "credential_id": "tg_mybot",
            "adapter": "telegram",
            "health": "ok",
            "failures": 0,
        }

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post(f"/api/v1/credentials/{cred.id}/test/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "health" in str(data.get("detail", ""))
        mock_client.check_credential_health.assert_called_once_with("tg_mybot")

    def test_test_gateway_credential_health_not_found(self, auth_client, db, user_profile):
        """Testing a gateway credential returns ok=False when not found in gateway."""
        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.check_credential_health.return_value = None

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post(f"/api/v1/credentials/{cred.id}/test/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "not found" in data.get("detail", "").lower()

    # -- activate/deactivate --------------------------------------------------

    def test_activate_gateway_credential(self, auth_client, db, user_profile):
        """POST /credentials/{id}/activate/ calls gateway.activate_credential()."""
        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.activate_credential.return_value = {"id": "tg_mybot", "status": "activated"}

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post(f"/api/v1/credentials/{cred.id}/activate/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "activated"
        mock_client.activate_credential.assert_called_once_with("tg_mybot")

    def test_deactivate_gateway_credential(self, auth_client, db, user_profile):
        """POST /credentials/{id}/deactivate/ calls gateway.deactivate_credential()."""
        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.deactivate_credential.return_value = {"id": "tg_mybot", "status": "deactivated"}

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post(f"/api/v1/credentials/{cred.id}/deactivate/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deactivated"
        mock_client.deactivate_credential.assert_called_once_with("tg_mybot")

    def test_activate_non_gateway_credential_returns_404(self, auth_client, db, user_profile):
        """Activating a non-gateway credential returns 404."""
        cred = BaseCredential(user_profile_id=user_profile.id, name="LLM", credential_type="llm")
        db.add(cred)
        db.commit()

        resp = auth_client.post(f"/api/v1/credentials/{cred.id}/activate/")
        assert resp.status_code == 404

    def test_deactivate_non_gateway_credential_returns_404(self, auth_client, db, user_profile):
        """Deactivating a non-gateway credential returns 404."""
        cred = BaseCredential(user_profile_id=user_profile.id, name="LLM", credential_type="llm")
        db.add(cred)
        db.commit()

        resp = auth_client.post(f"/api/v1/credentials/{cred.id}/deactivate/")
        assert resp.status_code == 404

    def test_activate_credential_not_found_returns_404(self, auth_client):
        """Activating a non-existent credential returns 404."""
        resp = auth_client.post("/api/v1/credentials/99999/activate/")
        assert resp.status_code == 404

    def test_deactivate_credential_not_found_returns_404(self, auth_client):
        """Deactivating a non-existent credential returns 404."""
        resp = auth_client.post("/api/v1/credentials/99999/deactivate/")
        assert resp.status_code == 404

    def test_activate_gateway_unavailable_returns_502(self, auth_client, db, user_profile):
        """If gateway is unavailable during activate, return 502."""
        from services.gateway_client import GatewayUnavailableError

        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.activate_credential.side_effect = GatewayUnavailableError("down")

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post(f"/api/v1/credentials/{cred.id}/activate/")

        assert resp.status_code == 502

    def test_deactivate_gateway_api_error_returns_502(self, auth_client, db, user_profile):
        """If gateway returns error during deactivate, return 502."""
        from services.gateway_client import GatewayAPIError

        cred = self._make_gateway_cred(db, user_profile)

        mock_client = MagicMock()
        mock_client.deactivate_credential.side_effect = GatewayAPIError(500, "server error")

        with patch("api.credentials.get_gateway_client", return_value=mock_client):
            resp = auth_client.post(f"/api/v1/credentials/{cred.id}/deactivate/")

        assert resp.status_code == 502


# ── Workflow batch operations ────────────────────────────────────────────────

class TestWorkflowBatchOps:
    def test_batch_delete_workflows(self, auth_client, db, user_profile):
        wf1 = Workflow(name="W1", slug="w1", owner_id=user_profile.id, is_active=True)
        wf2 = Workflow(name="W2", slug="w2", owner_id=user_profile.id, is_active=True)
        db.add_all([wf1, wf2])
        db.commit()

        resp = auth_client.post("/api/v1/workflows/batch-delete/", json={
            "slugs": ["w1", "w2"],
        })
        assert resp.status_code == 204

    def test_batch_delete_workflows_empty(self, auth_client):
        resp = auth_client.post("/api/v1/workflows/batch-delete/", json={
            "slugs": [],
        })
        assert resp.status_code == 204
