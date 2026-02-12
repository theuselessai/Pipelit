"""Workflow discovery — search existing workflows by requirements and score matches."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def discover_workflows(
    requirements: dict[str, Any],
    db: Session,
    exclude_workflow_id: int | None = None,
    limit: int = 5,
) -> tuple[list[dict], int]:
    """Search active workflows, score them against requirements, return top-N matches.

    Args:
        requirements: Dict with optional keys: triggers, node_types, tools, tags,
                      description, model_capability.
        db: SQLAlchemy session.
        exclude_workflow_id: Workflow ID to exclude (caller's own).
        limit: Maximum results to return.

    Returns:
        Tuple of (matches list sorted by score descending, total workflows searched).
    """
    from models.workflow import Workflow

    query = db.query(Workflow).filter(
        Workflow.is_active.is_(True),
        Workflow.deleted_at.is_(None),
    )
    if exclude_workflow_id is not None:
        query = query.filter(Workflow.id != exclude_workflow_id)

    workflows = query.all()

    results = []
    for wf in workflows:
        caps = _extract_capabilities(wf.id, db, wf)
        success_rate, exec_count = _compute_success_rate(wf.id, db)
        score = _score_workflow(caps, requirements, success_rate, wf.description or "")

        # Gap analysis
        req_triggers = set(requirements.get("triggers") or [])
        req_node_types = set(requirements.get("node_types") or [])
        req_tools = set(requirements.get("tools") or [])

        has_triggers = set(caps["triggers"])
        has_node_types = set(caps["node_types"])
        has_tools = set(caps["tools"])

        missing = {
            "triggers": sorted(req_triggers - has_triggers),
            "node_types": sorted(req_node_types - has_node_types),
            "tools": sorted(req_tools - has_tools),
        }
        extra = {
            "triggers": sorted(has_triggers - req_triggers),
            "node_types": sorted(has_node_types - req_node_types),
            "tools": sorted(has_tools - req_tools),
        }

        # Recommendation thresholds
        if score >= 0.95:
            recommendation = "reuse"
        elif score >= 0.50:
            recommendation = "fork_and_patch"
        else:
            recommendation = "create_new"

        results.append({
            "workflow_id": wf.id,
            "slug": wf.slug,
            "name": wf.name,
            "description": wf.description or "",
            "tags": wf.tags or [],
            "match_score": round(score, 4),
            "has_capabilities": {
                "triggers": sorted(has_triggers),
                "node_types": sorted(has_node_types),
                "tools": sorted(has_tools),
                "model_names": caps["model_names"],
            },
            "missing_capabilities": missing,
            "extra_capabilities": extra,
            "recommendation": recommendation,
            "success_rate": success_rate,
            "execution_count": exec_count,
        })

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results[:limit], len(workflows)


def _extract_capabilities(workflow_id: int, db: Session, workflow: Any = None) -> dict:
    """Extract capability summary from a workflow's nodes.

    Returns dict with keys: triggers, node_types, tools, model_names, tags.
    """
    from models.node import WorkflowNode
    from services.topology import SUB_COMPONENT_TYPES

    nodes = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == workflow_id)
        .all()
    )

    triggers: list[str] = []
    node_types: list[str] = []
    tools: list[str] = []
    model_names: list[str] = []

    tool_types = {"run_command", "http_request", "web_search", "calculator", "datetime", "code_execute"}

    for node in nodes:
        ct = node.component_type
        if ct.startswith("trigger_"):
            triggers.append(ct.removeprefix("trigger_"))
        elif ct in tool_types:
            tools.append(ct)
        elif ct == "ai_model":
            cfg = node.component_config
            if cfg and cfg.model_name:
                model_names.append(cfg.model_name)
        elif ct not in SUB_COMPONENT_TYPES:
            # Executable non-sub-component nodes
            node_types.append(ct)

    # Tags from workflow (use passed object to avoid extra query)
    wf = workflow
    if wf is None:
        from models.workflow import Workflow
        wf = db.query(Workflow).filter_by(id=workflow_id).first()
    tags = list(wf.tags) if wf and wf.tags else []

    return {
        "triggers": sorted(set(triggers)),
        "node_types": sorted(set(node_types)),
        "tools": sorted(set(tools)),
        "model_names": sorted(set(model_names)),
        "tags": tags,
    }


def _compute_success_rate(workflow_id: int, db: Session) -> tuple[float | None, int]:
    """Compute success rate from terminal executions.

    Returns (rate, total_count) or (None, 0) if no terminal executions.
    """
    from models.execution import WorkflowExecution

    terminal = (
        db.query(WorkflowExecution)
        .filter(
            WorkflowExecution.workflow_id == workflow_id,
            WorkflowExecution.status.in_(("completed", "failed")),
        )
        .all()
    )

    total = len(terminal)
    if total == 0:
        return None, 0

    completed = sum(1 for e in terminal if e.status == "completed")
    return completed / total, total


def _score_workflow(
    capabilities: dict,
    requirements: dict[str, Any],
    success_rate: float | None,
    description: str,
) -> float:
    """Score a workflow against requirements.

    Weighted: capability_match * 0.8 + tag_overlap * 0.1 + success_rate * 0.1
    Plus description substring bonus (+0.05, capped at 1.0).

    Capability match is the dominant signal so a perfect match can reach the
    "reuse" threshold (>= 0.95) even without tag overlap or execution history.
    """
    # Capability match: fraction of required items present
    required_items: list[tuple[str, set]] = []
    for key in ("triggers", "node_types", "tools"):
        req = set(requirements.get(key) or [])
        if req:
            required_items.append((key, req))

    # model_capability is a single string requirement
    model_cap = requirements.get("model_capability")
    if model_cap:
        required_items.append(("model_capability", {model_cap}))

    if required_items:
        total_required = 0
        total_matched = 0
        for key, req_set in required_items:
            total_required += len(req_set)
            if key == "model_capability":
                # Substring match against model_names
                for req_model in req_set:
                    if any(req_model.lower() in m.lower() for m in capabilities.get("model_names", [])):
                        total_matched += 1
            else:
                has_set = set(capabilities.get(key, []))
                total_matched += len(req_set & has_set)
        capability_match = total_matched / total_required
    else:
        capability_match = 1.0

    # Tag overlap: Jaccard similarity (only when tags are requested)
    req_tags = set(requirements.get("tags") or [])
    if req_tags:
        has_tags = set(capabilities.get("tags") or [])
        union = req_tags | has_tags
        tag_overlap = len(req_tags & has_tags) / len(union) if union else 1.0
    else:
        tag_overlap = 1.0

    # Success rate: default 0.5 if no executions
    sr = success_rate if success_rate is not None else 0.5

    score = capability_match * 0.8 + tag_overlap * 0.1 + sr * 0.1

    # Description substring bonus
    req_desc = (requirements.get("description") or "").strip().lower()
    if req_desc and req_desc in description.lower():
        score = min(score + 0.05, 1.0)

    return score
