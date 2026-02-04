"""Memory Read component — LangChain tool that retrieves information from memory."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register
from database import SessionLocal
from services.memory import MemoryService

logger = logging.getLogger(__name__)


@register("memory_read")
def memory_read_factory(node):
    """Return a LangChain @tool named 'recall' that reads from global memory."""
    extra = node.component_config.extra_config or {}

    memory_type = extra.get("memory_type", "facts")
    limit = extra.get("limit", 10)
    min_confidence = extra.get("min_confidence", 0.5)

    @tool
    def recall(key: str = "", query: str = "") -> str:
        """Recall information from memory. Use key for exact lookup, or query to search."""
        if not key and not query:
            return "Error: Either 'key' or 'query' must be provided"

        db = SessionLocal()
        try:
            memory = MemoryService(db)
            results = []

            if key:
                # Exact key lookup — global scope
                value = memory.get_fact(
                    key=key,
                    agent_id="global",
                )
                if value is not None:
                    return f"{key} = {value}"
                return f"No memory found for key: {key}"

            # Search — global scope
            if memory_type in ("facts", "all"):
                facts = memory.search_facts(
                    query=query,
                    agent_id="global",
                    limit=limit,
                    min_confidence=min_confidence,
                )
                results.extend([
                    {"key": f.key, "value": f.value, "confidence": f.confidence}
                    for f in facts
                ])

            if memory_type in ("procedures", "all"):
                proc = memory.find_matching_procedure(
                    goal=query,
                    context={},
                    agent_id="global",
                )
                if proc:
                    results.append({
                        "type": "procedure",
                        "name": proc.name,
                        "description": proc.description,
                    })

            if memory_type in ("episodes", "all"):
                episodes = memory.get_recent_episodes(
                    agent_id="global",
                    limit=min(limit, 5),
                )
                for ep in episodes:
                    if query.lower() in (ep.summary or "").lower():
                        results.append({
                            "type": "episode",
                            "summary": ep.summary,
                        })

            if not results:
                return f"No memories found for query: {query}"

            return json.dumps(results, default=str)

        except Exception as e:
            logger.exception("Memory read error")
            return f"Error reading memory: {e}"
        finally:
            db.close()

    return recall
