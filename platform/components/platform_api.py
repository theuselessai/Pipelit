"""Platform API tool component — allows agents to interact with the platform API."""

from __future__ import annotations

import json
import logging

import httpx
from langchain_core.tools import tool

from components import register

logger = logging.getLogger(__name__)


@register("platform_api")
def platform_api_factory(node):
    """Return a LangChain @tool that makes authenticated requests to the platform API."""
    from config import settings
    default_base_url = settings.PLATFORM_BASE_URL

    @tool
    def platform_api(
        method: str = "GET",
        path: str = "/openapi.json",
        body: str = "",
        api_key: str = "",
    ) -> str:
        """Make authenticated requests to the platform API.

        To discover available endpoints, first call with path="/openapi.json" to get
        the full API schema. Then use the schema to construct requests.

        The base URL is locked to the platform address and cannot be overridden.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            path: API path (e.g., "/openapi.json", "/api/v1/workflows/", "/api/v1/auth/me/")
            body: JSON body for POST/PATCH requests (as string)
            api_key: API key from create_agent_user tool

        Returns:
            JSON response from the API, or error message.

        Example workflow:
            1. Call create_agent_user to get credentials
            2. Call platform_api(path="/openapi.json", api_key="...") to discover endpoints
            3. Call platform_api(method="GET", path="/api/v1/workflows/", api_key="...") to list workflows
            4. Call platform_api(method="PATCH", path="/api/v1/workflows/my-workflow/nodes/123/",
                                 body='{"config": {"system_prompt": "new prompt"}}', api_key="...")
        """
        resolved_base_url = default_base_url.rstrip("/")
        url = f"{resolved_base_url}{path}"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            with httpx.Client(timeout=30) as client:
                if method.upper() == "GET":
                    resp = client.get(url, headers=headers)
                elif method.upper() == "POST":
                    resp = client.post(url, headers=headers, content=body or "{}")
                elif method.upper() == "PATCH":
                    resp = client.patch(url, headers=headers, content=body or "{}")
                elif method.upper() == "DELETE":
                    resp = client.delete(url, headers=headers)
                else:
                    return json.dumps({"error": f"Unsupported method: {method}"})

                # Try to parse as JSON
                try:
                    data = resp.json()
                except Exception:
                    data = resp.text

                result = {
                    "status_code": resp.status_code,
                    "success": 200 <= resp.status_code < 300,
                    "data": data,
                }

                if resp.status_code >= 400:
                    result["error"] = f"HTTP {resp.status_code}"

                return json.dumps(result, indent=2, default=str)

        except httpx.TimeoutException:
            return json.dumps({"error": "Request timed out", "success": False})
        except Exception as e:
            logger.exception("Platform API request failed")
            return json.dumps({"error": str(e), "success": False})

    return platform_api
