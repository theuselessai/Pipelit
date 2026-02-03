"""Orchestrator — RQ-based per-node workflow execution."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import redis as redis_lib
from rq import Queue
from sqlalchemy.orm import Session

from config import settings
from services.state import deserialize_state, merge_state_update, serialize_state
from services.topology import build_topology

logger = logging.getLogger(__name__)

STATE_TTL = 3600  # 1 hour
LOCK_TTL = 30  # seconds
MAX_NODE_RETRIES = 3
PUBSUB_CHANNEL_PREFIX = "execution:"


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


def _queue() -> Queue:
    conn = redis_lib.from_url(settings.REDIS_URL)
    return Queue("workflows", connection=conn)


# ── Redis state helpers ────────────────────────────────────────────────────────


def _state_key(execution_id: str) -> str:
    return f"execution:{execution_id}:state"


def _fanin_key(execution_id: str, node_id: str) -> str:
    return f"execution:{execution_id}:fanin:{node_id}"


def _lock_key(execution_id: str) -> str:
    return f"execution:{execution_id}:lock"


def _topo_key(execution_id: str) -> str:
    return f"execution:{execution_id}:topo"


def _completed_key(execution_id: str) -> str:
    return f"execution:{execution_id}:completed"


def load_state(execution_id: str) -> dict:
    r = _redis()
    raw = r.get(_state_key(execution_id))
    if not raw:
        return {}
    return deserialize_state(json.loads(raw))


def save_state(execution_id: str, state: dict) -> None:
    r = _redis()
    r.set(_state_key(execution_id), json.dumps(serialize_state(state)), ex=STATE_TTL)


def _publish_event(execution_id: str, event_type: str, data: dict | None = None, workflow_slug: str | None = None) -> None:
    r = _redis()
    payload = {"type": event_type, "execution_id": execution_id, "timestamp": time.time()}
    if data:
        payload["data"] = data
    raw = json.dumps(payload)
    r.publish(f"{PUBSUB_CHANNEL_PREFIX}{execution_id}", raw)
    # Also publish to workflow channel so global WS subscribers get execution events
    if workflow_slug:
        payload["channel"] = f"workflow:{workflow_slug}"
        r.publish(f"workflow:{workflow_slug}", json.dumps(payload))


def _save_topology(execution_id: str, topo) -> None:
    """Cache topology edges and node info in Redis for worker access."""
    r = _redis()
    data = {
        "workflow_slug": getattr(topo, "workflow_slug", ""),
        "entry_node_ids": topo.entry_node_ids,
        "nodes": {
            nid: {
                "node_id": n.node_id,
                "component_type": n.component_type,
                "db_id": n.db_id,
                "component_config_id": n.component_config_id,
                "interrupt_before": n.interrupt_before,
                "interrupt_after": n.interrupt_after,
            }
            for nid, n in topo.nodes.items()
        },
        "edges_by_source": {
            src: [
                {
                    "source_node_id": e.source_node_id,
                    "target_node_id": e.target_node_id,
                    "edge_type": e.edge_type,
                    "condition_mapping": e.condition_mapping,
                    "priority": e.priority,
                }
                for e in edges
            ]
            for src, edges in topo.edges_by_source.items()
        },
        "incoming_count": topo.incoming_count,
    }
    r.set(_topo_key(execution_id), json.dumps(data), ex=STATE_TTL)


def _load_topology(execution_id: str) -> dict:
    r = _redis()
    raw = r.get(_topo_key(execution_id))
    if not raw:
        raise RuntimeError(f"Topology not found in Redis for execution {execution_id}")
    return json.loads(raw)


# ── Core orchestrator ──────────────────────────────────────────────────────────


def start_execution(execution_id: str, db: Session | None = None) -> None:
    """Entry point: build topology, save initial state, enqueue entry nodes."""
    from database import SessionLocal
    from models.execution import WorkflowExecution
    from models.workflow import Workflow

    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        execution = (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == execution_id)
            .first()
        )
        if not execution:
            logger.error("Execution %s not found", execution_id)
            return

        workflow = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
        if not workflow:
            logger.error("Workflow not found for execution %s", execution_id)
            return

        execution.status = "running"
        execution.started_at = datetime.now(timezone.utc)
        db.commit()

        # Publish execution_started event so frontend can reset node statuses
        _publish_event(execution_id, "execution_started", {"workflow_id": workflow.id}, workflow_slug=workflow.slug)

        topo = build_topology(workflow, db, trigger_node_id=execution.trigger_node_id)
        _save_topology(execution_id, topo)

        initial_state = _build_initial_state(execution)
        save_state(execution_id, initial_state)

        # Initialize completed-nodes set
        r = _redis()
        r.delete(_completed_key(execution_id))

        slug = workflow.slug
        from tasks import execute_node_job as _enqueue_node
        q = _queue()
        for node_id in topo.entry_node_ids:
            _publish_event(execution_id, "node_enqueued", {"node_id": node_id}, workflow_slug=slug)
            q.enqueue(_enqueue_node, execution_id, node_id)

        logger.info("Started execution %s with entry nodes %s", execution_id, topo.entry_node_ids)

    except Exception as exc:
        logger.exception("Failed to start execution %s", execution_id)
        if execution:
            execution.status = "failed"
            execution.error_message = str(exc)[:2000]
            execution.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        if own_session:
            db.close()


def execute_node_job(execution_id: str, node_id: str, retry_count: int = 0) -> None:
    """RQ job: execute a single workflow node."""
    from database import SessionLocal
    from models.execution import ExecutionLog, WorkflowExecution
    from models.node import WorkflowNode

    db = SessionLocal()
    try:
        execution = (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == execution_id)
            .first()
        )
        if not execution or execution.status not in ("running",):
            logger.warning("Execution %s not runnable (status=%s)", execution_id, execution.status if execution else "?")
            return

        topo_data = _load_topology(execution_id)
        node_info = topo_data["nodes"].get(node_id)
        if not node_info:
            logger.error("Node %s not in topology for execution %s", node_id, execution_id)
            return

        # Check interrupt_before
        if node_info.get("interrupt_before"):
            _handle_interrupt(execution, node_id, "before", db)
            return

        state = load_state(execution_id)
        state["current_node"] = node_id

        from schemas.node_io import NodeStatus
        slug = topo_data.get("workflow_slug", "")
        _publish_event(execution_id, "node_status", {"node_id": node_id, "status": NodeStatus.RUNNING.value}, workflow_slug=slug)

        # Load node from DB and get component factory
        db_node = db.get(WorkflowNode, node_info["db_id"])
        if not db_node:
            raise RuntimeError(f"Node DB record {node_info['db_id']} not found")

        from components import get_component_factory
        factory = get_component_factory(node_info["component_type"])
        node_fn = factory(db_node)

        from schemas.node_io import NodeResult, NodeStatus

        started_at = datetime.now(timezone.utc)
        start_time = time.monotonic()
        try:
            result = node_fn(state)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            exc_type = type(exc).__name__
            node_result = NodeResult.failed(
                error_code=exc_type, message=str(exc), node_id=node_id,
                recoverable=retry_count < MAX_NODE_RETRIES,
            )
            node_result.started_at = started_at
            node_result.completed_at = datetime.now(timezone.utc)

            _write_log(
                db, execution_id, node_id, "failed",
                duration_ms=duration_ms, error=str(exc),
                error_code=exc_type,
                metadata=node_result.metadata,
            )
            _publish_event(execution_id, "node_status", {
                "node_id": node_id, "status": NodeStatus.FAILED.value,
                "error": str(exc)[:500], "error_code": exc_type,
            }, workflow_slug=slug)

            # Retry logic
            if retry_count < MAX_NODE_RETRIES:
                logger.warning("Node %s failed (attempt %d), retrying", node_id, retry_count + 1)
                from tasks import execute_node_job as _enqueue_node
                q = _queue()
                q.enqueue_in(
                    timedelta(seconds=2 ** retry_count),
                    _enqueue_node,
                    execution_id,
                    node_id,
                    retry_count + 1,
                )
                return

            logger.exception("Node %s failed permanently in execution %s", node_id, execution_id)
            execution.status = "failed"
            execution.error_message = f"Node {node_id}: {str(exc)[:1900]}"
            execution.completed_at = datetime.now(timezone.utc)
            db.commit()
            _publish_event(execution_id, "execution_failed", {"error": str(exc)[:500]}, workflow_slug=slug)
            _cleanup_redis(execution_id)
            return

        duration_ms = int((time.monotonic() - start_time) * 1000)
        completed_at = datetime.now(timezone.utc)

        # Wrap raw result in NodeResult
        result_data = _safe_json(result) or {}
        node_result = NodeResult.success(
            data=result_data,
            started_at=started_at,
            completed_at=completed_at,
        )

        # Merge result into state
        if result and isinstance(result, dict):
            state = merge_state_update(state, result)

        # Store NodeResult in state under node_results
        node_results = state.get("node_results", {})
        node_results[node_id] = node_result.model_dump(mode="json")
        state["node_results"] = node_results

        save_state(execution_id, state)

        _write_log(
            db, execution_id, node_id, "completed",
            duration_ms=duration_ms, output=result_data,
            metadata=node_result.metadata,
        )
        _publish_event(execution_id, "node_status", {
            "node_id": node_id, "status": NodeStatus.SUCCESS.value,
            "duration_ms": duration_ms,
        }, workflow_slug=slug)

        # Mark node completed
        r = _redis()
        r.sadd(_completed_key(execution_id), node_id)

        # Check interrupt_after
        if node_info.get("interrupt_after"):
            _handle_interrupt(execution, node_id, "after", db)
            return

        _advance(execution_id, node_id, state, topo_data, db)

    except Exception as exc:
        logger.exception("Unexpected error in execute_node_job(%s, %s)", execution_id, node_id)
        try:
            if execution:
                execution.status = "failed"
                execution.error_message = str(exc)[:2000]
                execution.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
        _ws_slug = topo_data.get("workflow_slug", "") if "topo_data" in locals() else None
        _publish_event(execution_id, "execution_failed", {"error": str(exc)[:500]}, workflow_slug=_ws_slug)
    finally:
        db.close()


def resume_node_job(execution_id: str, user_input: str) -> None:
    """Resume an interrupted execution by injecting user input and running the interrupted node."""
    from database import SessionLocal
    from models.execution import PendingTask, WorkflowExecution

    db = SessionLocal()
    try:
        execution = (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == execution_id)
            .first()
        )
        if not execution or execution.status != "interrupted":
            return

        # Find pending task to get node_id
        pending = (
            db.query(PendingTask)
            .filter(PendingTask.execution_id == execution_id)
            .first()
        )
        node_id = pending.node_id if pending else ""
        if pending:
            db.delete(pending)

        execution.status = "running"
        db.commit()

        if not node_id:
            logger.error("No node_id found for resume of execution %s", execution_id)
            return

        # Inject resume input into state
        state = load_state(execution_id)
        state["_resume_input"] = user_input
        save_state(execution_id, state)

        # Re-enqueue the node
        from tasks import execute_node_job as _enqueue_node
        q = _queue()
        q.enqueue(_enqueue_node, execution_id, node_id)

    finally:
        db.close()


# ── Advance / finalize ─────────────────────────────────────────────────────────


def _advance(
    execution_id: str,
    completed_node_id: str,
    state: dict,
    topo_data: dict,
    db: Session,
) -> None:
    """Enqueue successor nodes after a node completes."""
    edges = topo_data["edges_by_source"].get(completed_node_id, [])
    if not edges:
        _maybe_finalize(execution_id, topo_data, db)
        return

    q = _queue()
    r = _redis()

    # Separate direct and conditional edges
    conditional = [e for e in edges if e["edge_type"] == "conditional"]
    direct = [e for e in edges if e["edge_type"] == "direct"]

    targets_to_enqueue: list[str] = []

    if conditional:
        # Route based on state["route"]
        route_val = state.get("route", "")
        edge = conditional[0]
        mapping = edge.get("condition_mapping") or {}
        target = mapping.get(route_val)
        if target and target != "__end__":
            targets_to_enqueue.append(target)
        elif target == "__end__" or not target:
            # This branch ends
            pass
    else:
        # Fan-out: enqueue ALL direct edge targets
        for e in direct:
            target = e["target_node_id"]
            if target and target != "__end__":
                targets_to_enqueue.append(target)

    for target_id in targets_to_enqueue:
        target_info = topo_data["nodes"].get(target_id)
        if not target_info:
            continue

        # Check if target is a merge node (fan-in)
        if target_info["component_type"] == "merge":
            expected = topo_data["incoming_count"].get(target_id, 1)
            count = r.incr(_fanin_key(execution_id, target_id))
            r.expire(_fanin_key(execution_id, target_id), STATE_TTL)
            if count < expected:
                logger.debug(
                    "Fan-in %s: %d/%d parents done", target_id, count, expected
                )
                continue
            # All parents done — fall through to enqueue

        _publish_event(execution_id, "node_enqueued", {"node_id": target_id}, workflow_slug=topo_data.get("workflow_slug", ""))
        from tasks import execute_node_job as _enqueue_node
        q.enqueue(_enqueue_node, execution_id, target_id)

    if not targets_to_enqueue:
        _maybe_finalize(execution_id, topo_data, db)


def _maybe_finalize(execution_id: str, topo_data: dict, db: Session) -> None:
    """Finalize execution if all nodes are done."""
    r = _redis()
    completed = r.smembers(_completed_key(execution_id))
    all_node_ids = set(topo_data["nodes"].keys())

    if not all_node_ids.issubset(completed):
        # Some nodes still pending — might be on parallel branches
        return

    _finalize(execution_id, db)


def _finalize(execution_id: str, db: Session) -> None:
    """Mark execution complete, extract output, deliver, clean up."""
    from models.execution import WorkflowExecution

    execution = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.execution_id == execution_id)
        .first()
    )
    if not execution or execution.status != "running":
        return

    state = load_state(execution_id)
    execution.status = "completed"
    execution.final_output = _extract_output(state)
    execution.completed_at = datetime.now(timezone.utc)
    db.commit()

    logger.info("Execution %s completed", execution_id)
    slug = _get_workflow_slug(execution_id, db)
    _publish_event(execution_id, "execution_completed", {"output": execution.final_output}, workflow_slug=slug)

    from services.delivery import output_delivery
    output_delivery.deliver(execution, db)

    _cleanup_redis(execution_id)


def _handle_interrupt(execution, node_id: str, phase: str, db: Session) -> None:
    """Create a PendingTask and set execution to interrupted."""
    from models.execution import PendingTask
    from models.system import SystemConfig

    config = SystemConfig.load(db)
    timeout = config.confirmation_timeout_seconds
    payload = execution.trigger_payload or {}

    pending = PendingTask(
        task_id=uuid.uuid4().hex[:8],
        execution_id=execution.execution_id,
        user_profile_id=execution.user_profile_id,
        telegram_chat_id=payload.get("chat_id", 0),
        node_id=node_id,
        prompt=f"Confirmation required at node '{node_id}' ({phase} execution).",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=timeout),
    )
    db.add(pending)
    execution.status = "interrupted"
    db.commit()

    slug = _get_workflow_slug(str(execution.execution_id), db)
    _publish_event(str(execution.execution_id), "execution_interrupted", {"node_id": node_id}, workflow_slug=slug)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_initial_state(execution) -> dict:
    from langchain_core.messages import HumanMessage

    payload = execution.trigger_payload or {}
    messages = []
    text = payload.get("text", "")
    if text:
        messages.append(HumanMessage(content=text))
    return {
        "messages": messages,
        "trigger": payload,
        "user_context": {
            "user_profile_id": execution.user_profile_id,
            "telegram_chat_id": payload.get("chat_id"),
        },
        "current_node": "",
        "execution_id": str(execution.execution_id),
        "route": "",
        "branch_results": {},
        "plan": [],
        "node_outputs": {},
        "output": None,
        "loop_state": {},
        "error": "",
        "should_retry": False,
    }


def _write_log(
    db: Session,
    execution_id: str,
    node_id: str,
    status: str,
    duration_ms: int = 0,
    output: dict | None = None,
    error: str = "",
    error_code: str | None = None,
    metadata: dict | None = None,
) -> None:
    from models.execution import ExecutionLog

    log = ExecutionLog(
        execution_id=execution_id,
        node_id=node_id,
        status=status,
        output=output,
        error=error[:2000] if error else "",
        error_code=error_code,
        log_metadata=metadata or {},
        duration_ms=duration_ms,
    )
    db.add(log)
    db.commit()


def _extract_output(state: dict) -> dict | None:
    output = state.get("output")
    if output is not None:
        return {"output": output}
    node_outputs = state.get("node_outputs", {})
    if node_outputs:
        return {"node_outputs": node_outputs}
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        return {"message": last.content if hasattr(last, "content") else str(last)}
    return None


def _safe_json(obj) -> dict | None:
    """Best-effort JSON-serializable version of obj."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return {"repr": repr(obj)[:1000]}
    return {"repr": repr(obj)[:1000]}


def _get_workflow_slug(execution_id: str, db: Session | None = None) -> str | None:
    """Look up workflow slug for an execution (cached in topo or from DB)."""
    try:
        topo = _load_topology(execution_id)
        slug = topo.get("workflow_slug")
        if slug:
            return slug
    except Exception:
        pass
    if db:
        from models.execution import WorkflowExecution
        from models.workflow import Workflow
        ex = db.query(WorkflowExecution).filter(WorkflowExecution.execution_id == execution_id).first()
        if ex:
            wf = db.query(Workflow).filter(Workflow.id == ex.workflow_id).first()
            if wf:
                return wf.slug
    return None


def _cleanup_redis(execution_id: str) -> None:
    """Remove execution keys from Redis."""
    r = _redis()
    keys = r.keys(f"execution:{execution_id}:*")
    if keys:
        r.delete(*keys)


# ── RQ entry points (module-level for pickling) ───────────────────────────────


def start_execution_job(execution_id: str) -> None:
    start_execution(execution_id)
