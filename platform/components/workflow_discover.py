"""workflow_discover tool — LangChain tool for searching existing workflows."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register

logger = logging.getLogger(__name__)


@register("workflow_discover")
def workflow_discover_factory(node):
    """Return a list with one LangChain tool: workflow_discover.

    The tool searches existing workflows by requirements and returns
    scored matches with gap analysis and reuse recommendations.
    """
    workflow_id = node.workflow_id

    @tool
    def workflow_discover(requirements: str, limit: int = 5) -> str:
        """Search existing workflows by requirements and get reuse recommendations.

        Scores each workflow against your requirements and recommends whether to
        reuse (score >= 0.95), fork_and_patch (>= 0.50), or create_new (< 0.50).

        Args:
            requirements: JSON string with optional keys: triggers, node_types,
                tools, tags, description, model_capability.
            limit: Maximum number of results (default 5).

        Returns:
            JSON with success, matches (scored results), and total_searched.
        """
        from database import SessionLocal
        from services.workflow_discovery import discover_workflows

        db = SessionLocal()
        try:
            req = json.loads(requirements)
            matches = discover_workflows(
                req, db,
                exclude_workflow_id=workflow_id,
                limit=limit,
            )
            return json.dumps({
                "success": True,
                "matches": matches,
                "total_searched": len(matches),
            }, default=str)
        except json.JSONDecodeError as e:
            return json.dumps({"success": False, "error": f"Invalid JSON: {e}"})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    return [workflow_discover]
