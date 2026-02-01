"""Trigger handlers — unified event dispatch."""

from __future__ import annotations

import logging
import uuid

import redis
from rq import Queue
from sqlalchemy.orm import Session

from config import settings
from triggers.resolver import trigger_resolver

logger = logging.getLogger(__name__)


def dispatch_event(event_type: str, event_data: dict, user_profile, db: Session):
    """Unified entry point for all trigger types."""
    from models.execution import WorkflowExecution
    from tasks import execute_workflow_job

    result = trigger_resolver.resolve(event_type, event_data, db)
    if result is None:
        logger.debug("No workflow matched for event_type='%s'", event_type)
        return None

    workflow, trigger_node = result

    execution = WorkflowExecution(
        workflow_id=workflow.id,
        trigger_node_id=trigger_node.id,
        user_profile_id=user_profile.id,
        thread_id=uuid.uuid4().hex,
        trigger_payload=event_data,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    conn = redis.from_url(settings.REDIS_URL)
    queue = Queue("workflows", connection=conn)
    queue.enqueue(execute_workflow_job, str(execution.execution_id))

    logger.info(
        "Dispatched event '%s' → workflow '%s' (execution %s)",
        event_type, workflow.slug, execution.execution_id,
    )
    return execution
