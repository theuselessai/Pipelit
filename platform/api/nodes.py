"""Node + Edge CRUD router."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.node import (
    COMPONENT_TYPE_TO_CONFIG,
    BaseComponentConfig,
    ModelComponentConfig,
    TriggerComponentConfig,
    WorkflowEdge,
    WorkflowNode,
)
from models.scheduled_job import ScheduledJob
from models.user import UserProfile
from schemas.node import EdgeIn, EdgeOut, EdgeUpdate, NodeIn, NodeOut, NodeUpdate
from api._helpers import get_workflow, serialize_edge, serialize_node
from services.scheduler import pause_scheduled_job, resume_scheduled_job, start_scheduled_job
from ws.broadcast import broadcast

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _link_sub_component(
    db: Session, workflow_id: int, source_node_id: str, target_node_id: str, config_field: str
):
    """Set a FK on the target node's config pointing to the source node's config."""
    src = db.query(WorkflowNode).filter_by(workflow_id=workflow_id, node_id=source_node_id).first()
    tgt = db.query(WorkflowNode).filter_by(workflow_id=workflow_id, node_id=target_node_id).first()
    if src and tgt and src.component_config_id and tgt.component_config_id:
        tgt_cfg = db.get(BaseComponentConfig, tgt.component_config_id)
        if tgt_cfg:
            setattr(tgt_cfg, config_field, src.component_config_id)


def _unlink_sub_component(
    db: Session, workflow_id: int, target_node_id: str, config_field: str
):
    """Clear a sub-component FK on the target node's config."""
    tgt = db.query(WorkflowNode).filter_by(workflow_id=workflow_id, node_id=target_node_id).first()
    if tgt and tgt.component_config_id:
        tgt_cfg = db.get(BaseComponentConfig, tgt.component_config_id)
        if tgt_cfg:
            setattr(tgt_cfg, config_field, None)


# ── Nodes ─────────────────────────────────────────────────────────────────────


@router.get("/{slug}/nodes/", response_model=list[NodeOut])
def list_nodes(
    slug: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf.id).all()
    return [serialize_node(n, db) for n in nodes]


@router.post("/{slug}/nodes/", response_model=NodeOut, status_code=201)
def create_node(
    slug: str,
    payload: NodeIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)

    # Auto-generate node_id if not provided
    node_id = payload.node_id
    if not node_id:
        for _ in range(10):
            candidate = f"{payload.component_type}_{secrets.token_hex(4)}"
            exists = db.query(WorkflowNode).filter_by(workflow_id=wf.id, node_id=candidate).first()
            if not exists:
                node_id = candidate
                break
        if not node_id:
            node_id = f"{payload.component_type}_{secrets.token_hex(8)}"

    config_data = payload.config.model_dump()
    component_type = payload.component_type

    kwargs = {
        "component_type": component_type,
        "extra_config": config_data.get("extra_config", {}),
    }

    # AI config fields
    if component_type in ("agent", "categorizer", "router", "extractor"):
        kwargs["system_prompt"] = config_data.get("system_prompt", "")

    # Model config fields
    if component_type == "ai_model":
        kwargs["llm_credential_id"] = config_data.get("llm_credential_id")
        kwargs["model_name"] = config_data.get("model_name", "")
        for param in ("temperature", "max_tokens", "frequency_penalty", "presence_penalty",
                       "top_p", "timeout", "max_retries", "response_format"):
            if config_data.get(param) is not None:
                kwargs[param] = config_data[param]

    # Trigger config fields
    if component_type.startswith("trigger_"):
        kwargs["credential_id"] = config_data.get("credential_id")
        kwargs["is_active"] = config_data.get("is_active", True)
        kwargs["priority"] = config_data.get("priority", 0)
        kwargs["trigger_config"] = config_data.get("trigger_config", {})

    # NOTE: cc and node are created in the same transaction. If commit fails
    # (IntegrityError on node_id collision), rollback reverts BOTH the cc INSERT
    # and node INSERT — no orphaned config records are left behind.
    cc = BaseComponentConfig(**kwargs)
    db.add(cc)
    db.flush()

    node = WorkflowNode(
        workflow_id=wf.id,
        node_id=node_id,
        label=payload.label,
        component_type=component_type,
        component_config_id=cc.id,
        is_entry_point=payload.is_entry_point,
        interrupt_before=payload.interrupt_before,
        interrupt_after=payload.interrupt_after,
        position_x=payload.position_x,
        position_y=payload.position_y,
        subworkflow_id=payload.subworkflow_id,
        code_block_id=payload.code_block_id,
    )
    db.add(node)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Collision on auto-generated node_id — recreate objects after rollback
        # (rollback expires all ORM objects, so we must create fresh instances)
        if not payload.node_id:
            node_id = f"{payload.component_type}_{secrets.token_hex(8)}"
            cc = BaseComponentConfig(**kwargs)
            db.add(cc)
            db.flush()
            node = WorkflowNode(
                workflow_id=wf.id,
                node_id=node_id,
                label=payload.label,
                component_type=component_type,
                component_config_id=cc.id,
                is_entry_point=payload.is_entry_point,
                interrupt_before=payload.interrupt_before,
                interrupt_after=payload.interrupt_after,
                position_x=payload.position_x,
                position_y=payload.position_y,
                subworkflow_id=payload.subworkflow_id,
                code_block_id=payload.code_block_id,
            )
            db.add(node)
            db.commit()
        else:
            raise HTTPException(status_code=409, detail=f"Node with id '{node_id}' already exists.")
    db.refresh(node)
    result = serialize_node(node, db)
    broadcast(f"workflow:{slug}", "node_created", result)
    return result


