"""Whoami tool component — gives agents self-awareness about their identity."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register
from database import SessionLocal
from models.workflow import Workflow
from models.node import WorkflowNode, WorkflowEdge

logger = logging.getLogger(__name__)


@register("whoami")
def whoami_factory(node):
    """Return a LangChain @tool that tells the agent about itself."""

    # Capture this tool's node info to find the parent agent
    tool_workflow_id = node.workflow_id
    tool_node_id = node.node_id

    @tool
    def whoami() -> str:
        """Get information about the agent using this tool - workflow, node ID, and current configuration.

        Use this to understand your identity and how to modify yourself via the platform API.

        Returns:
            JSON with workflow_slug, node_id, current system_prompt, and instructions for self-modification.
        """
        db = SessionLocal()
        try:
            # Find the agent node that this tool is connected to
            # Tools connect to agents via edges with edge_label="tool"
            edge = (
                db.query(WorkflowEdge)
                .filter(
                    WorkflowEdge.workflow_id == tool_workflow_id,
                    WorkflowEdge.source_node_id == tool_node_id,
                    WorkflowEdge.edge_label == "tool",
                )
                .first()
            )

            if not edge:
                return json.dumps({
                    "error": "This whoami tool is not connected to any agent node",
                    "hint": "Connect this tool to an agent via a 'tool' edge"
                })

            # Get the agent node
            agent_node = (
                db.query(WorkflowNode)
                .filter(
                    WorkflowNode.workflow_id == tool_workflow_id,
                    WorkflowNode.node_id == edge.target_node_id,
                )
                .first()
            )

            if not agent_node:
                return json.dumps({"error": f"Agent node '{edge.target_node_id}' not found"})

            # Get workflow slug
            workflow = db.query(Workflow).filter(Workflow.id == tool_workflow_id).first()
            workflow_slug = workflow.slug if workflow else "unknown"

            # Get agent's config
            agent_config = agent_node.component_config
            system_prompt = agent_config.system_prompt or ""
            extra_config = agent_config.extra_config or {}

            result = {
                "identity": {
                    "workflow_slug": workflow_slug,
                    "workflow_id": tool_workflow_id,
                    "node_id": agent_node.node_id,
                    "component_type": agent_node.component_type,
                },
                "current_config": {
                    "system_prompt": system_prompt[:1000] + "..." if len(system_prompt) > 1000 else system_prompt,
                    "system_prompt_length": len(system_prompt),
                    "extra_config": extra_config,
                },
                "self_modification": {
                    "endpoint": f"/api/v1/workflows/{workflow_slug}/nodes/{agent_node.node_id}/",
                    "method": "PATCH",
                    "example_body": {
                        "config": {
                            "system_prompt": "Your new system prompt here",
                            "extra_config": {"conversation_memory": True}
                        }
                    },
                    "instructions": [
                        "1. Use create_agent_user to get API credentials if you don't have them",
                        "2. Use platform_api with method='PATCH' to update your configuration",
                        "3. Changes take effect on the next execution/conversation",
                    ]
                }
            }

            return json.dumps(result, indent=2)

        except Exception as e:
            logger.exception("Error in whoami")
            return json.dumps({"error": str(e)})
        finally:
            db.close()

    return whoami
