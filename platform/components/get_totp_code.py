"""Get TOTP Code tool component — allows agents to retrieve their current TOTP code."""

from __future__ import annotations

import json
import logging

import pyotp
from langchain_core.tools import tool

from components import register
from database import SessionLocal
from models.user import UserProfile

logger = logging.getLogger(__name__)


@register("get_totp_code")
def get_totp_code_factory(node):
    """Return a LangChain @tool that retrieves the agent's current TOTP code."""

    tool_workflow_id = node.workflow_id
    tool_node_id = node.node_id

    @tool
    def get_totp_code(username: str = "") -> str:
        """Get the current TOTP code for an agent user.

        If no username is provided, attempts to find the agent user
        associated with this workflow/node.

        Args:
            username: The agent username to get TOTP code for (optional).

        Returns:
            JSON string with the current TOTP code and username.
        """
        db = SessionLocal()
        try:
            if username:
                user = db.query(UserProfile).filter(
                    UserProfile.username == username,
                    UserProfile.is_agent == True,  # noqa: E712
                ).first()
            else:
                # Try to find agent user for this workflow/node
                from models.node import WorkflowEdge
                from models.workflow import Workflow

                edge = (
                    db.query(WorkflowEdge)
                    .filter(
                        WorkflowEdge.workflow_id == tool_workflow_id,
                        WorkflowEdge.source_node_id == tool_node_id,
                        WorkflowEdge.edge_label == "tool",
                    )
                    .first()
                )
                if edge:
                    agent_node_id = edge.target_node_id
                    workflow = db.query(Workflow).filter(Workflow.id == tool_workflow_id).first()
                    workflow_slug = workflow.slug if workflow else str(tool_workflow_id)
                else:
                    agent_node_id = tool_node_id
                    workflow_slug = str(tool_workflow_id)

                agent_username = f"agent_{workflow_slug}_{agent_node_id}"
                user = db.query(UserProfile).filter(
                    UserProfile.username == agent_username,
                ).first()

            if not user:
                return json.dumps({"success": False, "error": "Agent user not found"})

            if not user.totp_secret:
                return json.dumps({"success": False, "error": "No TOTP secret configured for this user"})

            code = pyotp.TOTP(user.totp_secret).now()
            return json.dumps({
                "success": True,
                "username": user.username,
                "totp_code": code,
            })

        except Exception as e:
            logger.exception("Error getting TOTP code")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    return get_totp_code
