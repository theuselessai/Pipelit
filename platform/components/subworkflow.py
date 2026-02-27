"""Subworkflow component — execute another workflow as a child execution."""

from __future__ import annotations

import logging
import uuid

from components import register

logger = logging.getLogger(__name__)


@register("workflow")
def subworkflow_factory(node):
    """Build a subworkflow graph node.

    On first invocation: creates a child WorkflowExecution and signals the
    orchestrator to wait (via ``_subworkflow``).  On second invocation (after
    the child completes): reads the child output from state and returns it.
    """
    extra = node.component_config.extra_config or {}
    target_slug = extra.get("target_workflow", "")
    trigger_mode = extra.get("trigger_mode", "implicit")
    input_mapping = extra.get("input_mapping", {})
    # Fallback: subworkflow_id FK on the node record
    subworkflow_id_fk = node.subworkflow_id
    node_id = node.node_id

    def subworkflow_node(state: dict) -> dict:
        # Check if child already completed and result was injected
        child_result = state.get("_subworkflow_results", {}).get(node_id)
        if child_result is not None:
            return {"output": child_result}

        # First invocation — create and enqueue child execution
        child_execution_id = _create_child_execution(
            state=state,
            target_slug=target_slug,
            subworkflow_id_fk=subworkflow_id_fk,
            trigger_mode=trigger_mode,
            input_mapping=input_mapping,
            parent_node_id=node_id,
        )

        return {"_subworkflow": {"child_execution_id": child_execution_id}}

    return subworkflow_node


def _create_child_execution(
    state: dict,
    target_slug: str,
    subworkflow_id_fk: int | None,
    trigger_mode: str,
    input_mapping: dict,
    parent_node_id: str,
) -> str:
    """Create a child WorkflowExecution and enqueue it on RQ."""
    from database import SessionLocal
    from models.execution import WorkflowExecution
    from models.workflow import Workflow

    db = SessionLocal()
    try:
        # Resolve target workflow
        target_workflow = None
        if trigger_mode == "explicit":
            return _create_via_dispatch(state, target_slug, input_mapping, parent_node_id, db)

        # Implicit mode — look up workflow directly
        if target_slug:
            target_workflow = (
                db.query(Workflow)
                .filter(Workflow.slug == target_slug)
                .first()
            )
        if not target_workflow and subworkflow_id_fk:
            target_workflow = db.query(Workflow).filter(Workflow.id == subworkflow_id_fk).first()

        if not target_workflow:
            raise ValueError(
                f"Target workflow not found: slug={target_slug!r}, "
                f"subworkflow_id={subworkflow_id_fk}"
            )

        # Build child trigger payload
        trigger_payload = _build_trigger_payload(state, input_mapping)

        # Get parent execution context
        parent_execution_id = state.get("execution_id", "")
        user_context = state.get("user_context", {})
        user_profile_id = user_context.get("user_profile_id")
        if not user_profile_id:
            # Fallback: look up from parent execution
            if parent_execution_id:
                parent_exec = (
                    db.query(WorkflowExecution)
                    .filter(WorkflowExecution.execution_id == parent_execution_id)
                    .first()
                )
                if parent_exec:
                    user_profile_id = parent_exec.user_profile_id

        if not user_profile_id:
            raise ValueError("Cannot determine user_profile_id for child execution")

        child_execution = WorkflowExecution(
            workflow_id=target_workflow.id,
            user_profile_id=user_profile_id,
            thread_id=uuid.uuid4().hex,
            trigger_payload=trigger_payload,
            parent_execution_id=parent_execution_id,
            parent_node_id=parent_node_id,
        )
        db.add(child_execution)
        db.commit()
        db.refresh(child_execution)

        child_id = str(child_execution.execution_id)

        # Enqueue child execution on RQ
        import redis
        from rq import Queue

        from config import settings

        conn = redis.from_url(settings.REDIS_URL)
        q = Queue("workflows", connection=conn)
        from tasks import execute_workflow_job

        q.enqueue(execute_workflow_job, child_id)

        logger.info(
            "Subworkflow: created child execution %s for workflow '%s' "
            "(parent=%s, node=%s, mode=implicit)",
            child_id, target_workflow.slug, parent_execution_id, parent_node_id,
        )
        return child_id

    finally:
        db.close()


def _create_via_dispatch(
    state: dict,
    target_slug: str,
    input_mapping: dict,
    parent_node_id: str,
    db,
) -> str:
    """Create child execution via dispatch_event (explicit mode)."""
    from handlers import dispatch_event
    from models.execution import WorkflowExecution
    from models.user import UserProfile

    trigger_payload = _build_trigger_payload(state, input_mapping)
    trigger_payload["source_workflow"] = target_slug

    parent_execution_id = state.get("execution_id", "")
    user_context = state.get("user_context", {})
    user_profile_id = user_context.get("user_profile_id")

    user_profile = db.query(UserProfile).filter(UserProfile.id == user_profile_id).first()
    if not user_profile:
        raise ValueError(f"User profile {user_profile_id} not found for explicit dispatch")

    execution = dispatch_event("workflow", trigger_payload, user_profile, db)
    if not execution:
        raise ValueError(
            f"No workflow matched for explicit dispatch "
            f"(source_workflow={target_slug!r})"
        )

    # Set parent linkage (dispatch_event doesn't know about parent)
    execution.parent_execution_id = parent_execution_id
    execution.parent_node_id = parent_node_id
    db.commit()

    logger.info(
        "Subworkflow: dispatched child execution %s via trigger resolver "
        "(parent=%s, node=%s, mode=explicit)",
        execution.execution_id, parent_execution_id, parent_node_id,
    )
    return str(execution.execution_id)


def _build_trigger_payload(state: dict, input_mapping: dict) -> dict:
    """Build the trigger_payload for the child execution from parent state."""
    if not input_mapping:
        # Default: pass trigger data and all node outputs
        return {
            "text": state.get("trigger", {}).get("text", ""),
            "payload": {
                "trigger": state.get("trigger", {}),
                "node_outputs": state.get("node_outputs", {}),
            },
        }

    # Resolve mapped fields from state
    payload = {}
    for target_key, source_path in input_mapping.items():
        payload[target_key] = _resolve_path(state, source_path)
    return payload


def _resolve_path(state: dict, path: str):
    """Resolve a dotted path like 'node_outputs.agent_1.output' from state."""
    parts = path.split(".")
    current = state
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current
