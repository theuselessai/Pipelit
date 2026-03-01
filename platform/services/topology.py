"""Topology — extract node/edge info from DB for the orchestrator."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SUB_COMPONENT_TYPES = {"ai_model", "run_command", "output_parser", "memory_read", "memory_write", "code_execute", "create_agent_user", "platform_api", "whoami", "epic_tools", "task_tools", "spawn_and_await", "workflow_create", "workflow_discover", "scheduler_tools", "system_health", "skill"}


@dataclass
class NodeInfo:
    node_id: str
    component_type: str
    db_id: int
    component_config_id: int
    is_entry_point: bool = False
    interrupt_before: bool = False
    interrupt_after: bool = False


@dataclass
class EdgeInfo:
    source_node_id: str
    target_node_id: str
    edge_type: str = "direct"
    edge_label: str = ""
    condition_mapping: dict | None = None
    condition_value: str = ""
    priority: int = 0


@dataclass
class Topology:
    workflow_slug: str = ""
    nodes: dict[str, NodeInfo] = field(default_factory=dict)
    edges: list[EdgeInfo] = field(default_factory=list)
    entry_node_ids: list[str] = field(default_factory=list)
    edges_by_source: dict[str, list[EdgeInfo]] = field(default_factory=dict)
    incoming_count: dict[str, int] = field(default_factory=dict)
    loop_bodies: dict[str, list[str]] = field(default_factory=dict)
    loop_return_nodes: dict[str, list[str]] = field(default_factory=dict)   # loop_id -> [return source node_ids]
    loop_body_all_nodes: dict[str, list[str]] = field(default_factory=dict) # loop_id -> [all node_ids in body subgraph]


def build_topology(workflow, db: Session, trigger_node_id: int | None = None) -> Topology:
    """Build a Topology from workflow DB models. No LangGraph objects involved."""
    from models.node import WorkflowEdge, WorkflowNode

    all_nodes = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == workflow.id)
        .order_by(WorkflowNode.id)
        .all()
    )
    # Include both direct ("") and loop_body edges
    all_edges = (
        db.query(WorkflowEdge)
        .filter(
            WorkflowEdge.workflow_id == workflow.id,
            WorkflowEdge.edge_label.in_(["", "loop_body", "loop_return"]),
        )
        .order_by(WorkflowEdge.priority, WorkflowEdge.id)
        .all()
    )

    # Scope to reachable nodes from trigger
    if trigger_node_id is not None:
        trigger_node = db.get(WorkflowNode, trigger_node_id)
        if trigger_node:
            reachable = _reachable_node_ids(trigger_node.node_id, all_edges)
            all_nodes = [n for n in all_nodes if n.node_id in reachable]
            all_edges = [e for e in all_edges if e.source_node_id in reachable and e.target_node_id in reachable]

    trigger_nodes = {n.node_id for n in all_nodes if n.component_type.startswith("trigger_")}
    skip_nodes = trigger_nodes | {n.node_id for n in all_nodes if n.component_type in SUB_COMPONENT_TYPES}
    exec_nodes = [n for n in all_nodes if n.node_id not in skip_nodes]

    if not exec_nodes:
        raise ValueError(f"Workflow '{workflow.slug}' has no executable nodes")

    # Build node info dict
    nodes: dict[str, NodeInfo] = {}
    for n in exec_nodes:
        nodes[n.node_id] = NodeInfo(
            node_id=n.node_id,
            component_type=n.component_type,
            db_id=n.id,
            component_config_id=n.component_config_id,
            is_entry_point=n.is_entry_point,
            interrupt_before=n.interrupt_before,
            interrupt_after=n.interrupt_after,
        )

    # Filter edges to only executable nodes
    exec_edges = [
        e for e in all_edges
        if e.source_node_id not in skip_nodes and e.target_node_id not in skip_nodes
    ]

    edges: list[EdgeInfo] = []
    edges_by_source: dict[str, list[EdgeInfo]] = {}
    incoming_count: dict[str, int] = {nid: 0 for nid in nodes}

    for e in exec_edges:
        ei = EdgeInfo(
            source_node_id=e.source_node_id,
            target_node_id=e.target_node_id,
            edge_type=e.edge_type,
            edge_label=getattr(e, "edge_label", "") or "",
            condition_mapping=e.condition_mapping,
            condition_value=getattr(e, "condition_value", "") or "",
            priority=e.priority,
        )
        edges.append(ei)
        edges_by_source.setdefault(e.source_node_id, []).append(ei)
        if e.target_node_id in incoming_count and ei.edge_label != "loop_return":
            incoming_count[e.target_node_id] += 1

    # Determine entry nodes — ALL trigger targets are entries (supports fan-out from trigger)
    entry_nodes = [n for n in exec_nodes if n.is_entry_point]
    if not entry_nodes:
        trigger_target_ids = set()
        for e in all_edges:
            if e.source_node_id in trigger_nodes and e.target_node_id not in skip_nodes:
                trigger_target_ids.add(e.target_node_id)
        if trigger_target_ids:
            entry_nodes = [n for n in exec_nodes if n.node_id in trigger_target_ids]
        if not entry_nodes:
            entry_nodes = exec_nodes[:1]

    # Build loop_bodies mapping: loop_node_id -> list of body target node_ids
    loop_bodies: dict[str, list[str]] = {}
    for nid, ninfo in nodes.items():
        if ninfo.component_type == "loop":
            body_targets = [
                e.target_node_id for e in edges_by_source.get(nid, [])
                if e.edge_label == "loop_body"
            ]
            if body_targets:
                loop_bodies[nid] = body_targets

    # Build loop_return_nodes: loop_id -> [source node_ids of loop_return edges]
    loop_return_nodes: dict[str, list[str]] = {}
    for nid, ninfo in nodes.items():
        if ninfo.component_type == "loop":
            return_sources = [
                e.source_node_id for e in edges
                if e.target_node_id == nid and e.edge_label == "loop_return"
            ]
            if return_sources:
                loop_return_nodes[nid] = return_sources

    # Build loop_body_all_nodes: BFS from body_targets through direct edges
    loop_body_all_nodes: dict[str, list[str]] = {}
    for loop_id in loop_bodies:
        body_targets = loop_bodies[loop_id]
        all_body = set(body_targets)
        bfs_queue = deque(body_targets)
        while bfs_queue:
            cur = bfs_queue.popleft()
            for e in edges_by_source.get(cur, []):
                if e.edge_label in ("",) and e.target_node_id != loop_id and e.target_node_id not in all_body:
                    all_body.add(e.target_node_id)
                    bfs_queue.append(e.target_node_id)
        loop_body_all_nodes[loop_id] = list(all_body)

    topo = Topology(
        workflow_slug=workflow.slug,
        nodes=nodes,
        edges=edges,
        entry_node_ids=[n.node_id for n in entry_nodes],
        edges_by_source=edges_by_source,
        incoming_count=incoming_count,
        loop_bodies=loop_bodies,
        loop_return_nodes=loop_return_nodes,
        loop_body_all_nodes=loop_body_all_nodes,
    )

    logger.info(
        "Built topology for workflow '%s': %d nodes, %d edges, entries=%s, loops=%s",
        workflow.slug, len(nodes), len(edges), topo.entry_node_ids, list(loop_bodies.keys()),
    )
    return topo


def _reachable_node_ids(start_node_id: str, all_edges) -> set[str]:
    """BFS from start_node_id following direct, conditional, and loop_body edges."""
    adjacency: dict[str, list[str]] = {}
    for e in all_edges:
        if e.target_node_id:
            adjacency.setdefault(e.source_node_id, []).append(e.target_node_id)
        # Also follow conditional edge targets from condition_mapping
        if e.edge_type == "conditional" and e.condition_mapping:
            for target_id in e.condition_mapping.values():
                if target_id and target_id != "__end__":
                    adjacency.setdefault(e.source_node_id, []).append(target_id)

    visited: set[str] = set()
    queue = deque([start_node_id])
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        for neighbor in adjacency.get(nid, []):
            if neighbor not in visited:
                queue.append(neighbor)
    return visited
