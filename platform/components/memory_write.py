"""Memory Write component — store information in agent memory."""

from __future__ import annotations

import logging

from components import register
from database import SessionLocal
from services.memory import MemoryService

logger = logging.getLogger(__name__)


@register("memory_write")
def memory_write_factory(node):
    """Return a graph node function that writes to memory."""
    extra = node.component_config.extra_config or {}
    node_id = node.node_id

    fact_type = extra.get("fact_type", "world_knowledge")
    scope = extra.get("scope", "agent")
    overwrite = extra.get("overwrite", True)

    def memory_write_node(state: dict) -> dict:
        # Get inputs from state
        node_outputs = state.get("node_outputs", {})

        # Look for key and value in node_outputs from connected nodes
        key = None
        value = None

        for out in node_outputs.values():
            if isinstance(out, dict):
                if "key" in out and key is None:
                    key = out["key"]
                if "value" in out and value is None:
                    value = out["value"]
                # Also check for memory_key/memory_value pattern
                if "memory_key" in out and key is None:
                    key = out["memory_key"]
                if "memory_value" in out and value is None:
                    value = out["memory_value"]

        # Also check trigger for direct inputs
        trigger = state.get("trigger", {})
        if key is None:
            key = trigger.get("memory_key") or trigger.get("key")
        if value is None:
            value = trigger.get("memory_value") or trigger.get("value")

        if not key:
            return {
                "node_outputs": {
                    node_id: {
                        "success": False,
                        "action": "failed",
                        "error": "Key is required for memory write",
                    }
                }
            }

        if value is None:
            return {
                "node_outputs": {
                    node_id: {
                        "success": False,
                        "action": "failed",
                        "error": "Value is required for memory write",
                    }
                }
            }

        # Get context for scoping
        user_context = state.get("user_context", {})
        execution_id = state.get("execution_id", "")

        # Derive identifiers from execution context
        agent_id = f"workflow:{execution_id.split('-')[0]}" if execution_id else "default"
        user_id = user_context.get("canonical_id") or user_context.get("user_id")
        session_id = execution_id

        # Validate scope requirements
        if scope == "user" and not user_id:
            return {
                "node_outputs": {
                    node_id: {
                        "success": False,
                        "action": "failed",
                        "error": "User scope requires user_id in context",
                    }
                }
            }

        if scope == "session" and not session_id:
            return {
                "node_outputs": {
                    node_id: {
                        "success": False,
                        "action": "failed",
                        "error": "Session scope requires session_id in context",
                    }
                }
            }

        db = SessionLocal()
        try:
            memory = MemoryService(db)

            fact = memory.set_fact(
                key=key,
                value=value,
                fact_type=fact_type,
                scope=scope,
                agent_id=agent_id if scope in ("agent", "global") else None,
                user_id=user_id if scope == "user" else None,
                session_id=session_id if scope == "session" else None,
                source_episode_id=None,  # Will be linked when episode logging is enabled
                overwrite=overwrite,
            )

            action = "updated" if fact.times_confirmed > 1 else "created"
            if not overwrite and fact.times_confirmed > 1:
                action = "skipped"

            return {
                "node_outputs": {
                    node_id: {
                        "success": True,
                        "action": action,
                        "fact_id": fact.id,
                    }
                }
            }

        except Exception as e:
            logger.exception("Memory write error")
            return {
                "node_outputs": {
                    node_id: {
                        "success": False,
                        "action": "failed",
                        "error": str(e),
                    }
                }
            }
        finally:
            db.close()

    return memory_write_node
