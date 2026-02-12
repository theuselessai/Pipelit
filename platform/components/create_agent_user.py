"""Create Agent User tool component — allows agents to provision API users."""

from __future__ import annotations

import json
import logging
import secrets
import uuid

import pyotp
from langchain_core.tools import tool

from components import register
from database import SessionLocal
from models.user import APIKey, UserProfile
from models.node import WorkflowEdge, WorkflowNode
from models.workflow import Workflow

logger = logging.getLogger(__name__)


@register("create_agent_user")
def create_agent_user_factory(node):
    """Return a LangChain @tool that creates an agent user for API access."""
    extra = node.component_config.extra_config or {}
    api_base_url = extra.get("api_base_url", "http://localhost:8000")

    # Capture tool's node info to find the parent agent
    tool_workflow_id = node.workflow_id
    tool_node_id = node.node_id

    @tool
    def create_agent_user(purpose: str = "") -> str:
        """Get or create API credentials for this agent.

        Safe to call every time you need API access — returns existing
        credentials if they already exist, or creates new ones.

        Args:
            purpose: Optional description of what the credentials are for.

        Returns:
            JSON string with username, api_key, and api_base_url.
        """
        db = SessionLocal()
        try:
            # Find the parent agent node via edge lookup
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

            # Deterministic username from agent identity
            username = f"agent_{workflow_slug}_{agent_node_id}"

            # Return existing credentials if already provisioned
            existing = db.query(UserProfile).filter(UserProfile.username == username).first()
            if existing and existing.api_key:
                logger.info("Returning existing agent user: %s", username)
                return json.dumps({
                    "success": True,
                    "username": username,
                    "api_key": existing.api_key.key,
                    "api_base_url": api_base_url,
                    "purpose": existing.first_name,
                    "already_existed": True,
                })

            # Create new agent user with TOTP secret for MFA
            random_hash = secrets.token_hex(32)
            user = UserProfile(
                username=username,
                password_hash=random_hash,
                first_name=purpose or "Agent-created user",
                is_agent=True,
                totp_secret=pyotp.random_base32(),
                mfa_enabled=True,
            )
            db.add(user)
            db.flush()

            api_key = APIKey(user_id=user.id, key=str(uuid.uuid4()))
            db.add(api_key)
            db.commit()
            db.refresh(api_key)

            logger.info("Created agent user: %s", username)
            return json.dumps({
                "success": True,
                "username": username,
                "api_key": api_key.key,
                "api_base_url": api_base_url,
                "purpose": purpose,
                "already_existed": False,
            })

        except Exception as e:
            db.rollback()
            logger.exception("Error creating agent user")
            return json.dumps({
                "error": str(e),
                "success": False,
            })
        finally:
            db.close()

    return create_agent_user
