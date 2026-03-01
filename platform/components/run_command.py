"""Run Command tool component — sandboxed subprocess execution."""

from __future__ import annotations

import logging
import subprocess

from langchain_core.tools import tool

from components import register

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 300  # seconds
_MAX_OUTPUT_CHARS = 50_000


def _resolve_parent_workspace(node) -> dict:
    """Find the parent agent's workspace config by tracing tool edges.

    Returns the parent agent's extra_config dict (or empty dict).
    """
    try:
        from database import SessionLocal
        from models.node import WorkflowEdge, WorkflowNode

        db = SessionLocal()
        try:
            # Find edges where this tool is the source and edge_label is "tool"
            tool_edge = (
                db.query(WorkflowEdge)
                .filter(
                    WorkflowEdge.workflow_id == node.workflow_id,
                    WorkflowEdge.source_node_id == node.node_id,
                    WorkflowEdge.edge_label == "tool",
                )
                .first()
            )
            if tool_edge:
                parent = (
                    db.query(WorkflowNode)
                    .filter_by(
                        workflow_id=node.workflow_id,
                        node_id=tool_edge.target_node_id,
                    )
                    .first()
                )
                if parent:
                    cfg = parent.component_config
                    return getattr(cfg, "extra_config", None) or {}
        finally:
            db.close()
    except Exception:
        logger.debug("run_command: failed to resolve parent workspace", exc_info=True)
    return {}


@register("run_command")
def run_command_factory(node):
    """Return a LangChain tool that runs shell commands, sandboxed when possible."""

    extra = node.component_config.extra_config or {}
    timeout = int(extra.get("timeout", _DEFAULT_TIMEOUT))

    # Try to resolve workspace from parent agent
    parent_extra = _resolve_parent_workspace(node)
    workspace_id = parent_extra.get("workspace_id")

    # Build sandbox backend if a workspace is available
    backend = None
    if workspace_id:
        try:
            from components._agent_shared import _build_backend
            backend = _build_backend(parent_extra)
            logger.info("run_command %s: using sandbox backend (workspace_id=%s)", node.node_id, workspace_id)
        except Exception:
            logger.warning("run_command %s: failed to build sandbox backend, falling back to subprocess", node.node_id, exc_info=True)

    @tool
    def run_command(command: str) -> str:
        """Run a shell command and return stdout/stderr."""
        try:
            if backend is not None:
                resp = backend.execute(command, timeout=timeout)
                output = resp.output or ""
                if resp.exit_code is not None and resp.exit_code != 0:
                    output += f"\n[exit code: {resp.exit_code}]"
                output = output or "(no output)"
            else:
                return "Error: No sandbox backend available. run_command requires a workspace with sandbox support."

            if len(output) > _MAX_OUTPUT_CHARS:
                half = _MAX_OUTPUT_CHARS // 2
                output = (
                    output[:half]
                    + f"\n\n... ({len(output) - _MAX_OUTPUT_CHARS} chars truncated) ...\n\n"
                    + output[-half:]
                )
            return output
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {timeout} seconds"
        except Exception as e:
            return f"Error: {e}"

    return run_command
