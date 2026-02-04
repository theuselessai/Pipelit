"""Memory Write component — LangChain tool that stores information in memory."""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from components import register
from database import SessionLocal
from services.memory import MemoryService

logger = logging.getLogger(__name__)


@register("memory_write")
def memory_write_factory(node):
    """Return a LangChain @tool named 'remember' that writes to global memory."""
    extra = node.component_config.extra_config or {}

    default_fact_type = extra.get("fact_type", "world_knowledge")
    overwrite = extra.get("overwrite", True)

    @tool
    def remember(key: str, value: str, fact_type: str = "") -> str:
        """Store a fact in memory. Provide a key and value to remember."""
        if not key:
            return "Error: key is required"
        if not value:
            return "Error: value is required"

        resolved_fact_type = fact_type or default_fact_type

        db = SessionLocal()
        try:
            memory = MemoryService(db)

            fact = memory.set_fact(
                key=key,
                value=value,
                fact_type=resolved_fact_type,
                scope="global",
                agent_id="global",
                overwrite=overwrite,
            )

            action = "updated" if fact.times_confirmed > 1 else "created"
            if not overwrite and fact.times_confirmed > 1:
                action = "skipped"

            return f"Remembered: {key} = {value} ({action})"

        except Exception as e:
            logger.exception("Memory write error")
            return f"Error writing memory: {e}"
        finally:
            db.close()

    return remember