@router.patch("/{slug}/nodes/{node_id}/", response_model=NodeOut)
def update_node(
    slug: str,
    node_id: str,
    payload: NodeUpdate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    node = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == wf.id, WorkflowNode.node_id == node_id)
        .first()
    )
    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")

    data = payload.model_dump(exclude_unset=True)
    config_data = data.pop("config", None)

    if config_data:
        cc = node.component_config
        model_fields = (
            "llm_credential_id", "model_name", "temperature", "max_tokens",
            "frequency_penalty", "presence_penalty", "top_p", "timeout",
            "max_retries", "response_format",
        )
        trigger_fields = ("credential_id", "is_active", "priority", "trigger_config")

        for k, v in config_data.items():
            if k in model_fields and cc.component_type == "ai_model":
                setattr(cc, k, v)
            elif k in trigger_fields and cc.component_type.startswith("trigger_"):
                setattr(cc, k, v)
            elif k == "system_prompt":
                cc.system_prompt = v
            elif k == "extra_config":
                cc.extra_config = v

    for attr, value in data.items():
        setattr(node, attr, value)

    db.commit()
    db.refresh(node)
    result = serialize_node(node, db)
    broadcast(f"workflow:{slug}", "node_updated", result)
    return result


@router.delete("/{slug}/nodes/{node_id}/", status_code=204)
def delete_node(
    slug: str,
    node_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    node = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == wf.id, WorkflowNode.node_id == node_id)
        .first()
    )
    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")

    # Clean up any scheduled job for trigger_schedule nodes
    if node.component_type == "trigger_schedule":
        sched_job = db.query(ScheduledJob).filter(
            ScheduledJob.workflow_id == wf.id,
            ScheduledJob.trigger_node_id == node_id,
        ).first()
        if sched_job:
            if sched_job.status == "active":
                pause_scheduled_job(sched_job)
            db.delete(sched_job)

    # Delete edges referencing this node
    db.query(WorkflowEdge).filter(
        WorkflowEdge.workflow_id == wf.id,
        (WorkflowEdge.source_node_id == node_id) | (WorkflowEdge.target_node_id == node_id),
    ).delete(synchronize_session=False)

    deleted_node_id = node.node_id
    cc_id = node.component_config_id
    db.delete(node)
    # Delete the config
    cc = db.query(BaseComponentConfig).filter(BaseComponentConfig.id == cc_id).first()
    if cc:
        db.delete(cc)
    db.commit()
    broadcast(f"workflow:{slug}", "node_deleted", {"node_id": deleted_node_id})


