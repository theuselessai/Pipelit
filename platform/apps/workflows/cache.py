"""GraphCache — in-memory cache for compiled LangGraph graphs."""

from __future__ import annotations

import hashlib
import logging
import threading
import time

from apps.workflows.builder import WorkflowBuilder

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 3600  # 1 hour


class GraphCache:
    """Thread-safe in-memory cache for CompiledGraph instances."""

    def __init__(self, ttl: int = _DEFAULT_TTL):
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._builder = WorkflowBuilder()

    def get_or_build(self, workflow):
        """Return cached CompiledGraph or build and cache a new one."""
        key = self._cache_key(workflow)

        with self._lock:
            if key in self._cache:
                ts, graph = self._cache[key]
                if time.monotonic() - ts < self._ttl:
                    logger.debug("Cache hit for workflow '%s'", workflow.slug)
                    return graph
                del self._cache[key]

        # Build outside lock (may be slow)
        graph = self._builder.build(workflow)

        with self._lock:
            self._cache[key] = (time.monotonic(), graph)

        logger.info("Cached graph for workflow '%s' (key=%s)", workflow.slug, key)
        return graph

    def invalidate(self, workflow_id: int) -> None:
        """Remove all cache entries for a workflow."""
        prefix = f"{workflow_id}:"
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]
        if keys_to_remove:
            logger.info("Invalidated %d cache entries for workflow %s", len(keys_to_remove), workflow_id)

    def clear(self) -> None:
        """Clear entire cache."""
        with self._lock:
            self._cache.clear()

    def _cache_key(self, workflow) -> str:
        """Generate cache key from workflow ID and config hash."""
        # Hash based on updated_at timestamps
        parts = [str(workflow.updated_at)]
        for node in workflow.nodes.all().order_by("id"):
            parts.append(f"{node.node_id}:{node.updated_at}:{node.component_config.updated_at}")
        config_hash = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
        return f"{workflow.id}:{config_hash}"


# Module-level singleton
graph_cache = GraphCache()
