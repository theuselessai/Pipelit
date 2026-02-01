"""Node + Edge CRUD router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
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
from models.user import UserProfile
from schemas.node import EdgeIn, EdgeOut, EdgeUpdate, NodeIn, NodeOut, NodeUpdate
from api._helpers import get_workflow, serialize_edge, serialize_node
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
    return [serialize_node(n) for n in nodes]


@router.post("/{slug}/nodes/", response_model=NodeOut, status_code=201)
def create_node(
    slug: str,
    payload: NodeIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    config_data = payload.config.model_dump()
    component_type = payload.component_type

    kwargs = {
        "component_type": component_type,
        "extra_config": config_data.get("extra_config", {}),
    }

    # AI config fields
    if component_type in ("simple_agent", "planner_agent", "categorizer", "router", "extractor"):
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

    cc = BaseComponentConfig(**kwargs)
    db.add(cc)
    db.flush()

    node = WorkflowNode(
        workflow_id=wf.id,
        node_id=payload.node_id,
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
    db.refresh(node)
    result = serialize_node(node)
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
    result = serialize_node(node)
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
