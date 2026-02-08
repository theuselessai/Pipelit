"""Extended API tests for credentials, executions, users, workflows, and memory endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.credential import BaseCredential, LLMProviderCredential, TelegramCredential
from models.execution import ExecutionLog, WorkflowExecution
from models.node import BaseComponentConfig, WorkflowNode
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

    def test_create_telegram_credential(self, auth_client):
        resp = auth_client.post("/api/v1/credentials/", json={
            "name": "My Bot",
            "credential_type": "telegram",
            "detail": {
                "bot_token": "123456:ABC-DEF",
                "allowed_user_ids": "111,222",
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


# ── Users ────────────────────────────────────────────────────────────────────

class TestUsersAPI:
    def test_list_agent_users_empty(self, auth_client):
        resp = auth_client.get("/api/v1/users/agents/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_agent_users(self, auth_client, db):
        import bcrypt
        agent = UserProfile(
            username="agent-bot",
            password_hash=bcrypt.hashpw(b"random", bcrypt.gensalt()).decode(),
            is_agent=True,
            first_name="Test Agent",
        )
        db.add(agent)
        db.flush()
        key = APIKey(user_id=agent.id)
        db.add(key)
        db.commit()

        resp = auth_client.get("/api/v1/users/agents/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["username"] == "agent-bot"

    def test_delete_agent_user(self, auth_client, db):
        import bcrypt
        agent = UserProfile(
            username="agent-to-delete",
            password_hash=bcrypt.hashpw(b"random", bcrypt.gensalt()).decode(),
            is_agent=True,
        )
        db.add(agent)
        db.flush()
        key = APIKey(user_id=agent.id)
        db.add(key)
        db.commit()

        resp = auth_client.delete(f"/api/v1/users/agents/{agent.id}/")
        assert resp.status_code == 204

    def test_delete_agent_user_not_found(self, auth_client):
        resp = auth_client.delete("/api/v1/users/agents/99999/")
        assert resp.status_code == 404

    def test_batch_delete_agent_users(self, auth_client, db):
        import bcrypt
        agent = UserProfile(
            username="agent-batch-del",
            password_hash=bcrypt.hashpw(b"random", bcrypt.gensalt()).decode(),
            is_agent=True,
        )
        db.add(agent)
        db.commit()

        resp = auth_client.post("/api/v1/users/agents/batch-delete/", json={
            "ids": [agent.id],
        })
        assert resp.status_code == 204


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

    def test_setup_status(self, client):
        resp = client.get("/api/v1/auth/setup-status/")
        assert resp.status_code == 200

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
            credential_type="telegram",
        )
        db.add(cred)
        db.flush()
        tg = TelegramCredential(
            base_credentials_id=cred.id,
            bot_token="123456:ABC-DEF-GHI-JKL",
            allowed_user_ids="111,222",
        )
        db.add(tg)
        db.commit()

        resp = auth_client.get(f"/api/v1/credentials/{cred.id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert "****" in data["detail"]["bot_token"]

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


# ── Chat endpoint ────────────────────────────────────────────────────────────

class TestChatAPI:
    @pytest.fixture
    def chat_trigger(self, db, workflow):
        cc = BaseComponentConfig(
            component_type="trigger_chat",
            trigger_config={},
            is_active=True,
        )
        db.add(cc)
        db.flush()
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="chat_trigger_1",
            component_type="trigger_chat",
            component_config_id=cc.id,
        )
        db.add(node)
        db.commit()
        db.refresh(node)
        return node

    def test_chat_no_trigger(self, auth_client, workflow):
        resp = auth_client.post(f"/api/v1/workflows/{workflow.slug}/chat/", json={
            "text": "hello",
        })
        assert resp.status_code == 404

    def test_chat_workflow_not_found(self, auth_client):
        resp = auth_client.post("/api/v1/workflows/nonexistent/chat/", json={
            "text": "hello",
        })
        assert resp.status_code == 404

    def test_chat_with_trigger_node_id(self, auth_client, workflow, chat_trigger):
        """Chat with specific trigger_node_id — mock Redis enqueue."""
        mock_q = MagicMock()
        mock_conn = MagicMock()
        with patch("redis.from_url", return_value=mock_conn):
            with patch("rq.Queue", return_value=mock_q):
                resp = auth_client.post(f"/api/v1/workflows/{workflow.slug}/chat/", json={
                    "text": "hello",
                    "trigger_node_id": "chat_trigger_1",
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        mock_q.enqueue.assert_called_once()


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
