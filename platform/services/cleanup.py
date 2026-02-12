"""Periodic cleanup job: expire stuck child-wait nodes.

Scans Redis for ``execution:*:child_wait:*`` keys whose deadline has passed and
resumes the parent execution with an ``_error`` payload so the parent doesn't
stay stuck in "running" forever.

Schedule this as an RQ periodic/cron job (e.g. every 60 seconds).
"""

from __future__ import annotations

import json
import logging
import time

import redis as redis_lib

from config import settings

logger = logging.getLogger(__name__)


def cleanup_stuck_child_waits() -> int:
    """Expire child-wait keys past their deadline.

    Returns the number of waits expired.
    """
    r = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)

    # Scan for all child_wait keys
    expired_count = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match="execution:*:child_wait:*", count=100)
        for key in keys:
            raw = r.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                r.delete(key)
                continue

            deadline = data.get("deadline", 0)
            if time.time() <= deadline:
                continue

            # Extract execution_id and node_id from key pattern:
            # execution:<execution_id>:child_wait:<node_id>
            parts = key.split(":")
            # parts = ["execution", execution_id, "child_wait", node_id]
            if len(parts) < 4:
                r.delete(key)
                continue

            execution_id = parts[1]
            node_id = parts[3]

            logger.warning(
                "Child wait expired for execution %s node %s (deadline %.0f, now %.0f)",
                execution_id,
                node_id,
                deadline,
                time.time(),
            )

            # Resume parent with timeout error
            try:
                from services.orchestrator import _resume_from_child

                _resume_from_child(
                    parent_execution_id=execution_id,
                    parent_node_id=node_id,
                    child_output={"_error": "Child execution timed out after 600s"},
                )
            except Exception:
                logger.exception(
                    "Failed to resume timed-out parent %s at node %s",
                    execution_id,
                    node_id,
                )

            # Delete the key regardless (prevent repeated retries)
            r.delete(key)
            expired_count += 1

        if cursor == 0:
            break

    if expired_count:
        logger.info("Expired %d stuck child waits", expired_count)
    return expired_count
