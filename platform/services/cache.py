"""GraphCache — in-memory cache for compiled LangGraph graphs."""

from __future__ import annotations

import hashlib
import logging
import threading
import time

from sqlalchemy.orm import Session

from services.builder import WorkflowBuilder

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 3600


class GraphCache:
    def __init__(self, ttl: int = _DEFAULT_TTL):
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._builder = WorkflowBuilder()

    def get_or_build(self, workflow, db: Session, trigger_node_id: int | None = None):
        key = self._cache_key(workflow, db, trigger_node_id)

        with self._lock:
            if key in self._cache:
                ts, graph = self._cache[key]
                if time.monotonic() - ts < self._ttl:
                    return graph
                del self._cache[key]

        graph = self._builder.build(workflow, db, trigger_node_id=trigger_node_id)

        with self._lock:
            self._cache[key] = (time.monotonic(), graph)
        return graph

    def invalidate(self, workflow_id: int) -> None:
        prefix = f"{workflow_id}:"
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def _cache_key(self, workflow, db: Session, trigger_node_id: int | None = None) -> str:
        from models.node import WorkflowNode

        parts = [str(workflow.updated_at), str(trigger_node_id)]
        nodes = (
            db.query(WorkflowNode)
            .filter(WorkflowNode.workflow_id == workflow.id)
            .order_by(WorkflowNode.id)
            .all()
        )
        for node in nodes:
            parts.append(f"{node.node_id}:{node.updated_at}:{node.component_config.updated_at}")
        config_hash = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
        return f"{workflow.id}:{config_hash}"


graph_cache = GraphCache()
