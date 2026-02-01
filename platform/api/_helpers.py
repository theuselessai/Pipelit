"""Shared helpers for API routers."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models.node import BaseComponentConfig, ModelComponentConfig, TriggerComponentConfig, WorkflowEdge, WorkflowNode
from models.user import UserProfile
from models.workflow import Workflow, WorkflowCollaborator


def get_workflow(slug: str, profile: UserProfile, db: Session) -> Workflow:
    """Look up a workflow by slug, checking ownership or collaboration."""
    wf = (
        db.query(Workflow)
        .filter(
            Workflow.slug == slug,
            Workflow.deleted_at.is_(None),
            or_(
                Workflow.owner_id == profile.id,
                Workflow.id.in_(
                    db.query(WorkflowCollaborator.workflow_id)
                    .filter(WorkflowCollaborator.user_profile_id == profile.id)
                ),
            ),
        )
        .first()
    )
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return wf


def serialize_config(cc: BaseComponentConfig) -> dict:
    """Serialize a component config to the ComponentConfigData shape."""
    result = {
        "system_prompt": cc.system_prompt or "",
        "extra_config": cc.extra_config or {},
        "llm_credential_id": None,
        "model_name": "",
        "temperature": None,
        "max_tokens": None,
        "frequency_penalty": None,
        "presence_penalty": None,
        "top_p": None,
        "timeout": None,
        "max_retries": None,
        "response_format": None,
        "credential_id": None,
        "is_active": True,
        "priority": 0,
        "trigger_config": {},
    }

    if isinstance(cc, ModelComponentConfig) or cc.component_type == "ai_model":
        result["llm_credential_id"] = cc.llm_credential_id
        result["model_name"] = cc.model_name or ""
        result["temperature"] = cc.temperature
        result["max_tokens"] = cc.max_tokens
        result["frequency_penalty"] = cc.frequency_penalty
        result["presence_penalty"] = cc.presence_penalty
        result["top_p"] = cc.top_p
        result["timeout"] = cc.timeout
        result["max_retries"] = cc.max_retries
        result["response_format"] = cc.response_format
    elif isinstance(cc, TriggerComponentConfig) or cc.component_type.startswith("trigger_"):
        result["credential_id"] = cc.credential_id
        result["is_active"] = cc.is_active if cc.is_active is not None else True
        result["priority"] = cc.priority if cc.priority is not None else 0
        result["trigger_config"] = cc.trigger_config or {}

    return result


def serialize_node(node: WorkflowNode) -> dict:
    """Serialize a WorkflowNode to NodeOut shape."""
    return {
        "id": node.id,
        "node_id": node.node_id,
        "component_type": node.component_type,
        "is_entry_point": node.is_entry_point,
        "interrupt_before": node.interrupt_before,
        "interrupt_after": node.interrupt_after,
        "position_x": node.position_x,
        "position_y": node.position_y,
        "config": serialize_config(node.component_config),
        "subworkflow_id": node.subworkflow_id,
        "code_block_id": node.code_block_id,
        "updated_at": node.updated_at,
    }


def serialize_edge(edge: WorkflowEdge) -> dict:
    """Serialize a WorkflowEdge to EdgeOut shape."""
    return {
        "id": edge.id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "edge_type": edge.edge_type,
        "edge_label": edge.edge_label or "",
        "condition_mapping": edge.condition_mapping,
        "priority": edge.priority,
    }


def serialize_workflow(wf: Workflow, db: Session) -> dict:
    """Serialize a Workflow to WorkflowOut shape."""
    node_count = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf.id).count()
    edge_count = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf.id).count()
    return {
        "id": wf.id,
        "name": wf.name,
        "slug": wf.slug,
        "description": wf.description,
        "is_active": wf.is_active,
        "is_public": wf.is_public,
        "is_default": wf.is_default,
        "error_handler_workflow_id": wf.error_handler_workflow_id,
        "input_schema": wf.input_schema,
        "output_schema": wf.output_schema,
        "node_count": node_count,
        "edge_count": edge_count,
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
    }


def serialize_workflow_detail(wf: Workflow, db: Session) -> dict:
    """Serialize a Workflow to WorkflowDetailOut shape (with nodes and edges)."""
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf.id).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf.id).all()
    data = serialize_workflow(wf, db)
    data["nodes"] = [serialize_node(n) for n in nodes]
    data["edges"] = [serialize_edge(e) for e in edges]
    return data
