"""HTTP Request tool component — make HTTP requests."""

from __future__ import annotations

import httpx
from langchain_core.tools import tool

from components import register


@register("http_request")
def http_request_factory(node):
    """Return a LangChain tool that makes HTTP requests."""
    extra = node.component_config.extra_config or {}
    default_method = extra.get("method", "GET")
    default_headers = extra.get("headers", {})
    default_timeout = extra.get("timeout", 30)

    @tool
    def http_request(url: str, method: str = "", body: str = "") -> str:
        """Make an HTTP request. Returns status code and response body."""
        req_method = method.upper() or default_method
        try:
            resp = httpx.request(
                req_method,
                url,
                headers=default_headers,
                content=body if body else None,
                timeout=default_timeout,
            )
            truncated = resp.text[:4000] if len(resp.text) > 4000 else resp.text
            return f"HTTP {resp.status_code}\n{truncated}"
        except Exception as e:
            return f"Error: {e}"

    return http_request
