"""Validate Topology tool component — DSL compiler dry-run validation."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register
from database import SessionLocal
from services.dsl_compiler import validate_dsl

logger = logging.getLogger(__name__)


@register("validate_topology")
def validate_topology_factory(node):
    """Return a LangChain tool that validates a topology YAML via the DSL compiler."""

    @tool
    def validate_topology(topology_yaml: str) -> str:
        """Validate a topology YAML string using the DSL compiler in dry-run mode.

        Args:
            topology_yaml: The workflow topology YAML string to validate.

        Returns:
            JSON string with validation results including valid, errors,
            warnings, node_count, and edge_count.
        """
        result = {
            "valid": False,
            "errors": [],
            "warnings": [],
            "node_count": 0,
            "edge_count": 0,
        }

        if not topology_yaml or not topology_yaml.strip():
            result["errors"].append("Empty topology YAML provided")
            return json.dumps(result)

        db = None
        try:
            db = SessionLocal()
            dsl_result = validate_dsl(topology_yaml, db)

            result["valid"] = dsl_result.get("valid", False)
            result["errors"] = dsl_result.get("errors", [])
            result["node_count"] = dsl_result.get("node_count", 0)
            result["edge_count"] = dsl_result.get("edge_count", 0)

        except Exception as e:
            logger.debug("validate_topology: unexpected error", exc_info=True)
            result["errors"].append(f"Validation error: {e}")
        finally:
            if db is not None:
                db.close()

        return json.dumps(result)

    return validate_topology
