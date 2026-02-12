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


def dispatch_event(
    event_type: str,
    event_data: dict,
    user_profile,
    db: Session,
    *,
    workflow_id: int | None = None,
    trigger_node_id: str | None = None,
):
    """Unified entry point for all trigger types.

    When workflow_id and/or trigger_node_id are provided (e.g. from the
    scheduler), the resolver is bypassed and the specific workflow/trigger
    is targeted directly.
    """
    from models.execution import WorkflowExecution
    from models.node import WorkflowNode
    from models.workflow import Workflow
    from tasks import execute_workflow_job

    if workflow_id and trigger_node_id:
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        trigger_node = (
            db.query(WorkflowNode)
            .filter(WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_id == trigger_node_id)
            .first()
        )
        if not workflow or not trigger_node:
            logger.debug("Direct dispatch: workflow=%s trigger=%s not found", workflow_id, trigger_node_id)
            return None
    else:
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
