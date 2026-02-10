"""workflow_create tool — LangChain tool for creating workflows from YAML DSL."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register

logger = logging.getLogger(__name__)


@register("workflow_create")
def workflow_create_factory(node):
    """Return a list with one LangChain tool: workflow_create.

    The tool accepts a YAML DSL string and compiles it into a persisted
    workflow (nodes, edges, configs) in a single transaction.
    """
    workflow_id = node.workflow_id
    node_id = node.node_id

    @tool
    def workflow_create(dsl: str, tags: str = "") -> str:
        """Create a workflow from a YAML DSL specification.

        Parses the YAML, creates trigger + step nodes, wires edges, and
        persists everything to the database.  Supports two modes:

        **Create mode** — define ``name``, ``trigger``, ``steps``.
        **Fork mode** — ``based_on: <slug>`` + ``patches`` list.

        Args:
            dsl: YAML string defining the workflow.
            tags: Optional comma-separated tags to add.

        Returns:
            JSON with workflow_id, slug, node_count, edge_count, or error.
        """
        from database import SessionLocal
        from models.node import WorkflowNode
        from models.workflow import Workflow
        from services.dsl_compiler import compile_dsl

        db = SessionLocal()
        try:
            # Resolve parent agent node for inherit model resolution
            parent_node = (
                db.query(WorkflowNode)
                .filter_by(workflow_id=workflow_id, node_id=node_id)
                .first()
            )

            # Find owner from workflow
            workflow = db.query(Workflow).filter_by(id=workflow_id).first()
            if not workflow:
                return json.dumps({"success": False, "error": "Parent workflow not found"})
            owner_id = workflow.owner_id

            result = compile_dsl(dsl, owner_id, db, parent_node=parent_node)

            # Append extra tags if provided
            if tags and result.get("success") and result.get("slug"):
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                if tag_list:
                    created_wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
                    if created_wf:
                        existing = created_wf.tags or []
                        created_wf.tags = list(set(existing + tag_list))
                        db.commit()

            return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    return [workflow_create]
