"""Identify User component — identify who is talking and load their context."""

from __future__ import annotations

import logging

from components import register
from database import SessionLocal
from services.memory import MemoryService

logger = logging.getLogger(__name__)


@register("identify_user")
def identify_user_factory(node):
    """Return a graph node function that identifies the user and loads their context."""
    node_id = node.node_id

    def identify_user_node(state: dict) -> dict:
        # Get trigger payload and channel
        trigger = state.get("trigger", {})
        node_outputs = state.get("node_outputs", {})

        # Try to get trigger_input and channel from connected nodes first
        trigger_input = trigger
        channel = "unknown"

        for out in node_outputs.values():
            if isinstance(out, dict):
                if "trigger_input" in out:
                    trigger_input = out["trigger_input"]
                if "channel" in out:
                    channel = out["channel"]

        # Fallback to infer channel from trigger payload
        if channel == "unknown":
            if "message" in trigger_input and "from" in trigger_input.get("message", {}):
                channel = "telegram"
            elif "webhook_id" in trigger_input:
                channel = "webhook"
            elif trigger_input.get("source") == "manual":
                channel = "manual"
            elif trigger_input.get("source") == "chat":
                channel = "chat"

        # Extract channel-specific identifier
        channel_id = None
        display_name = None

        if channel == "telegram":
            msg = trigger_input.get("message", {})
            from_user = msg.get("from", {})
            channel_id = str(from_user.get("id", ""))
            display_name = from_user.get("first_name", "")
            if from_user.get("last_name"):
                display_name += f" {from_user['last_name']}"

        elif channel == "webhook":
            channel_id = trigger_input.get("user_id") or trigger_input.get("email") or "anonymous"
            display_name = trigger_input.get("user_name") or trigger_input.get("name")

        elif channel in ("manual", "chat"):
            channel_id = trigger_input.get("user_id") or "manual_user"
            display_name = trigger_input.get("user_name") or "Manual User"

        else:
            channel_id = trigger_input.get("user_id") or "unknown"
            display_name = trigger_input.get("user_name")

        if not channel_id:
            return {
                "node_outputs": {
                    node_id: {
                        "user_id": None,
                        "user_context": {"is_new": True, "facts": [], "history": []},
                        "is_new_user": True,
                        "error": f"Could not extract user ID from {channel} trigger",
                    }
                },
                "user_context": {
                    "is_new": True,
                    "channel": channel,
                },
            }

        # Derive agent_id from execution context
        execution_id = state.get("execution_id", "")
        agent_id = f"workflow:{execution_id.split('-')[0]}" if execution_id else "default"

        db = SessionLocal()
        try:
            memory = MemoryService(db)

            # Get or create user
            user = memory.get_or_create_user(
                channel=channel,
                channel_id=channel_id,
                display_name=display_name,
            )

            is_new = user.total_conversations == 0

            # Update conversation count
            memory.increment_user_conversations(user.canonical_id)

            # Get full context
            user_context = memory.get_user_context(
                user_id=user.canonical_id,
                agent_id=agent_id,
            )

            return {
                "node_outputs": {
                    node_id: {
                        "user_id": user.canonical_id,
                        "user_context": user_context,
                        "is_new_user": is_new,
                    }
                },
                # Also update the global user_context in state for other nodes
                "user_context": {
                    **user_context,
                    "canonical_id": user.canonical_id,
                    "display_name": display_name,
                    "channel": channel,
                },
            }

        except Exception as e:
            logger.exception("Identify user error")
            return {
                "node_outputs": {
                    node_id: {
                        "user_id": None,
                        "user_context": {"is_new": True, "facts": [], "history": []},
                        "is_new_user": True,
                        "error": str(e),
                    }
                },
                "user_context": {
                    "is_new": True,
                    "channel": channel,
                    "error": str(e),
                },
            }
        finally:
            db.close()

    return identify_user_node
