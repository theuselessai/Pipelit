"""Tests for HTTP-dependent components: platform_api, chat."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_node(component_type="test", extra_config=None, system_prompt=None):
    config = SimpleNamespace(
        component_type=component_type,
        extra_config=extra_config or {},
        system_prompt=system_prompt or "",
    )
    return SimpleNamespace(
        node_id="test_node_1",
        workflow_id=1,
        component_type=component_type,
        component_config=config,
    )


# ── Platform API ──────────────────────────────────────────────────────────────

class TestPlatformApi:
    def _get_tool(self, **extra):
        from components.platform_api import platform_api_factory
        defaults = {"api_base_url": "http://localhost:8000"}
        defaults.update(extra)
        return platform_api_factory(_make_node("platform_api", extra_config=defaults))

    @patch("components.platform_api.httpx.Client")
    def test_get_request(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"items": []}
        mock_client.get.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"method": "GET", "path": "/api/v1/workflows/", "api_key": "test-key"})
        data = json.loads(result)
        assert data["success"] is True
        assert data["status_code"] == 200

    @patch("components.platform_api.httpx.Client")
    def test_post_request(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": 1}
        mock_client.post.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"method": "POST", "path": "/api/v1/workflows/", "body": '{"name": "test"}'})
        data = json.loads(result)
        assert data["success"] is True

    @patch("components.platform_api.httpx.Client")
    def test_patch_request(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"updated": True}
        mock_client.patch.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"method": "PATCH", "path": "/api/v1/nodes/1/"})
        data = json.loads(result)
        assert data["success"] is True

    @patch("components.platform_api.httpx.Client")
    def test_delete_request(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.status_code = 204
        resp.json.return_value = {}
        mock_client.delete.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"method": "DELETE", "path": "/api/v1/workflows/1/"})
        data = json.loads(result)
        assert data["success"] is True

    def test_unsupported_method(self):
        tool = self._get_tool()
        result = tool.invoke({"method": "OPTIONS", "path": "/"})
        data = json.loads(result)
        assert "Unsupported method" in data["error"]

    @patch("components.platform_api.httpx.Client")
    def test_http_error(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.status_code = 404
        resp.json.return_value = {"detail": "Not found"}
        mock_client.get.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"method": "GET", "path": "/api/v1/missing/"})
        data = json.loads(result)
        assert data["success"] is False
        assert "HTTP 404" in data["error"]

    @patch("components.platform_api.httpx.Client")
    def test_non_json_response(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not json")
        resp.text = "plain text"
        mock_client.get.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"method": "GET", "path": "/"})
        data = json.loads(result)
        assert data["data"] == "plain text"

    @patch("components.platform_api.httpx.Client")
    def test_timeout(self, mock_cls):
        import httpx
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        tool = self._get_tool()
        result = tool.invoke({"method": "GET", "path": "/"})
        data = json.loads(result)
        assert data["success"] is False
        assert "timed out" in data["error"]

    @patch("components.platform_api.httpx.Client")
    def test_generic_exception(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = RuntimeError("boom")

        tool = self._get_tool()
        result = tool.invoke({"method": "GET", "path": "/"})
        data = json.loads(result)
        assert data["success"] is False

    @patch("components.platform_api.httpx.Client")
    def test_base_url_locked_to_config(self, mock_cls):
        """Verify that base_url uses platform config, not LLM-controlled input."""
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {}
        mock_client.get.return_value = resp

        # The tool uses settings.PLATFORM_BASE_URL (defaults to http://localhost:8000)
        # and no longer accepts a base_url parameter
        tool = self._get_tool()
        assert "base_url" not in tool.args_schema.model_fields
        tool.invoke({"method": "GET", "path": "/test"})
        mock_client.get.assert_called_once()
        url = mock_client.get.call_args[0][0]
        # Should use the platform config URL, not any LLM-provided value
        assert url == "http://localhost:8000/test"


# ── Chat Model ────────────────────────────────────────────────────────────────

class TestChatModel:
    @patch("components.chat.resolve_llm_for_node")
    def test_basic_invocation(self, mock_resolve):
        from components.chat import chat_model_factory

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Hello, I am AI"
        mock_llm.invoke.return_value = mock_response
        mock_resolve.return_value = mock_llm

        node = _make_node("chat_model", system_prompt="You are helpful.")
        fn = chat_model_factory(node)
        result = fn({"messages": []})

        assert result["output"] == "Hello, I am AI"
        assert len(result["_messages"]) == 1
        # System prompt should be prepended
        call_messages = mock_llm.invoke.call_args[0][0]
        assert call_messages[0].content == "You are helpful."

    @patch("components.chat.resolve_llm_for_node")
    def test_without_system_prompt(self, mock_resolve):
        from components.chat import chat_model_factory

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Reply"
        mock_llm.invoke.return_value = mock_response
        mock_resolve.return_value = mock_llm

        node = _make_node("chat_model", system_prompt="")
        fn = chat_model_factory(node)
        result = fn({"messages": ["hi"]})

        call_messages = mock_llm.invoke.call_args[0][0]
        # No system message prepended
        assert call_messages == ["hi"]

    @patch("components.chat.resolve_llm_for_node")
    def test_empty_messages(self, mock_resolve):
        from components.chat import chat_model_factory

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Sure"
        mock_llm.invoke.return_value = mock_response
        mock_resolve.return_value = mock_llm

        node = _make_node("chat_model")
        fn = chat_model_factory(node)
        result = fn({})  # no messages key
        assert result["output"] == "Sure"
