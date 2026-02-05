"""Create Agent User tool component — allows agents to provision API users."""

from __future__ import annotations

import json
import logging
import secrets
import uuid

from langchain_core.tools import tool

from components import register
from database import SessionLocal
from models.user import APIKey, UserProfile

logger = logging.getLogger(__name__)


@register("create_agent_user")
def create_agent_user_factory(node):
    """Return a LangChain @tool that creates an agent user for API access."""
    extra = node.component_config.extra_config or {}
    api_base_url = extra.get("api_base_url", "http://localhost:8000/api/v1")

    @tool
    def create_agent_user(username: str = "", purpose: str = "") -> str:
        """Create an agent user and return credentials for API access.

        Args:
            username: Optional username for the new user. If not provided, auto-generates one.
            purpose: Optional description of what this user will be used for.

        Returns:
            JSON string with username, api_key, and api_base_url.
        """
        db = SessionLocal()
        try:
            # Auto-generate username if not provided
            if not username:
                username = f"agent_{uuid.uuid4().hex[:8]}"

            # Check if username already exists
            existing = db.query(UserProfile).filter(UserProfile.username == username).first()
            if existing:
                return json.dumps({
                    "error": f"Username '{username}' already exists",
                    "success": False,
                })

            # Create the agent user with a random password hash (agents don't login via password)
            random_hash = secrets.token_hex(32)
            user = UserProfile(
                username=username,
                password_hash=random_hash,
                first_name=purpose or "Agent-created user",
                is_agent=True,
            )
            db.add(user)
            db.flush()

            # Create API key
            api_key = APIKey(user_id=user.id, key=str(uuid.uuid4()))
            db.add(api_key)
            db.commit()
            db.refresh(api_key)

            result = {
                "success": True,
                "username": username,
                "api_key": api_key.key,
                "api_base_url": api_base_url,
                "purpose": purpose,
            }

            logger.info("Created agent user: %s", username)
            return json.dumps(result)

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
