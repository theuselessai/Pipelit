"""MCP server for the aichat platform API.

Run: python platform/mcp_server.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

CONFIG_PATH = Path.home() / ".config" / "aichat-platform" / "config.json"
BASE_URL = os.environ.get("PLATFORM_BASE_URL", "http://localhost:8000")

mcp = FastMCP("aichat-platform")


# ── Platform HTTP client ─────────────────────────────────────────────────────


def _load_api_key() -> str:
    key = os.environ.get("PLATFORM_API_KEY", "")
    if key:
        return key
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        return data.get("api_key", "")
    return ""


def _save_api_key(key: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
    data["api_key"] = key
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def _headers() -> dict[str, str]:
    key = _load_api_key()
    h: dict[str, str] = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _url(path: str) -> str:
    return f"{BASE_URL}/api/v1{path}"


async def _get(path: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_url(path), headers=_headers(), params=params)
        if resp.status_code >= 400:
            return {"error": resp.text, "status_code": resp.status_code}
        return resp.json()


async def _post(path: str, body: dict | None = None) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(_url(path), headers=_headers(), json=body or {})
        if resp.status_code >= 400:
            return {"error": resp.text, "status_code": resp.status_code}
        return resp.json()


async def _patch(path: str, body: dict) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.patch(_url(path), headers=_headers(), json=body)
        if resp.status_code >= 400:
            return {"error": resp.text, "status_code": resp.status_code}
        return resp.json()


async def _delete(path: str) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(_url(path), headers=_headers())
        if resp.status_code == 204:
            return {"ok": True}
        if resp.status_code >= 400:
            return {"error": resp.text, "status_code": resp.status_code}
        return resp.json()


# ── Auth tools ───────────────────────────────────────────────────────────────


@mcp.tool()
async def platform_login(username: str, password: str) -> str:
    """Log in to the platform and save the API key.

    Args:
        username: Platform username
        password: Platform password
    """
    result = await _post("/auth/token/", {"username": username, "password": password})
    if "key" in result:
        _save_api_key(result["key"])
        return json.dumps({"ok": True, "message": "Logged in and API key saved."})
    return json.dumps(result)


@mcp.tool()
async def platform_setup(username: str, password: str) -> str:
    """Bootstrap the first user (only works if no users exist).

    Args:
        username: Username for the new admin
        password: Password for the new admin
    """
    result = await _post("/auth/setup/", {"username": username, "password": password})
    if "key" in result:
        _save_api_key(result["key"])
        return json.dumps({"ok": True, "message": "Setup complete and API key saved."})
    return json.dumps(result)


# ── Read tools ───────────────────────────────────────────────────────────────


@mcp.tool()
async def list_workflows() -> str:
    """List all workflows the authenticated user can access."""
    result = await _get("/workflows/")
    return json.dumps(result, default=str)


@mcp.tool()
async def get_workflow(slug: str) -> str:
    """Get full workflow detail including all nodes and edges.

    Args:
        slug: Workflow slug (URL-friendly identifier)
    """
    result = await _get(f"/workflows/{slug}/")
    return json.dumps(result, default=str)


@mcp.tool()
async def list_nodes(slug: str) -> str:
    """List all nodes in a workflow.

    Args:
        slug: Workflow slug
    """
    result = await _get(f"/workflows/{slug}/nodes/")
    return json.dumps(result, default=str)


@mcp.tool()
async def list_edges(slug: str) -> str:
    """List all edges (connections) in a workflow.

    Args:
        slug: Workflow slug
    """
    result = await _get(f"/workflows/{slug}/edges/")
    return json.dumps(result, default=str)


@mcp.tool()
async def list_credentials() -> str:
    """List all credentials (API keys are masked)."""
    result = await _get("/credentials/")
    return json.dumps(result, default=str)


@mcp.tool()
async def get_node_types() -> str:
    """Get all available component types with their port definitions and schemas."""
    result = await _get("/workflows/node-types/")
    return json.dumps(result, default=str)


@mcp.tool()
async def list_executions(workflow_slug: str | None = None, status: str | None = None) -> str:
    """List workflow executions, optionally filtered.

    Args:
        workflow_slug: Filter by workflow (optional)
        status: Filter by status: pending, running, completed, failed, cancelled (optional)
    """
    params: dict[str, str] = {}
    if workflow_slug:
        params["workflow_slug"] = workflow_slug
    if status:
        params["status"] = status
    result = await _get("/executions/", params=params)
    return json.dumps(result, default=str)


@mcp.tool()
async def get_execution(execution_id: str) -> str:
    """Get execution detail including logs.

    Args:
        execution_id: Execution UUID
    """
    result = await _get(f"/executions/{execution_id}/")
    return json.dumps(result, default=str)


@mcp.tool()
async def get_chat_history(slug: str, limit: int = 10) -> str:
    """Get chat message history for a workflow.

    Args:
        slug: Workflow slug
        limit: Max messages to return (default 10)
    """
    result = await _get(f"/workflows/{slug}/chat/history", params={"limit": limit})
    return json.dumps(result, default=str)


# ── Write tools ──────────────────────────────────────────────────────────────


@mcp.tool()
async def create_node(
    slug: str,
    component_type: str,
    node_id: str | None = None,
    position_x: int = 0,
    position_y: int = 0,
    config: dict | None = None,
) -> str:
    """Create a new node in a workflow.

    Args:
        slug: Workflow slug
        component_type: Node type (agent, ai_model, trigger_chat, run_command, etc.)
        node_id: Unique node identifier (optional — auto-generated as "{type}_{hex}" if omitted)
        position_x: Canvas X position
        position_y: Canvas Y position
        config: ComponentConfigData dict with system_prompt, extra_config, llm_credential_id, model_name, etc.
    """
    body: dict[str, Any] = {
        "component_type": component_type,
        "position_x": position_x,
        "position_y": position_y,
    }
    if node_id:
        body["node_id"] = node_id
    if config:
        body["config"] = config
    result = await _post(f"/workflows/{slug}/nodes/", body)
    return json.dumps(result, default=str)


@mcp.tool()
async def update_node(
    slug: str,
    node_id: str,
    config: dict | None = None,
    position_x: int | None = None,
    position_y: int | None = None,
    label: str | None = None,
) -> str:
    """Update an existing node's configuration.

    Args:
        slug: Workflow slug
        node_id: The node_id to update
        config: ComponentConfigData fields to update (system_prompt, extra_config, model_name, etc.)
        position_x: New canvas X position (optional)
        position_y: New canvas Y position (optional)
        label: Display label for the node (optional)
    """
    body: dict[str, Any] = {}
    if config:
        body["config"] = config
    if position_x is not None:
        body["position_x"] = position_x
    if position_y is not None:
        body["position_y"] = position_y
    if label is not None:
        body["label"] = label
    result = await _patch(f"/workflows/{slug}/nodes/{node_id}/", body)
    return json.dumps(result, default=str)


@mcp.tool()
async def delete_node(slug: str, node_id: str) -> str:
    """Delete a node and all its connected edges.

    Args:
        slug: Workflow slug
        node_id: The node_id to delete
    """
    result = await _delete(f"/workflows/{slug}/nodes/{node_id}/")
    return json.dumps(result, default=str)


@mcp.tool()
async def create_edge(
    slug: str,
    source_node_id: str,
    target_node_id: str,
    edge_type: str = "direct",
    edge_label: str = "",
    condition_mapping: dict | None = None,
    condition_value: str = "",
) -> str:
    """Connect two nodes with an edge.

    Args:
        slug: Workflow slug
        source_node_id: Source node_id
        target_node_id: Target node_id
        edge_type: "direct" or "conditional"
        edge_label: "" for data flow, "llm" for model connection, "tool" for tool connection, "output_parser" for parser
        condition_mapping: For conditional edges, a dict mapping route values to target node_ids (e.g. {"chat": "agent_chat", "research": "agent_research"})
        condition_value: For conditional edges from switch nodes, the route value this edge matches (e.g. "chat", "research")
    """
    body: dict[str, Any] = {
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "edge_type": edge_type,
        "edge_label": edge_label,
    }
    if condition_mapping is not None:
        body["condition_mapping"] = condition_mapping
    if condition_value:
        body["condition_value"] = condition_value
    result = await _post(f"/workflows/{slug}/edges/", body)
    return json.dumps(result, default=str)


@mcp.tool()
async def update_edge(
    slug: str,
    edge_id: int,
    condition_mapping: dict | None = None,
    edge_type: str | None = None,
    edge_label: str | None = None,
) -> str:
    """Update an existing edge's properties.

    Args:
        slug: Workflow slug
        edge_id: Edge database ID
        condition_mapping: For conditional edges, a dict mapping route values to target node_ids
        edge_type: "direct" or "conditional"
        edge_label: "" for data flow, "llm" for model connection, etc.
    """
    body: dict[str, Any] = {}
    if condition_mapping is not None:
        body["condition_mapping"] = condition_mapping
    if edge_type is not None:
        body["edge_type"] = edge_type
    if edge_label is not None:
        body["edge_label"] = edge_label
    result = await _patch(f"/workflows/{slug}/edges/{edge_id}/", body)
    return json.dumps(result, default=str)


@mcp.tool()
async def delete_edge(slug: str, edge_id: int) -> str:
    """Remove a connection between nodes.

    Args:
        slug: Workflow slug
        edge_id: Edge database ID
    """
    result = await _delete(f"/workflows/{slug}/edges/{edge_id}/")
    return json.dumps(result, default=str)


@mcp.tool()
async def validate_workflow(slug: str) -> str:
    """Check structural validity of a workflow (edges, required inputs, etc.).

    Args:
        slug: Workflow slug
    """
    result = await _post(f"/workflows/{slug}/validate/")
    return json.dumps(result, default=str)


# ── Execute tools ────────────────────────────────────────────────────────────


@mcp.tool()
async def send_chat_message(slug: str, text: str, trigger_node_id: str | None = None) -> str:
    """Send a chat message to a workflow's chat trigger and start execution.

    Args:
        slug: Workflow slug
        text: Message text
        trigger_node_id: Specific chat trigger node_id (optional, uses first chat trigger if omitted)
    """
    body: dict[str, Any] = {"text": text}
    if trigger_node_id:
        body["trigger_node_id"] = trigger_node_id
    result = await _post(f"/workflows/{slug}/chat/", body)
    return json.dumps(result, default=str)


if __name__ == "__main__":
    mcp.run()
