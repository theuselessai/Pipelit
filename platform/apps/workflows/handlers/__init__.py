"""Trigger handlers — unified event dispatch."""

from __future__ import annotations

import logging
import uuid

import django_rq

from apps.workflows.triggers.resolver import trigger_resolver

logger = logging.getLogger(__name__)


def dispatch_event(event_type: str, event_data: dict, user_profile):
    """Unified entry point for all trigger types.

    Resolves the event to a workflow, creates a WorkflowExecution, and
    enqueues the execution job.

    Args:
        event_type: Trigger type (e.g., "telegram_chat", "webhook", "manual").
        event_data: Event payload dict.
        user_profile: UserProfile instance for the triggering user.

    Returns:
        WorkflowExecution instance, or None if no workflow matched.
    """
    from apps.workflows.executor import execute_workflow_job
    from apps.workflows.models import WorkflowExecution

    result = trigger_resolver.resolve(event_type, event_data)
    if result is None:
        logger.debug("No workflow matched for event_type='%s'", event_type)
        return None

    workflow, trigger = result

    execution = WorkflowExecution.objects.create(
        workflow=workflow,
        trigger=trigger,
        user_profile=user_profile,
        thread_id=uuid.uuid4().hex,
        trigger_payload=event_data,
    )

    queue = django_rq.get_queue("workflows")
    queue.enqueue(execute_workflow_job, str(execution.execution_id))

    logger.info(
        "Dispatched event '%s' → workflow '%s' (execution %s)",
        event_type,
        workflow.slug,
        execution.execution_id,
    )
    return execution
