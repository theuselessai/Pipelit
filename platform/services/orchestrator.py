"""Orchestrator — RQ-based per-node workflow execution."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
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
    return Queue("workflows", connection=conn, default_timeout=600)


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


def _episode_key(execution_id: str) -> str:
    return f"execution:{execution_id}:episode_id"


def _inflight_key(execution_id: str) -> str:
    return f"execution:{execution_id}:inflight"


def _child_wait_key(execution_id: str, node_id: str) -> str:
    return f"execution:{execution_id}:child_wait:{node_id}"


def _loop_key(execution_id: str, loop_id: str) -> str:
    return f"execution:{execution_id}:loop:{loop_id}"


def _loop_iter_done_key(execution_id: str, loop_id: str, iter_index: int | None = None) -> str:
    if iter_index is not None:
        return f"execution:{execution_id}:loop:{loop_id}:iter:{iter_index}:done"
    return f"execution:{execution_id}:loop:{loop_id}:iter_done"  # legacy fallback


def _parent_info_key(execution_id: str) -> str:
    return f"execution:{execution_id}:parent_info"


def _cache_parent_info(
    execution_id: str,
    parent_eid: str,
    parent_nid: str,
    parent_slug: str,
    root_eid: str,
    root_nid: str,
    root_slug: str,
) -> None:
    """Cache parent/root execution metadata so child events can be forwarded."""
    r = _redis()
    r.set(
        _parent_info_key(execution_id),
        json.dumps({
            "parent_execution_id": parent_eid,
            "parent_node_id": parent_nid,
            "parent_workflow_slug": parent_slug,
            "root_execution_id": root_eid,
            "root_node_id": root_nid,
            "root_workflow_slug": root_slug,
        }),
        ex=STATE_TTL,
    )


def _get_parent_info(execution_id: str) -> dict | None:
    """Retrieve cached parent/root execution metadata."""
    r = _redis()
    raw = r.get(_parent_info_key(execution_id))
    return json.loads(raw) if raw else None


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
    try:
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

        # Forward child node_status events to root parent's channels
        if event_type == "node_status":
            parent_info = _get_parent_info(execution_id)
            if parent_info:
                root_eid = parent_info.get("root_execution_id")
                root_slug = parent_info.get("root_workflow_slug")
                root_nid = parent_info.get("root_node_id")
                if root_eid:
                    child_data = dict(data) if data else {}
                    child_data["child_execution_id"] = execution_id
                    child_data["parent_node_id"] = root_nid
                    child_data["is_child_event"] = True
                    child_payload = {
                        "type": "child_node_status",
                        "execution_id": root_eid,
                        "timestamp": time.time(),
                        "data": child_data,
                    }
                    r.publish(f"{PUBSUB_CHANNEL_PREFIX}{root_eid}", json.dumps(child_payload))
                    if root_slug:
                        child_payload["channel"] = f"workflow:{root_slug}"
                        r.publish(f"workflow:{root_slug}", json.dumps(child_payload))
    except Exception:
        logger.warning(
            "Failed to publish event %s for execution %s (non-fatal)",
            event_type, execution_id, exc_info=True,
        )


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
                    "edge_label": getattr(e, "edge_label", "") or "",
                    "condition_mapping": e.condition_mapping,
                    "condition_value": getattr(e, "condition_value", "") or "",
                    "priority": e.priority,
                }
                for e in edges
            ]
            for src, edges in topo.edges_by_source.items()
        },
        "incoming_count": topo.incoming_count,
        "loop_bodies": getattr(topo, "loop_bodies", {}),
        "loop_return_nodes": getattr(topo, "loop_return_nodes", {}),
        "loop_body_all_nodes": {k: list(v) for k, v in getattr(topo, "loop_body_all_nodes", {}).items()},
    }
    r.set(_topo_key(execution_id), json.dumps(data), ex=STATE_TTL)


def _load_topology(execution_id: str) -> dict:
    r = _redis()
    raw = r.get(_topo_key(execution_id))
    if not raw:
        raise RuntimeError(f"Topology not found in Redis for execution {execution_id}")
    return json.loads(raw)


# ── Node metadata helper ──────────────────────────────────────────────────────


def _get_node_meta(node_info: dict) -> dict:
    """Extract display metadata from a topology node_info dict for WS events."""
    from schemas.node_types import get_node_type

    component_type = node_info.get("component_type", "")
    spec = get_node_type(component_type)
    display_name = spec.display_name if spec else component_type
    return {
        "component_type": component_type,
        "display_name": display_name,
        "node_label": node_info.get("node_id", ""),
    }


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

        # Start memory episode for this execution
        trigger_type = "manual"
        trigger_node = None
        if execution.trigger_node_id:
            from models.node import WorkflowNode
            trigger_node = db.get(WorkflowNode, execution.trigger_node_id)
            if trigger_node:
                trigger_type = trigger_node.component_type.replace("trigger_", "")
        _start_episode(
            execution_id=execution_id,
            workflow_id=workflow.id,
            trigger_type=trigger_type,
            trigger_payload=execution.trigger_payload,
            db=db,
        )

        topo = build_topology(workflow, db, trigger_node_id=execution.trigger_node_id)
        _save_topology(execution_id, topo)

        # Cache parent info for child executions so events can be forwarded
        if execution.parent_execution_id:
            parent_eid = str(execution.parent_execution_id)
            parent_nid = execution.parent_node_id or ""
            # Resolve parent workflow slug from DB (not the child's workflow.slug)
            parent_exec = (
                db.query(WorkflowExecution)
                .filter(WorkflowExecution.execution_id == parent_eid)
                .first()
            )
            if parent_exec:
                parent_wf = db.query(Workflow).filter(Workflow.id == parent_exec.workflow_id).first()
                parent_slug = parent_wf.slug if parent_wf else ""
            else:
                parent_slug = ""
            # Check if parent is itself a child (grandchild+ scenario)
            grandparent_info = _get_parent_info(parent_eid)
            if grandparent_info and grandparent_info.get("root_execution_id"):
                root_eid = grandparent_info["root_execution_id"]
                root_nid = grandparent_info["root_node_id"]
                root_slug = grandparent_info["root_workflow_slug"]
            else:
                root_eid = parent_eid
                root_nid = parent_nid
                root_slug = parent_slug
            _cache_parent_info(
                execution_id, parent_eid, parent_nid, parent_slug,
                root_eid, root_nid, root_slug,
            )

        initial_state = _build_initial_state(execution)

        # Pre-populate node_outputs for the trigger node so downstream
        # Jinja2 expressions like {{ trigger_schedule_xxx.timestamp }} resolve.
        if execution.trigger_node_id and trigger_node:
            initial_state["node_outputs"][trigger_node.node_id] = dict(
                initial_state.get("trigger", {})
            )

        save_state(execution_id, initial_state)

        # Initialize completed-nodes set and inflight counter
        r = _redis()
        r.delete(_completed_key(execution_id))
        r.delete(_inflight_key(execution_id))

        slug = workflow.slug
        from tasks import execute_node_job as _enqueue_node
        q = _queue()
        for node_id in topo.entry_node_ids:
            r.incr(_inflight_key(execution_id))
            r.expire(_inflight_key(execution_id), STATE_TTL)
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
            # Decrement inflight so execution can finalize if all other nodes are done
            r = _redis()
            remaining = r.decr(_inflight_key(execution_id))
            if remaining <= 0 and execution and execution.status == "running":
                _finalize(execution_id, db)
            return

        topo_data = _load_topology(execution_id)
        node_info = topo_data["nodes"].get(node_id)
        if not node_info:
            logger.error("Node %s not in topology for execution %s", node_id, execution_id)
            r = _redis()
            remaining = r.decr(_inflight_key(execution_id))
            if remaining <= 0:
                _finalize(execution_id, db)
            return

        # Check interrupt_before
        if node_info.get("interrupt_before"):
            _handle_interrupt(execution, node_id, "before", db)
            # Decrement inflight — execution is now "interrupted" so _finalize()
            # will no-op even if counter reaches 0. resume_node_job() re-increments.
            r = _redis()
            r.decr(_inflight_key(execution_id))
            return

        state = load_state(execution_id)
        state["current_node"] = node_id

        from schemas.node_io import NodeStatus
        slug = topo_data.get("workflow_slug", "")

        # Budget enforcement: check epic budget before executing node
        budget_error = _check_budget(execution_id, state, db)
        if budget_error:
            execution.status = "failed"
            execution.error_message = budget_error[:2000]
            execution.completed_at = datetime.now(timezone.utc)
            _persist_execution_costs(execution, state)
            db.commit()
            _sync_task_costs(execution_id, db)
            _publish_event(execution_id, "execution_failed", {"error": budget_error[:500]}, workflow_slug=slug)
            _cleanup_redis(execution_id)
            return

        _node_meta = _get_node_meta(node_info)
        _publish_event(execution_id, "node_status", {"node_id": node_id, "status": NodeStatus.RUNNING.value, **_node_meta}, workflow_slug=slug)

        # Load node from DB and get component factory
        db_node = db.get(WorkflowNode, node_info["db_id"])
        if not db_node:
            raise RuntimeError(f"Node DB record {node_info['db_id']} not found")

        # Resolve Jinja2 expressions in config before component gets it
        from services.expressions import resolve_config_expressions, resolve_expressions

        expr_node_outputs = state.get("node_outputs", {})
        expr_trigger = state.get("trigger", {})
        # Include loop context in expression resolution
        loop_ctx = state.get("loop")
        if loop_ctx:
            expr_node_outputs = {**expr_node_outputs, "loop": loop_ctx}

        # Expunge config to avoid dirtying SQLAlchemy session
        db.expunge(db_node.component_config)

        if db_node.component_config.system_prompt:
            db_node.component_config.system_prompt = resolve_expressions(
                db_node.component_config.system_prompt, expr_node_outputs, expr_trigger
            )
        if db_node.component_config.extra_config:
            db_node.component_config.extra_config = resolve_config_expressions(
                db_node.component_config.extra_config, expr_node_outputs, expr_trigger
            )

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
                **_node_meta,
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

            # Check if failed node is inside a loop body with on_error=continue
            r = _redis()
            loop_body_all = topo_data.get("loop_body_all_nodes", {})
            owning_loop_id = None
            for lid, all_body in loop_body_all.items():
                if node_id in set(all_body):
                    owning_loop_id = lid
                    break

            if owning_loop_id:
                from models.node import WorkflowNode as _WFNode
                loop_info = topo_data["nodes"].get(owning_loop_id)
                on_error = "stop"
                if loop_info:
                    loop_db_node = db.get(_WFNode, loop_info["db_id"])
                    if loop_db_node and loop_db_node.component_config:
                        on_error = loop_db_node.component_config.extra_config.get("on_error", "stop")

                if on_error == "continue":
                    logger.warning("Node %s failed in loop %s body (on_error=continue), skipping", node_id, owning_loop_id)
                    # Store error in state so _loop_next_iteration includes it
                    state = load_state(execution_id)
                    loop_errors = state.get("_loop_errors", {})
                    loop_errors.setdefault(owning_loop_id, {})[node_id] = {
                        "error": str(exc)[:500], "error_code": exc_type,
                    }
                    state["_loop_errors"] = loop_errors
                    save_state(execution_id, state)

                    # Check if this is a completion node or intermediate
                    return_nodes = topo_data.get("loop_return_nodes", {}).get(owning_loop_id, [])
                    body_targets = topo_data.get("loop_bodies", {}).get(owning_loop_id, [])
                    completion_nodes = return_nodes if return_nodes else body_targets

                    if node_id not in completion_nodes:
                        # Intermediate node failed — downstream won't run, force advance
                        _loop_next_iteration(execution_id, owning_loop_id, topo_data, db)
                    else:
                        # Completion node failed — _check_loop_body_done handles it normally
                        _check_loop_body_done(execution_id, node_id, topo_data, db)

                    # Decrement inflight for the failed node
                    remaining = r.decr(_inflight_key(execution_id))
                    if remaining <= 0:
                        _finalize(execution_id, db)
                    return

            # on_error == "stop" (default) — fail the entire execution
            logger.exception("Node %s failed permanently in execution %s", node_id, execution_id)
            execution.status = "failed"
            execution.error_message = f"Node {node_id}: {str(exc)[:1900]}"
            execution.completed_at = datetime.now(timezone.utc)
            _persist_execution_costs(execution, load_state(execution_id))
            db.commit()
            _clear_stale_checkpoints(execution_id, db)
            _sync_task_costs(execution_id, db)
            _publish_event(execution_id, "execution_failed", {"error": str(exc)[:500]}, workflow_slug=slug)
            _complete_episode(
                execution_id=execution_id,
                success=False,
                final_output=None,
                error_code=exc_type,
                error_message=f"Node {node_id}: {str(exc)[:500]}",
            )
            _propagate_failure_to_parent(execution, exc)
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
        delay_seconds = None
        loop_data = None
        subworkflow_data = None
        token_usage = None
        if result and isinstance(result, dict):
            if "node_outputs" in result:
                # Legacy path — component did its own wrapping
                token_usage = result.pop("_token_usage", None)
                state = merge_state_update(state, result)
            else:
                # New path — extract reserved keys, wrap the rest
                route = result.pop("_route", None)
                new_messages = result.pop("_messages", None)
                state_patch = result.pop("_state_patch", None)
                delay_seconds = result.pop("_delay_seconds", None)
                loop_data = result.pop("_loop", None)
                subworkflow_data = result.pop("_subworkflow", None)
                token_usage = result.pop("_token_usage", None)

                # Wrap port values into node_outputs
                port_data = {k: v for k, v in result.items() if not k.startswith("_")}
                node_outputs = state.get("node_outputs", {})
                node_outputs[node_id] = port_data
                state["node_outputs"] = node_outputs

                # Apply side effects
                if route is not None:
                    state["route"] = route
                if new_messages:
                    state["messages"] = state.get("messages", []) + new_messages
                if state_patch and isinstance(state_patch, dict):
                    for k, v in state_patch.items():
                        if k not in ("messages", "node_outputs", "node_results"):
                            state[k] = v

        # Accumulate token usage into execution-level totals
        if token_usage:
            node_result.metadata["token_usage"] = token_usage
            from services.token_usage import merge_usage
            exec_usage = state.get("_execution_token_usage", {})
            state["_execution_token_usage"] = merge_usage(exec_usage, token_usage)

        # Store NodeResult in state under node_results
        node_results = state.get("node_results", {})
        node_results[node_id] = node_result.model_dump(mode="json")
        state["node_results"] = node_results

        save_state(execution_id, state)

        # Extract output for log and WS event (truncate large values)
        node_output = state.get("node_outputs", {}).get(node_id)
        log_output = _safe_json(node_output) if node_output is not None else result_data

        _write_log(
            db, execution_id, node_id, "completed",
            duration_ms=duration_ms, output=log_output,
            metadata=node_result.metadata,
        )
        ws_data = {
            "node_id": node_id, "status": NodeStatus.SUCCESS.value,
            "duration_ms": duration_ms,
            "output": _truncate_output(node_output),
            **_node_meta,
        }
        if token_usage:
            ws_data["token_usage"] = token_usage
        _publish_event(execution_id, "node_status", ws_data, workflow_slug=slug)

        # Mark node completed
        r = _redis()
        r.sadd(_completed_key(execution_id), node_id)

        # Check interrupt_after
        if node_info.get("interrupt_after"):
            _handle_interrupt(execution, node_id, "after", db)
            # Decrement inflight — execution is now "interrupted" so _finalize()
            # will no-op even if counter reaches 0. resume_node_job() re-increments.
            r.decr(_inflight_key(execution_id))
            return

        # Handle loop: if component returned _loop, start iteration
        if loop_data:
            items = loop_data.get("items", [])
            body_targets = topo_data.get("loop_bodies", {}).get(node_id, [])
            if items and body_targets:
                r.set(_loop_key(execution_id, node_id), json.dumps({
                    "items": items, "index": 0, "results": [],
                    "body_targets": body_targets,
                }), ex=STATE_TTL)
                state["loop"] = {"item": items[0], "index": 0, "total": len(items)}
                save_state(execution_id, state)
                _advance_loop_body(execution_id, node_id, topo_data, slug, iter_index=0)
                return
            # Empty array or no body targets — advance normally

        # Handle subworkflow: component created child execution(s), wait for completion
        if subworkflow_data:
            child_ids = subworkflow_data.get("child_execution_ids", [])
            is_parallel = subworkflow_data.get("parallel", False)
            count = subworkflow_data.get("count", len(child_ids))

            # Legacy single-child fallback
            if not child_ids and subworkflow_data.get("child_execution_id"):
                child_ids = [subworkflow_data["child_execution_id"]]
                count = 1

            logger.info(
                "Node %s waiting for %d child execution(s): %s",
                node_id, count, child_ids,
            )
            # Store timeout deadline so the cleanup job can expire stuck waits
            timeout_seconds = 600  # 10 minutes
            deadline = time.time() + timeout_seconds
            wait_data = {
                "deadline": deadline,
                "parallel": is_parallel,
                "total": count,
                "child_ids": child_ids,
                "results": {},
            }
            r.set(
                _child_wait_key(execution_id, node_id),
                json.dumps(wait_data),
                ex=timeout_seconds + 60,
            )
            _publish_event(execution_id, "node_status", {
                "node_id": node_id, "status": NodeStatus.WAITING.value,
                "child_execution_ids": child_ids,
                **_node_meta,
            }, workflow_slug=slug)
            # Do NOT advance or decrement inflight — node stays inflight
            # until all children complete and _resume_from_child is called.
            return

        # Handle delay: pass delay to _advance
        _advance(execution_id, node_id, state, topo_data, db, delay_seconds=delay_seconds)

    except Exception as exc:
        logger.exception("Unexpected error in execute_node_job(%s, %s)", execution_id, node_id)
        _exec = locals().get("execution")
        try:
            if _exec:
                _exec.status = "failed"
                _exec.error_message = str(exc)[:2000]
                _exec.completed_at = datetime.now(timezone.utc)
                try:
                    _persist_execution_costs(_exec, load_state(execution_id))
                except Exception:
                    logger.exception("Failed to persist execution costs for %s", execution_id)
                db.commit()
                _clear_stale_checkpoints(execution_id, db)
                _sync_task_costs(execution_id, db)
        except Exception:
            logger.exception(
                "Failed to persist failure status for execution %s", execution_id
            )
        # Decrement inflight so execution can finalize if other nodes are still inflight
        try:
            r = _redis()
            r.decr(_inflight_key(execution_id))
        except Exception:
            logger.exception("Failed to decrement inflight for execution %s", execution_id)
        _ws_slug = topo_data.get("workflow_slug", "") if "topo_data" in locals() else None
        try:
            _publish_event(execution_id, "execution_failed", {"error": str(exc)[:500]}, workflow_slug=_ws_slug)
        except Exception:
            logger.exception("Failed to publish execution_failed event for %s", execution_id)
        _complete_episode(
            execution_id=execution_id,
            success=False,
            final_output=None,
            error_code=type(exc).__name__,
            error_message=str(exc)[:500],
        )
        # Propagate failure to parent (if this is a child execution)
        if _exec:
            _propagate_failure_to_parent(_exec, exc)
        _cleanup_redis(execution_id)
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

        # Re-enqueue the node (increment inflight to match the decrement on interrupt)
        r = _redis()
        r.incr(_inflight_key(execution_id))
        r.expire(_inflight_key(execution_id), STATE_TTL)
        from tasks import execute_node_job as _enqueue_node
        q = _queue()
        q.enqueue(_enqueue_node, execution_id, node_id)

    finally:
        db.close()


def _propagate_failure_to_parent(execution, exc: Exception) -> None:
    """If *execution* is a child, notify the parent of failure (best-effort)."""
    parent_eid = getattr(execution, "parent_execution_id", None)
    parent_nid = getattr(execution, "parent_node_id", None)
    if not (parent_eid and parent_nid and isinstance(parent_eid, str)):
        return
    try:
        _resume_from_child(
            parent_execution_id=parent_eid,
            parent_node_id=parent_nid,
            child_output={"_error": f"Child execution failed: {str(exc)[:500]}"},
            child_execution_id=str(getattr(execution, "execution_id", "")),
        )
    except Exception:
        logger.exception("Failed to propagate failure to parent %s", parent_eid)


def _resume_from_child(
    parent_execution_id: str,
    parent_node_id: str,
    child_output: dict | None,
    child_execution_id: str | None = None,
) -> None:
    """Resume a parent execution after a child subworkflow completes.

    For parallel spawns, accumulates results in the child_wait key until
    all children have reported, then injects the ordered results list into
    parent state and re-enqueues the subworkflow node.
    """
    from database import SessionLocal
    from models.execution import WorkflowExecution

    db = SessionLocal()
    try:
        parent = (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == parent_execution_id)
            .first()
        )
        if not parent:
            logger.error("Parent execution %s not found for child resume", parent_execution_id)
            return
        if parent.status != "running":
            logger.warning(
                "Parent execution %s not running (status=%s), skipping resume",
                parent_execution_id, parent.status,
            )
            return

        r = _redis()
        wait_key = _child_wait_key(parent_execution_id, parent_node_id)
        raw = r.get(wait_key)

        if not raw:
            # Key already consumed (concurrent child or cleanup already resumed)
            logger.warning(
                "Child wait key gone for parent %s node %s, skipping",
                parent_execution_id, parent_node_id,
            )
            return

        wait_data = json.loads(raw)

        if wait_data.get("parallel") and child_execution_id:
            # Parallel mode: accumulate results under Redis lock
            lock_key = f"{wait_key}:lock"
            lock = r.lock(lock_key, timeout=LOCK_TTL)
            if not lock.acquire(blocking=True, blocking_timeout=10):
                logger.error(
                    "Failed to acquire lock for parallel resume %s/%s",
                    parent_execution_id, parent_node_id,
                )
                return
            try:
                # Re-read under lock (may have been updated by concurrent child)
                raw = r.get(wait_key)
                if not raw:
                    logger.warning("Child wait key consumed under lock for %s", parent_execution_id)
                    return
                wait_data = json.loads(raw)

                results = wait_data.get("results", {})
                results[child_execution_id] = child_output
                total = wait_data.get("total", 1)

                if len(results) < total:
                    # Not all children done yet — update and return
                    wait_data["results"] = results
                    r.set(wait_key, json.dumps(wait_data), ex=STATE_TTL)
                    logger.info(
                        "Parallel child %s reported (%d/%d) for parent %s node %s",
                        child_execution_id, len(results), total,
                        parent_execution_id, parent_node_id,
                    )
                    return

                # All children done — build ordered results list and resume
                child_ids = wait_data.get("child_ids", [])
                ordered_results = [results.get(cid) for cid in child_ids]
                r.delete(wait_key)
            finally:
                try:
                    lock.release()
                except Exception:
                    pass
        else:
            # Legacy single-child path or direct resume (e.g. from cleanup)
            r.delete(wait_key)
            ordered_results = child_output

        # Inject child output into parent state
        state = load_state(parent_execution_id)
        subworkflow_results = state.get("_subworkflow_results", {})
        subworkflow_results[parent_node_id] = ordered_results
        state["_subworkflow_results"] = subworkflow_results
        save_state(parent_execution_id, state)

        # Re-enqueue the subworkflow node — on re-entry it will see the
        # child result and return it as normal output, then advance.
        from tasks import execute_node_job as _enqueue_node

        q = _queue()
        q.enqueue(_enqueue_node, parent_execution_id, parent_node_id)

        logger.info(
            "Resumed parent execution %s at node %s with child output",
            parent_execution_id, parent_node_id,
        )
    finally:
        db.close()


# ── Advance / finalize ─────────────────────────────────────────────────────────


def _advance(
    execution_id: str,
    completed_node_id: str,
    state: dict,
    topo_data: dict,
    db: Session,
    delay_seconds: float | None = None,
) -> None:
    """Enqueue successor nodes after a node completes."""
    r = _redis()
    # Filter to non-loop_body edges for normal advancement
    all_edges = topo_data["edges_by_source"].get(completed_node_id, [])
    edges = [e for e in all_edges if e.get("edge_label", "") not in ("loop_body", "loop_return")]
    if not edges:
        # Check if completed node is inside a loop body
        if _check_loop_body_done(execution_id, completed_node_id, topo_data, db, delay_seconds=delay_seconds):
            r.decr(_inflight_key(execution_id))
            return
        remaining = r.decr(_inflight_key(execution_id))
        if remaining <= 0:
            _finalize(execution_id, db)
        return

    q = _queue()

    # Separate direct and conditional edges
    conditional = [e for e in edges if e["edge_type"] == "conditional"]
    direct = [e for e in edges if e["edge_type"] == "direct"]

    targets_to_enqueue: list[str] = []

    if conditional:
        # Route based on state["route"] using individual condition_value edges
        route_val = state.get("route", "")
        matched_target = None
        for e in conditional:
            if e.get("condition_value") == route_val:
                matched_target = e["target_node_id"]
                break
        # Fallback: legacy condition_mapping
        if matched_target is None:
            edge = conditional[0]
            mapping = edge.get("condition_mapping") or {}
            matched_target = mapping.get(route_val)
        if matched_target and matched_target != "__end__":
            targets_to_enqueue.append(matched_target)
    else:
        # Fan-out: enqueue ALL direct edge targets
        for e in direct:
            target = e["target_node_id"]
            if target and target != "__end__":
                targets_to_enqueue.append(target)

    enqueued_count = 0
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

        r.incr(_inflight_key(execution_id))
        enqueued_count += 1
        _publish_event(execution_id, "node_enqueued", {"node_id": target_id}, workflow_slug=topo_data.get("workflow_slug", ""))
        from tasks import execute_node_job as _enqueue_node
        if delay_seconds and delay_seconds > 0:
            q.enqueue_in(timedelta(seconds=delay_seconds), _enqueue_node, execution_id, target_id)
        else:
            q.enqueue(_enqueue_node, execution_id, target_id)

    # Check if completed node is inside a loop body
    _check_loop_body_done(execution_id, completed_node_id, topo_data, db, delay_seconds=delay_seconds)

    # Decrement inflight for the completed node and check if execution is done
    remaining = r.decr(_inflight_key(execution_id))
    if remaining <= 0:
        _finalize(execution_id, db)


def _advance_loop_body(execution_id: str, loop_node_id: str, topo_data: dict, slug: str, iter_index: int = 0, delay_seconds: float | None = None) -> None:
    """Enqueue body target nodes for the current loop iteration."""
    r = _redis()
    q = _queue()
    body_targets = topo_data.get("loop_bodies", {}).get(loop_node_id, [])
    r.delete(_loop_iter_done_key(execution_id, loop_node_id, iter_index))

    from tasks import execute_node_job as _enqueue_node

    for target_id in body_targets:
        r.incr(_inflight_key(execution_id))
        _publish_event(execution_id, "node_enqueued", {"node_id": target_id}, workflow_slug=slug)
        if delay_seconds and delay_seconds > 0:
            q.enqueue_in(timedelta(seconds=delay_seconds), _enqueue_node, execution_id, target_id)
        else:
            q.enqueue(_enqueue_node, execution_id, target_id)


def _check_loop_body_done(execution_id: str, completed_node_id: str, topo_data: dict, db: Session, delay_seconds: float | None = None) -> bool:
    """Check if completed node is a loop body node, and if all completion nodes for this iteration are done.

    Returns True if the node was inside a loop body (caller should handle inflight differently).
    """
    r = _redis()
    loop_bodies = topo_data.get("loop_bodies", {})
    loop_return_nodes = topo_data.get("loop_return_nodes", {})
    loop_body_all = topo_data.get("loop_body_all_nodes", {})

    for loop_id, body_targets in loop_bodies.items():
        all_body = set(loop_body_all.get(loop_id, body_targets))
        if completed_node_id not in all_body:
            continue

        # Node is inside this loop's body
        return_nodes = loop_return_nodes.get(loop_id, [])
        completion_nodes = return_nodes if return_nodes else body_targets

        if completed_node_id in completion_nodes:
            # Get current iteration index
            loop_raw = r.get(_loop_key(execution_id, loop_id))
            iter_index = json.loads(loop_raw).get("index", 0) if loop_raw else 0

            done_key = _loop_iter_done_key(execution_id, loop_id, iter_index)
            count = r.incr(done_key)
            r.expire(done_key, STATE_TTL)
            if count >= len(completion_nodes):
                # All completion nodes done for this iteration
                _loop_next_iteration(execution_id, loop_id, topo_data, db, delay_seconds=delay_seconds)

        return True  # All body nodes return True (skip _finalize check)

    return False


def _loop_next_iteration(execution_id: str, loop_node_id: str, topo_data: dict, db: Session, delay_seconds: float | None = None) -> None:
    """Advance loop to next iteration or complete it."""
    r = _redis()
    loop_raw = r.get(_loop_key(execution_id, loop_node_id))
    loop_state = json.loads(loop_raw) if loop_raw else {}
    items = loop_state.get("items", [])
    index = loop_state.get("index", 0)
    results = loop_state.get("results", [])

    # Collect body outputs for this iteration
    state = load_state(execution_id)
    body_targets = loop_state.get("body_targets", [])
    return_nodes = topo_data.get("loop_return_nodes", {}).get(loop_node_id, [])
    output_nodes = return_nodes if return_nodes else body_targets

    # Check for recorded errors from on_error=continue
    loop_errors = state.get("_loop_errors", {}).get(loop_node_id, {})
    iter_output = {}
    for bt in output_nodes:
        if bt in loop_errors:
            iter_output[bt] = loop_errors[bt]
        else:
            iter_output[bt] = state.get("node_outputs", {}).get(bt)

    # Clear errors for this iteration
    if loop_node_id in state.get("_loop_errors", {}):
        del state["_loop_errors"][loop_node_id]

    results.append(iter_output)
    index += 1

    slug = topo_data.get("workflow_slug", "")

    if index < len(items):
        # More items — update loop state, set next item, re-enqueue body
        loop_state["index"] = index
        loop_state["results"] = results
        r.set(_loop_key(execution_id, loop_node_id), json.dumps(loop_state), ex=STATE_TTL)
        state["loop"] = {"item": items[index], "index": index, "total": len(items)}
        save_state(execution_id, state)
        _advance_loop_body(execution_id, loop_node_id, topo_data, slug, iter_index=index, delay_seconds=delay_seconds)
    else:
        # Loop complete — store results and advance via non-body edges
        loop_state["results"] = results
        r.set(_loop_key(execution_id, loop_node_id), json.dumps(loop_state), ex=STATE_TTL)
        node_outputs = state.get("node_outputs", {})
        if loop_node_id in node_outputs:
            node_outputs[loop_node_id]["results"] = results
        else:
            node_outputs[loop_node_id] = {"results": results}
        state["node_outputs"] = node_outputs
        # Clear loop context
        state.pop("loop", None)
        save_state(execution_id, state)
        # Advance via normal direct edges (the "done" path)
        _advance(execution_id, loop_node_id, state, topo_data, db, delay_seconds=delay_seconds)


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

    try:
        state = load_state(execution_id)
        execution.status = "completed"
        execution.final_output = _extract_output(state)
        execution.completed_at = datetime.now(timezone.utc)
        _persist_execution_costs(execution, state)
        db.commit()

        _sync_task_costs(execution_id, db)

        logger.info("Execution %s completed", execution_id)
        slug = _get_workflow_slug(execution_id, db)

        # Build activity summary from execution cost fields
        exec_usage = state.get("_execution_token_usage", {})
        duration_ms = 0
        if execution.started_at and execution.completed_at:
            sa = execution.started_at.replace(tzinfo=None) if execution.started_at.tzinfo else execution.started_at
            ca = execution.completed_at.replace(tzinfo=None) if execution.completed_at.tzinfo else execution.completed_at
            duration_ms = int((ca - sa).total_seconds() * 1000)

        # Roll up descendant execution costs (BFS to handle grandchildren)
        child_tokens = 0
        child_cost = 0.0
        child_llm_calls = 0
        child_count = 0
        try:
            queue_ids = deque([execution_id])
            while queue_ids:
                pid = queue_ids.popleft()
                children = (
                    db.query(WorkflowExecution)
                    .filter(WorkflowExecution.parent_execution_id == pid)
                    .all()
                )
                for c in children:
                    child_count += 1
                    child_tokens += c.total_tokens or 0
                    child_cost += float(c.total_cost_usd or 0)
                    child_llm_calls += c.llm_calls or 0
                    queue_ids.append(str(c.execution_id))
        except Exception:
            logger.exception("Failed to roll up child costs for execution %s", execution_id)

        activity_summary = {
            "total_steps": len(state.get("node_results", {})) + child_count,
            "total_duration_ms": duration_ms,
            "total_tokens": (execution.total_tokens or 0) + child_tokens,
            "total_cost_usd": float(execution.total_cost_usd or 0) + child_cost,
            "llm_calls": (execution.llm_calls or 0) + child_llm_calls,
            "tool_invocations": exec_usage.get("tool_invocations", 0),
            "child_count": child_count,
        }

        _publish_event(execution_id, "execution_completed", {
            "output": execution.final_output,
            "activity_summary": activity_summary,
        }, workflow_slug=slug)

        # Complete memory episode
        _complete_episode(
            execution_id=execution_id,
            success=True,
            final_output=execution.final_output,
        )

        from services.delivery import output_delivery
        output_delivery.deliver(execution, db)

        # If this execution has a parent, resume the parent's subworkflow node
        parent_eid = getattr(execution, "parent_execution_id", None)
        parent_nid = getattr(execution, "parent_node_id", None)
        if parent_eid and parent_nid and isinstance(parent_eid, str):
            logger.info(
                "Child execution %s completed, resuming parent %s at node %s",
                execution_id, parent_eid, parent_nid,
            )
            _resume_from_child(
                parent_execution_id=parent_eid,
                parent_node_id=parent_nid,
                child_output=execution.final_output,
                child_execution_id=str(execution.execution_id),
            )

    except Exception as exc:
        logger.exception("Failed to finalize execution %s", execution_id)
        # Ensure execution is marked as failed if finalization crashes
        try:
            db.rollback()
            execution = (
                db.query(WorkflowExecution)
                .filter(WorkflowExecution.execution_id == execution_id)
                .first()
            )
            if execution and execution.status not in ("failed", "completed"):
                execution.status = "failed"
                execution.error_message = f"Finalization error: {str(exc)[:1900]}"
                execution.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            logger.exception(
                "Failed to persist failure status during finalize recovery for %s",
                execution_id,
            )
    finally:
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


# ── Cost tracking helpers ──────────────────────────────────────────────────────


def _persist_execution_costs(execution, state: dict) -> None:
    """Copy accumulated token usage from execution state to the WorkflowExecution model."""
    exec_usage = state.get("_execution_token_usage", {})
    execution.total_input_tokens = exec_usage.get("input_tokens", 0)
    execution.total_output_tokens = exec_usage.get("output_tokens", 0)
    execution.total_tokens = exec_usage.get("total_tokens", 0)
    execution.total_cost_usd = exec_usage.get("cost_usd", 0.0)
    execution.llm_calls = exec_usage.get("llm_calls", 0)


def _check_budget(execution_id: str, state: dict, db: Session) -> str | None:
    """Check if the execution's epic budget has been exceeded.

    Returns an error message string if budget is exceeded, None otherwise.
    """
    try:
        from models.epic import Task

        task = db.query(Task).filter(Task.execution_id == execution_id).first()
        if not task or not task.epic:
            return None

        epic = task.epic
        exec_usage = state.get("_execution_token_usage", {})
        current_tokens = exec_usage.get("total_tokens", 0)
        current_usd = exec_usage.get("cost_usd", 0.0)

        if epic.budget_tokens is not None:
            total_tokens = (epic.spent_tokens or 0) + current_tokens
            if total_tokens > epic.budget_tokens:
                return (
                    f"Epic budget exceeded: {total_tokens} tokens used "
                    f"(budget: {epic.budget_tokens} tokens)"
                )

        if epic.budget_usd is not None:
            total_usd = float(epic.spent_usd or 0) + current_usd
            if total_usd > float(epic.budget_usd):
                return (
                    f"Epic budget exceeded: ${total_usd:.4f} spent "
                    f"(budget: ${float(epic.budget_usd):.4f})"
                )

    except Exception:
        logger.exception("Budget check failed for execution %s", execution_id)

    return None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_initial_state(execution) -> dict:
    from langchain_core.messages import HumanMessage

    payload = execution.trigger_payload or {}
    messages = []
    text = payload.get("text", "")
    if text:
        messages.append(HumanMessage(
            content=text,
            additional_kwargs={"timestamp": datetime.now(timezone.utc).isoformat() + "Z"},
        ))
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
        "_is_child_execution": bool(execution.parent_execution_id),
        "_spawn_depth": int(payload.get("_spawn_depth", 0)),
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
    # Prefer last AI message (conversational response) over node_outputs
    messages = state.get("messages", [])
    if messages:
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "ai" and hasattr(msg, "content") and msg.content:
                return {"message": msg.content}
    node_outputs = state.get("node_outputs", {})
    if node_outputs:
        return {"node_outputs": node_outputs}
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


def _truncate_output(obj, max_str_len: int = 2048) -> dict | None:
    """Truncate large string values in output for WebSocket events."""
    if obj is None:
        return None
    try:
        if isinstance(obj, str):
            return obj[:max_str_len] if len(obj) > max_str_len else obj
        if isinstance(obj, dict):
            truncated = {}
            for k, v in obj.items():
                if isinstance(v, str) and len(v) > max_str_len:
                    truncated[k] = v[:max_str_len] + "..."
                else:
                    truncated[k] = v
            json.dumps(truncated)
            return truncated
        return {"repr": repr(obj)[:1000]}
    except (TypeError, ValueError):
        return {"repr": repr(obj)[:1000]}


def _get_workflow_slug(execution_id: str, db: Session | None = None) -> str | None:
    """Look up workflow slug for an execution (cached in topo or from DB)."""
    try:
        topo = _load_topology(execution_id)
        slug = topo.get("workflow_slug")
        if slug:
            return slug
    except Exception:
        logger.debug("Topology lookup failed for %s", execution_id, exc_info=True)
    if db:
        from models.execution import WorkflowExecution
        from models.workflow import Workflow
        ex = db.query(WorkflowExecution).filter(WorkflowExecution.execution_id == execution_id).first()
        if ex:
            wf = db.query(Workflow).filter(Workflow.id == ex.workflow_id).first()
            if wf:
                return wf.slug
    return None


def _sync_task_costs(execution_id: str, db: Session) -> None:
    """Sync Task status and duration from a completed/failed execution."""
    try:
        from models.epic import Task
        from models.execution import WorkflowExecution
        from api.epic_helpers import sync_epic_progress

        task = db.query(Task).filter(Task.execution_id == execution_id).first()
        if not task:
            return

        execution = (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == execution_id)
            .first()
        )
        if not execution:
            return

        if execution.status not in ("completed", "failed"):
            return

        if execution.status == "completed":
            task.status = "completed"
            if execution.final_output:
                summary = str(execution.final_output)
                task.result_summary = summary[:500]
        elif execution.status == "failed":
            task.status = "failed"
            task.error_message = (execution.error_message or "")[:500]

        if execution.started_at and execution.completed_at:
            # Normalise both to naive UTC to avoid mixed-tz subtraction errors
            sa = execution.started_at.replace(tzinfo=None) if execution.started_at.tzinfo else execution.started_at
            ca = execution.completed_at.replace(tzinfo=None) if execution.completed_at.tzinfo else execution.completed_at
            delta = ca - sa
            task.duration_ms = int(delta.total_seconds() * 1000)

        task.completed_at = execution.completed_at

        # Sync cost fields from execution to task
        task.actual_tokens = execution.total_tokens or 0
        task.actual_usd = float(execution.total_cost_usd or 0)
        task.llm_calls = execution.llm_calls or 0
        # tool_invocations from accumulated state
        try:
            exec_state = load_state(execution_id)
            exec_usage = exec_state.get("_execution_token_usage", {})
            task.tool_invocations = exec_usage.get("tool_invocations", 0)
        except Exception:
            logger.exception("Failed to load tool_invocations for task %s", task.id)

        db.commit()
        logger.info("Synced task %s costs from execution %s (status=%s)", task.id, execution_id, task.status)

        # Roll up costs to epic (recalculate from all tasks to avoid double-counting)
        if task.epic:
            epic = task.epic
            from sqlalchemy import func as sa_func
            from models.epic import Task as _Task
            totals = db.query(
                sa_func.coalesce(sa_func.sum(_Task.actual_tokens), 0),
                sa_func.coalesce(sa_func.sum(_Task.actual_usd), 0),
            ).filter(_Task.epic_id == epic.id).one()
            epic.spent_tokens = int(totals[0])
            epic.spent_usd = float(totals[1])
            db.commit()

        # Auto-unblock dependent tasks when this task is completed
        if task.status == "completed":
            try:
                from api.epic_helpers import resolve_blocked_tasks
                resolve_blocked_tasks(task.id, db)
                db.commit()
            except Exception:
                logger.exception("Failed to resolve blocked tasks for task %s", task.id)

        # Sync epic progress counters (best-effort — task status already committed)
        if task.epic:
            try:
                sync_epic_progress(task.epic, db)
                db.commit()
            except Exception:
                logger.exception("Failed to sync epic progress for task %s", task.id)

    except Exception:
        logger.exception("Failed to sync task costs for execution %s", execution_id)


def _clear_stale_checkpoints(execution_id: str, db: Session) -> None:
    """Clear SqliteSaver checkpoints for agent threads in a failed/cancelled execution.

    When an agent with conversation_memory fails mid-interrupt (e.g. during
    spawn_and_await), the SqliteSaver checkpoint retains orphaned tool_calls
    with no ToolMessage.  On the next conversation turn the same thread_id is
    reused and LangGraph raises INVALID_CHAT_HISTORY.  This helper deletes
    those stale checkpoints so the next turn starts fresh.
    """
    try:
        from models.execution import WorkflowExecution
        from models.node import WorkflowEdge, WorkflowNode

        execution = (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == execution_id)
            .first()
        )
        if not execution:
            return

        # Find agent nodes with conversation_memory in this workflow
        agent_nodes = (
            db.query(WorkflowNode)
            .filter(
                WorkflowNode.workflow_id == execution.workflow_id,
                WorkflowNode.component_type == "agent",
            )
            .all()
        )

        thread_ids_to_clear: list[str] = []
        for agent_node in agent_nodes:
            cfg = agent_node.component_config
            if not cfg:
                continue
            extra = getattr(cfg, "extra_config", None) or {}
            if not extra.get("conversation_memory"):
                continue

            # Reconstruct the thread_id (same logic as agent.py)
            user_id = execution.user_profile_id or "anon"
            payload = execution.trigger_payload or {}
            chat_id = payload.get("chat_id", "")
            if chat_id:
                thread_id = f"{user_id}:{chat_id}:{execution.workflow_id}"
            else:
                thread_id = f"{user_id}:{execution.workflow_id}"
            thread_ids_to_clear.append(thread_id)

        if not thread_ids_to_clear:
            return

        # Use the SqliteSaver singleton to delete threads
        from components.agent import _get_checkpointer

        checkpointer = _get_checkpointer()
        for thread_id in thread_ids_to_clear:
            try:
                checkpointer.delete_thread(thread_id)
                logger.info(
                    "Cleared stale checkpoint for thread %s (execution %s)",
                    thread_id, execution_id,
                )
            except AttributeError:
                # Fallback: delete directly via SQL if delete_thread not available
                import sqlite3
                import os

                db_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "checkpoints.db",
                )
                conn = sqlite3.connect(db_path)
                try:
                    with conn:
                        conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
                        conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
                    logger.info(
                        "Cleared stale checkpoint (SQL fallback) for thread %s",
                        thread_id,
                    )
                finally:
                    conn.close()

    except Exception:
        logger.exception(
            "Failed to clear stale checkpoints for execution %s", execution_id,
        )


def _cleanup_redis(execution_id: str) -> None:
    """Remove execution keys from Redis."""
    r = _redis()
    keys = r.keys(f"execution:{execution_id}:*")
    if keys:
        r.delete(*keys)


# ── Episode logging helpers ───────────────────────────────────────────────────


def _start_episode(
    execution_id: str,
    workflow_id: int,
    trigger_type: str,
    trigger_payload: dict | None,
    db: Session,
) -> str | None:
    """Start a memory episode for this execution."""
    try:
        from services.memory import MemoryService

        memory = MemoryService(db)

        # Extract user ID from trigger payload if possible
        user_id = None
        if trigger_payload:
            if "message" in trigger_payload and "from" in trigger_payload.get("message", {}):
                from_user = trigger_payload["message"]["from"]
                user_id = f"telegram:{from_user.get('id', '')}"
            elif trigger_payload.get("user_id"):
                user_id = trigger_payload["user_id"]

        episode = memory.log_episode(
            agent_id=f"workflow:{workflow_id}",
            trigger_type=trigger_type,
            trigger_input=trigger_payload,
            user_id=user_id,
            session_id=execution_id,
            workflow_id=workflow_id,
            execution_id=execution_id,
        )

        # Store episode ID in Redis for later completion
        r = _redis()
        r.set(_episode_key(execution_id), episode.id, ex=STATE_TTL)

        logger.debug("Started memory episode %s for execution %s", episode.id, execution_id)
        return episode.id

    except Exception as e:
        logger.warning("Failed to start memory episode: %s", e)
        return None


def _complete_episode(
    execution_id: str,
    success: bool,
    final_output: dict | None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Complete the memory episode for this execution."""
    try:
        r = _redis()
        episode_id = r.get(_episode_key(execution_id))
        if not episode_id:
            return

        from database import SessionLocal
        from services.memory import MemoryService

        db = SessionLocal()
        try:
            memory = MemoryService(db)

            # Get execution state for conversation and actions
            state = load_state(execution_id)
            conversation = []
            messages = state.get("messages", [])
            for msg in messages:
                if hasattr(msg, "type") and hasattr(msg, "content"):
                    conversation.append({"role": msg.type, "content": msg.content})
                elif isinstance(msg, dict):
                    conversation.append(msg)

            # Extract actions from node_results
            actions = []
            node_results = state.get("node_results", {})
            for node_id, result in node_results.items():
                if isinstance(result, dict):
                    actions.append({
                        "node_id": node_id,
                        "status": result.get("status", "unknown"),
                        "duration_ms": result.get("duration_ms"),
                    })

            memory.complete_episode(
                episode_id=episode_id,
                success=success,
                final_output=final_output,
                conversation=conversation,
                actions_taken=actions,
                error_code=error_code,
                error_message=error_message,
            )

            logger.debug("Completed memory episode %s (success=%s)", episode_id, success)

        finally:
            db.close()

    except Exception as e:
        logger.warning("Failed to complete memory episode: %s", e)


# ── RQ entry points (module-level for pickling) ───────────────────────────────


def start_execution_job(execution_id: str) -> None:
    start_execution(execution_id)
