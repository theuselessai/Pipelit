"""Memory Read component — retrieve information from agent memory."""

from __future__ import annotations

import logging

from components import register
from database import SessionLocal
from services.memory import MemoryService

logger = logging.getLogger(__name__)


@register("memory_read")
def memory_read_factory(node):
    """Return a graph node function that reads from memory."""
    extra = node.component_config.extra_config or {}
    node_id = node.node_id

    memory_type = extra.get("memory_type", "facts")
    limit = extra.get("limit", 10)
    min_confidence = extra.get("min_confidence", 0.5)
    include_user_scope = extra.get("include_user_scope", True)

    def memory_read_node(state: dict) -> dict:
        # Get inputs from state (either from trigger or node_outputs)
        node_outputs = state.get("node_outputs", {})

        # Look for inputs in node_outputs from connected nodes
        key = None
        query = None

        # Check if there's direct input from a previous node
        for out in node_outputs.values():
            if isinstance(out, dict):
                if "key" in out:
                    key = out["key"]
                if "query" in out:
                    query = out["query"]

        # Also check trigger for direct inputs
        trigger = state.get("trigger", {})
        if not key and not query:
            key = trigger.get("memory_key")
            query = trigger.get("memory_query")

        if not key and not query:
            return {
                "node_outputs": {
                    node_id: {
                        "result": None,
                        "found": False,
                        "count": 0,
                        "error": "Either 'key' or 'query' must be provided",
                    }
                }
            }

        # Get context for scoping
        user_context = state.get("user_context", {})
        execution_id = state.get("execution_id", "")

        # Derive agent_id from execution context
        agent_id = f"workflow:{execution_id.split('-')[0]}" if execution_id else "default"
        user_id = user_context.get("canonical_id") or user_context.get("user_id")
        session_id = execution_id

        db = SessionLocal()
        try:
            memory = MemoryService(db)
            results = []

            if key:
                # Exact key lookup
                value = memory.get_fact(
                    key=key,
                    agent_id=agent_id,
                    user_id=user_id if include_user_scope else None,
                    session_id=session_id,
                )
                if value is not None:
                    results = [{"key": key, "value": value}]

            elif query:
                # Search
                if memory_type in ("facts", "all"):
                    facts = memory.search_facts(
                        query=query,
                        agent_id=agent_id,
                        user_id=user_id if include_user_scope else None,
                        limit=limit,
                        min_confidence=min_confidence,
                    )
                    results.extend([
                        {
                            "type": "fact",
                            "key": f.key,
                            "value": f.value,
                            "confidence": f.confidence,
                            "fact_type": f.fact_type,
                        }
                        for f in facts
                    ])

                if memory_type in ("procedures", "all"):
                    proc = memory.find_matching_procedure(
                        goal=query,
                        context=state,
                        agent_id=agent_id,
                        user_id=user_id if include_user_scope else None,
                    )
                    if proc:
                        results.append({
                            "type": "procedure",
                            "name": proc.name,
                            "description": proc.description,
                            "success_rate": proc.success_rate,
                            "procedure_type": proc.procedure_type,
                        })

                if memory_type in ("episodes", "all"):
                    episodes = memory.get_recent_episodes(
                        agent_id=agent_id,
                        user_id=user_id if include_user_scope else None,
                        limit=min(limit, 5),
                    )
                    for ep in episodes:
                        if query.lower() in (ep.summary or "").lower():
                            results.append({
                                "type": "episode",
                                "id": ep.id,
                                "summary": ep.summary,
                                "success": ep.success,
                                "when": ep.started_at.isoformat() if ep.started_at else None,
                            })

            # Format output
            if len(results) == 0:
                return {
                    "node_outputs": {
                        node_id: {
                            "result": None,
                            "found": False,
                            "count": 0,
                        }
                    }
                }
            elif len(results) == 1:
                return {
                    "node_outputs": {
                        node_id: {
                            "result": results[0].get("value", results[0]),
                            "found": True,
                            "count": 1,
                        }
                    }
                }
            else:
                return {
                    "node_outputs": {
                        node_id: {
                            "result": results,
                            "found": True,
                            "count": len(results),
                        }
                    }
                }

        except Exception as e:
            logger.exception("Memory read error")
            return {
                "node_outputs": {
                    node_id: {
                        "result": None,
                        "found": False,
                        "count": 0,
                        "error": str(e),
                    }
                }
            }
        finally:
            db.close()

    return memory_read_node
