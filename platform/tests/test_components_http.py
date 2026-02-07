"""Tests for HTTP-dependent components: http_request, web_search, platform_api, chat."""

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


# ── HTTP Request ──────────────────────────────────────────────────────────────

class TestHttpRequest:
    def _get_tool(self, **extra):
        from components.http_request import http_request_factory
        return http_request_factory(_make_node("http_request", extra_config=extra))

    @patch("components.http_request.httpx.request")
    def test_get_request(self, mock_req):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "OK response body"
        mock_req.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"url": "https://example.com"})
        assert "HTTP 200" in result
        assert "OK response body" in result
        mock_req.assert_called_once_with("GET", "https://example.com", headers={}, content=None, timeout=30)

    @patch("components.http_request.httpx.request")
    def test_post_request(self, mock_req):
        resp = MagicMock()
        resp.status_code = 201
        resp.text = '{"id": 1}'
        mock_req.return_value = resp

        tool = self._get_tool(method="POST", headers={"X-Key": "val"}, timeout=10)
        result = tool.invoke({"url": "https://api.example.com", "body": '{"x": 1}'})
        assert "HTTP 201" in result
        mock_req.assert_called_once_with(
            "POST", "https://api.example.com", headers={"X-Key": "val"},
            content='{"x": 1}', timeout=10,
        )

    @patch("components.http_request.httpx.request")
    def test_method_override(self, mock_req):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        mock_req.return_value = resp

        tool = self._get_tool(method="GET")
        tool.invoke({"url": "https://x.com", "method": "PUT"})
        mock_req.assert_called_once()
        assert mock_req.call_args[0][0] == "PUT"

    @patch("components.http_request.httpx.request")
    def test_truncation(self, mock_req):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "x" * 5000
        mock_req.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"url": "https://x.com"})
        # Should truncate to 4000 chars + "HTTP 200\n"
        assert len(result) < 4100

    @patch("components.http_request.httpx.request", side_effect=Exception("conn refused"))
    def test_error_handling(self, mock_req):
        tool = self._get_tool()
        result = tool.invoke({"url": "https://x.com"})
        assert "Error: conn refused" in result


# ── Web Search ────────────────────────────────────────────────────────────────

class TestWebSearch:
    def _get_tool(self, **extra):
        from components.web_search import web_search_factory
        defaults = {"searxng_url": "http://localhost:8888"}
        defaults.update(extra)
        return web_search_factory(_make_node("web_search", extra_config=defaults))

    @patch("components.web_search.httpx.get")
    def test_returns_results(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "results": [
                {"title": "Result 1", "url": "https://r1.com", "content": "Content one"},
                {"title": "Result 2", "url": "https://r2.com", "content": "Content two"},
            ]
        }
        mock_get.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"query": "test query"})
        assert "Result 1" in result
        assert "Result 2" in result
        assert "https://r1.com" in result

    @patch("components.web_search.httpx.get")
    def test_no_results(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"results": []}
        mock_get.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"query": "obscure query"})
        assert "No results found" in result

    @patch("components.web_search.httpx.get")
    def test_max_5_results(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "results": [
                {"title": f"R{i}", "url": f"https://r{i}.com", "content": f"Content {i}"}
                for i in range(10)
            ]
        }
        mock_get.return_value = resp

        tool = self._get_tool()
        result = tool.invoke({"query": "test"})
        # Only 5 results
        assert "R4" in result
        assert "R5" not in result

    @patch("components.web_search.httpx.get", side_effect=Exception("timeout"))
    def test_error(self, mock_get):
        tool = self._get_tool()
        result = tool.invoke({"query": "test"})
        assert "Search error" in result

    @patch("components.web_search.httpx.get")
    def test_custom_searxng_url(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"results": []}
        mock_get.return_value = resp

        tool = self._get_tool(searxng_url="http://custom:9999/")
        tool.invoke({"query": "q"})
        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0]
        assert call_url == "http://custom:9999/search"


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
    def test_custom_base_url(self, mock_cls):
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {}
        mock_client.get.return_value = resp

        tool = self._get_tool()
        tool.invoke({"method": "GET", "path": "/test", "base_url": "http://custom:9000/"})
        mock_client.get.assert_called_once()
        url = mock_client.get.call_args[0][0]
        assert url == "http://custom:9000/test"


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
