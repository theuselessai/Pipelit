"""Tests for mcp_server.py — MCP tool wrappers around platform API."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We test the helper functions and MCP tool functions directly


# ── Config / auth helpers ─────────────────────────────────────────────────────

class TestLoadApiKey:
    def test_from_env(self):
        from mcp_server import _load_api_key
        with patch.dict(os.environ, {"PLATFORM_API_KEY": "env-key"}):
            assert _load_api_key() == "env-key"

    def test_from_config_file(self, tmp_path):
        from mcp_server import _load_api_key
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"api_key": "file-key"}))

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLATFORM_API_KEY", None)
            with patch("mcp_server.CONFIG_PATH", config_file):
                assert _load_api_key() == "file-key"

    def test_empty_when_nothing(self, tmp_path):
        from mcp_server import _load_api_key
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLATFORM_API_KEY", None)
            with patch("mcp_server.CONFIG_PATH", tmp_path / "nonexistent.json"):
                assert _load_api_key() == ""


class TestSaveApiKey:
    def test_creates_new_file(self, tmp_path):
        from mcp_server import _save_api_key
        config_file = tmp_path / "subdir" / "config.json"

        with patch("mcp_server.CONFIG_PATH", config_file):
            _save_api_key("test-key-123")

        data = json.loads(config_file.read_text())
        assert data["api_key"] == "test-key-123"

    def test_updates_existing_file(self, tmp_path):
        from mcp_server import _save_api_key
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"other": "data"}))

        with patch("mcp_server.CONFIG_PATH", config_file):
            _save_api_key("new-key")

        data = json.loads(config_file.read_text())
        assert data["api_key"] == "new-key"
        assert data["other"] == "data"  # preserved


class TestHeaders:
    def test_with_key(self):
        from mcp_server import _headers
        with patch("mcp_server._load_api_key", return_value="my-key"):
            h = _headers()
            assert h["Authorization"] == "Bearer my-key"
            assert h["Content-Type"] == "application/json"

    def test_without_key(self):
        from mcp_server import _headers
        with patch("mcp_server._load_api_key", return_value=""):
            h = _headers()
            assert "Authorization" not in h


class TestUrl:
    def test_url_construction(self):
        from mcp_server import _url
        with patch("mcp_server.BASE_URL", "http://localhost:8000"):
            assert _url("/workflows/") == "http://localhost:8000/api/v1/workflows/"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

class TestHttpHelpers:
    @pytest.mark.asyncio
    async def test_get_success(self):
        from mcp_server import _get
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"items": []}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
            with patch("mcp_server._headers", return_value={"Content-Type": "application/json"}):
                result = await _get("/workflows/")
                assert result == {"items": []}

    @pytest.mark.asyncio
    async def test_get_error(self):
        from mcp_server import _get
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
            with patch("mcp_server._headers", return_value={}):
                result = await _get("/workflows/")
                assert "error" in result
                assert result["status_code"] == 401

    @pytest.mark.asyncio
    async def test_post_success(self):
        from mcp_server import _post
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
            with patch("mcp_server._headers", return_value={}):
                result = await _post("/workflows/", {"name": "test"})
                assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_post_error(self):
        from mcp_server import _post
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "Validation error"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
            with patch("mcp_server._headers", return_value={}):
                result = await _post("/workflows/")
                assert result["status_code"] == 422

    @pytest.mark.asyncio
    async def test_patch_success(self):
        from mcp_server import _patch
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"updated": True}

        mock_client = AsyncMock()
        mock_client.patch.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
            with patch("mcp_server._headers", return_value={}):
                result = await _patch("/workflows/test/", {"name": "new"})
                assert result == {"updated": True}

    @pytest.mark.asyncio
    async def test_delete_204(self):
        from mcp_server import _delete
        mock_resp = MagicMock()
        mock_resp.status_code = 204

        mock_client = AsyncMock()
        mock_client.delete.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
            with patch("mcp_server._headers", return_value={}):
                result = await _delete("/workflows/test/")
                assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_delete_with_body(self):
        from mcp_server import _delete
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"deleted": True}

        mock_client = AsyncMock()
        mock_client.delete.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
            with patch("mcp_server._headers", return_value={}):
                result = await _delete("/workflows/test/")
                assert result == {"deleted": True}

    @pytest.mark.asyncio
    async def test_delete_error(self):
        from mcp_server import _delete
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not found"

        mock_client = AsyncMock()
        mock_client.delete.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
            with patch("mcp_server._headers", return_value={}):
                result = await _delete("/workflows/test/")
                assert result["status_code"] == 404


# ── MCP tool functions ────────────────────────────────────────────────────────

class TestMcpTools:
    @pytest.mark.asyncio
    async def test_platform_login_success(self):
        from mcp_server import platform_login
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"key": "api-key-123"}
            with patch("mcp_server._save_api_key") as mock_save:
                result = json.loads(await platform_login("user", "pass"))
                assert result["ok"] is True
                mock_save.assert_called_once_with("api-key-123")

    @pytest.mark.asyncio
    async def test_platform_login_failure(self):
        from mcp_server import platform_login
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"error": "Invalid credentials"}
            result = json.loads(await platform_login("user", "bad"))
            assert "error" in result

    @pytest.mark.asyncio
    async def test_platform_setup_success(self):
        from mcp_server import platform_setup
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"key": "setup-key"}
            with patch("mcp_server._save_api_key") as mock_save:
                result = json.loads(await platform_setup("admin", "secret"))
                assert result["ok"] is True
                mock_save.assert_called_once_with("setup-key")

    @pytest.mark.asyncio
    async def test_platform_setup_failure(self):
        from mcp_server import platform_setup
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"error": "Already set up"}
            result = json.loads(await platform_setup("admin", "secret"))
            assert "error" in result

    @pytest.mark.asyncio
    async def test_list_workflows(self):
        from mcp_server import list_workflows
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"items": [{"slug": "wf1"}], "total": 1}
            result = json.loads(await list_workflows())
            assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_get_workflow(self):
        from mcp_server import get_workflow
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"slug": "test-wf", "nodes": []}
            result = json.loads(await get_workflow("test-wf"))
            assert result["slug"] == "test-wf"

    @pytest.mark.asyncio
    async def test_list_nodes(self):
        from mcp_server import list_nodes
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"items": []}
            result = json.loads(await list_nodes("wf1"))
            mock_get.assert_called_once_with("/workflows/wf1/nodes/")

    @pytest.mark.asyncio
    async def test_list_edges(self):
        from mcp_server import list_edges
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"items": []}
            result = json.loads(await list_edges("wf1"))
            mock_get.assert_called_once_with("/workflows/wf1/edges/")

    @pytest.mark.asyncio
    async def test_list_credentials(self):
        from mcp_server import list_credentials
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"items": []}
            await list_credentials()
            mock_get.assert_called_once_with("/credentials/")

    @pytest.mark.asyncio
    async def test_get_node_types(self):
        from mcp_server import get_node_types
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"agent": {}}
            await get_node_types()
            mock_get.assert_called_once_with("/workflows/node-types/")

    @pytest.mark.asyncio
    async def test_list_executions_no_filter(self):
        from mcp_server import list_executions
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"items": []}
            await list_executions()
            mock_get.assert_called_once_with("/executions/", params={})

    @pytest.mark.asyncio
    async def test_list_executions_with_filter(self):
        from mcp_server import list_executions
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"items": []}
            await list_executions(workflow_slug="wf1", status="running")
            mock_get.assert_called_once_with("/executions/", params={"workflow_slug": "wf1", "status": "running"})

    @pytest.mark.asyncio
    async def test_get_execution(self):
        from mcp_server import get_execution
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"id": "exec-1"}
            await get_execution("exec-1")
            mock_get.assert_called_once_with("/executions/exec-1/")

    @pytest.mark.asyncio
    async def test_get_chat_history(self):
        from mcp_server import get_chat_history
        with patch("mcp_server._get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"messages": []}
            await get_chat_history("wf1", limit=5)
            mock_get.assert_called_once_with("/workflows/wf1/chat/history", params={"limit": 5})

    @pytest.mark.asyncio
    async def test_create_node(self):
        from mcp_server import create_node
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"node_id": "agent_1"}
            result = json.loads(await create_node("wf1", "agent_1", "agent", 100, 200, {"system_prompt": "hi"}))
            body = mock_post.call_args[0][1]
            assert body["node_id"] == "agent_1"
            assert body["component_type"] == "agent"
            assert body["position_x"] == 100
            assert body["config"] == {"system_prompt": "hi"}

    @pytest.mark.asyncio
    async def test_create_node_no_config(self):
        from mcp_server import create_node
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {}
            await create_node("wf1", "n1", "agent")
            body = mock_post.call_args[0][1]
            assert "config" not in body

    @pytest.mark.asyncio
    async def test_update_node(self):
        from mcp_server import update_node
        with patch("mcp_server._patch", new_callable=AsyncMock) as mock_patch:
            mock_patch.return_value = {}
            await update_node("wf1", "n1", config={"system_prompt": "new"}, position_x=50)
            body = mock_patch.call_args[0][1]
            assert body["config"] == {"system_prompt": "new"}
            assert body["position_x"] == 50
            assert "position_y" not in body

    @pytest.mark.asyncio
    async def test_update_node_empty(self):
        from mcp_server import update_node
        with patch("mcp_server._patch", new_callable=AsyncMock) as mock_patch:
            mock_patch.return_value = {}
            await update_node("wf1", "n1")
            body = mock_patch.call_args[0][1]
            assert body == {}

    @pytest.mark.asyncio
    async def test_delete_node(self):
        from mcp_server import delete_node
        with patch("mcp_server._delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = {"ok": True}
            await delete_node("wf1", "n1")
            mock_delete.assert_called_once_with("/workflows/wf1/nodes/n1/")

    @pytest.mark.asyncio
    async def test_create_edge(self):
        from mcp_server import create_edge
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"id": 1}
            await create_edge("wf1", "n1", "n2", edge_type="conditional", condition_value="yes")
            body = mock_post.call_args[0][1]
            assert body["source_node_id"] == "n1"
            assert body["target_node_id"] == "n2"
            assert body["edge_type"] == "conditional"
            assert body["condition_value"] == "yes"

    @pytest.mark.asyncio
    async def test_create_edge_with_mapping(self):
        from mcp_server import create_edge
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {}
            await create_edge("wf1", "n1", "n2", condition_mapping={"a": "b"})
            body = mock_post.call_args[0][1]
            assert body["condition_mapping"] == {"a": "b"}

    @pytest.mark.asyncio
    async def test_update_edge(self):
        from mcp_server import update_edge
        with patch("mcp_server._patch", new_callable=AsyncMock) as mock_patch:
            mock_patch.return_value = {}
            await update_edge("wf1", 5, edge_type="direct", edge_label="llm")
            mock_patch.assert_called_once()
            body = mock_patch.call_args[0][1]
            assert body["edge_type"] == "direct"
            assert body["edge_label"] == "llm"

    @pytest.mark.asyncio
    async def test_delete_edge(self):
        from mcp_server import delete_edge
        with patch("mcp_server._delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = {"ok": True}
            await delete_edge("wf1", 5)
            mock_delete.assert_called_once_with("/workflows/wf1/edges/5/")

    @pytest.mark.asyncio
    async def test_validate_workflow(self):
        from mcp_server import validate_workflow
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"valid": True}
            result = json.loads(await validate_workflow("wf1"))
            assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_send_chat_message(self):
        from mcp_server import send_chat_message
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"execution_id": "e1"}
            result = json.loads(await send_chat_message("wf1", "Hello!", "trigger_chat_1"))
            body = mock_post.call_args[0][1]
            assert body["text"] == "Hello!"
            assert body["trigger_node_id"] == "trigger_chat_1"

    @pytest.mark.asyncio
    async def test_send_chat_message_no_trigger(self):
        from mcp_server import send_chat_message
        with patch("mcp_server._post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {}
            await send_chat_message("wf1", "Hi")
            body = mock_post.call_args[0][1]
            assert "trigger_node_id" not in body