# ── Schedule Actions ──────────────────────────────────────────────────────────


def _get_schedule_node(slug: str, node_id: str, db: Session, profile: UserProfile):
    """Fetch workflow + trigger_schedule node, raising 404/400 as needed."""
    wf = get_workflow(slug, profile, db)
    node = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == wf.id, WorkflowNode.node_id == node_id)
        .first()
    )
    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")
    if node.component_type != "trigger_schedule":
        raise HTTPException(status_code=400, detail="Node is not a trigger_schedule.")
    return wf, node


@router.post("/{slug}/nodes/{node_id}/schedule/start/", response_model=NodeOut)
def schedule_start(
    slug: str,
    node_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf, node = _get_schedule_node(slug, node_id, db, profile)
    cc = node.component_config
    extra = cc.extra_config or {}

    interval = int(extra.get("interval_seconds", 300))
    total_repeats = int(extra.get("total_repeats", 0))
    max_retries = int(extra.get("max_retries", 3))
    timeout = int(extra.get("timeout_seconds", 600))
    payload = extra.get("trigger_payload") or {}

    if interval < 1:
        raise HTTPException(status_code=422, detail="interval_seconds must be >= 1")

    job = db.query(ScheduledJob).filter(
        ScheduledJob.workflow_id == wf.id,
        ScheduledJob.trigger_node_id == node_id,
    ).first()

    if not job:
        # Create new job
        job = ScheduledJob(
            name=f"schedule:{node_id}",
            workflow_id=wf.id,
            trigger_node_id=node_id,
            user_profile_id=profile.id,
            interval_seconds=interval,
            total_repeats=total_repeats,
            max_retries=max_retries,
            timeout_seconds=timeout,
            trigger_payload=payload if payload else None,
        )
        db.add(job)
        db.flush()
        start_scheduled_job(job)
    elif job.status == "paused":
        job.interval_seconds = interval
        job.total_repeats = total_repeats
        job.max_retries = max_retries
        job.timeout_seconds = timeout
        job.trigger_payload = payload if payload else None
        resume_scheduled_job(job)
    elif job.status in ("done", "dead"):
        job.current_repeat = 0
        job.current_retry = 0
        job.error_count = 0
        job.run_count = 0
        job.last_error = ""
        job.interval_seconds = interval
        job.total_repeats = total_repeats
        job.max_retries = max_retries
        job.timeout_seconds = timeout
        job.trigger_payload = payload if payload else None
        job.status = "active"
        start_scheduled_job(job)
    else:
        # Active — just update params
        job.interval_seconds = interval
        job.total_repeats = total_repeats
        job.max_retries = max_retries
        job.timeout_seconds = timeout
        job.trigger_payload = payload if payload else None

    cc.is_active = True
    db.commit()
    db.refresh(node)
    result = serialize_node(node, db)
    broadcast(f"workflow:{slug}", "node_updated", result)
    return result


@router.post("/{slug}/nodes/{node_id}/schedule/pause/", response_model=NodeOut)
def schedule_pause(
    slug: str,
    node_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf, node = _get_schedule_node(slug, node_id, db, profile)
    job = db.query(ScheduledJob).filter(
        ScheduledJob.workflow_id == wf.id,
        ScheduledJob.trigger_node_id == node_id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="No scheduled job found for this node.")
    if job.status != "active":
        raise HTTPException(status_code=400, detail=f"Cannot pause job with status '{job.status}'.")

    pause_scheduled_job(job)
    node.component_config.is_active = False
    db.commit()
    db.refresh(node)
    result = serialize_node(node, db)
    broadcast(f"workflow:{slug}", "node_updated", result)
    return result


@router.post("/{slug}/nodes/{node_id}/schedule/stop/", response_model=NodeOut)
def schedule_stop(
    slug: str,
    node_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf, node = _get_schedule_node(slug, node_id, db, profile)
    job = db.query(ScheduledJob).filter(
        ScheduledJob.workflow_id == wf.id,
        ScheduledJob.trigger_node_id == node_id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="No scheduled job found for this node.")

    if job.status == "active":
        pause_scheduled_job(job)
    db.delete(job)
    node.component_config.is_active = False
    db.commit()
    db.refresh(node)
    result = serialize_node(node, db)
    broadcast(f"workflow:{slug}", "node_updated", result)
    return result


# ── Edges ─────────────────────────────────────────────────────────────────────


@router.get("/{slug}/edges/", response_model=list[EdgeOut])
def list_edges(
    slug: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf.id).all()
    return [serialize_edge(e) for e in edges]


@router.post("/{slug}/edges/", response_model=EdgeOut, status_code=201)
def create_edge(
    slug: str,
    payload: EdgeIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)

    # Enforce switch-only conditional edges
    if payload.edge_type == "conditional":
        if not payload.condition_value:
            raise HTTPException(status_code=422, detail="Conditional edges require a non-empty condition_value")
        if not payload.target_node_id:
            raise HTTPException(status_code=422, detail="Conditional edges require a non-empty target_node_id")
        src_node = db.query(WorkflowNode).filter_by(workflow_id=wf.id, node_id=payload.source_node_id).first()
        if not src_node or src_node.component_type != "switch":
            raise HTTPException(status_code=422, detail="Conditional edges can only originate from 'switch' nodes")

    # Validate edge type compatibility (skip loop flow-control edges)
    if payload.source_node_id and payload.target_node_id and payload.edge_label not in ("loop_body", "loop_return"):
        src_node = db.query(WorkflowNode).filter_by(workflow_id=wf.id, node_id=payload.source_node_id).first()
        tgt_node = db.query(WorkflowNode).filter_by(workflow_id=wf.id, node_id=payload.target_node_id).first()
        if src_node and tgt_node:
            from validation.edges import EdgeValidator
            # "memory" was intentionally removed — memory nodes now connect via "tool" handle.
            # See migration 0d301d48b86a which converted all memory edges to tool edges.
            label_to_handle = {"llm": "model", "tool": "tools", "output_parser": "output_parser"}
            target_handle = label_to_handle.get(payload.edge_label) if payload.edge_label else None
            errors = EdgeValidator.validate_edge(
                src_node.component_type, tgt_node.component_type,
                target_handle=target_handle,
            )
            if errors:
                raise HTTPException(status_code=422, detail={"validation_errors": errors})

    edge = WorkflowEdge(workflow_id=wf.id, **payload.model_dump())
    db.add(edge)
    db.flush()

    # Link sub-component configs when connecting via labeled handles
    if payload.edge_label == "llm":
        _link_sub_component(db, wf.id, payload.source_node_id, payload.target_node_id, "llm_model_config_id")

    db.commit()
    db.refresh(edge)
    result = serialize_edge(edge)
    broadcast(f"workflow:{slug}", "edge_created", result)
    return result


@router.patch("/{slug}/edges/{edge_id}/", response_model=EdgeOut)
def update_edge(
    slug: str,
    edge_id: int,
    payload: EdgeUpdate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    edge = (
        db.query(WorkflowEdge)
        .filter(WorkflowEdge.workflow_id == wf.id, WorkflowEdge.id == edge_id)
        .first()
    )
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found.")
    for attr, value in payload.model_dump(exclude_unset=True).items():
        setattr(edge, attr, value)
    db.commit()
    db.refresh(edge)
    result = serialize_edge(edge)
    broadcast(f"workflow:{slug}", "edge_updated", result)
    return result


@router.delete("/{slug}/edges/{edge_id}/", status_code=204)
def delete_edge(
    slug: str,
    edge_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    edge = (
        db.query(WorkflowEdge)
        .filter(WorkflowEdge.workflow_id == wf.id, WorkflowEdge.id == edge_id)
        .first()
    )
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found.")

    # Unlink sub-component config when removing a labeled edge
    if edge.edge_label == "llm":
        _unlink_sub_component(db, wf.id, edge.target_node_id, "llm_model_config_id")

    deleted_edge_id = edge.id
    db.delete(edge)
    db.commit()
    broadcast(f"workflow:{slug}", "edge_deleted", {"id": deleted_edge_id})
