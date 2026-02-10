"""WorkflowBuilder — compiles Workflow models into LangGraph CompiledGraph."""

from __future__ import annotations

import logging
from collections import deque

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from models.node import WorkflowEdge, WorkflowNode
from services.state import WorkflowState

logger = logging.getLogger(__name__)

SUB_COMPONENT_TYPES = {"ai_model", "run_command", "http_request", "web_search", "calculator", "datetime", "output_parser", "memory_read", "memory_write", "code_execute", "create_agent_user", "platform_api", "whoami", "epic_tools", "task_tools", "spawn_and_await"}


def _reachable_node_ids(
    start_node_id: str,
    all_edges: list[WorkflowEdge],
) -> set[str]:
    """BFS from start_node_id following direct and conditional edges, returning all reachable node_ids."""
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


class WorkflowBuilder:
    """Builds a LangGraph CompiledGraph from a Workflow model instance."""

    def build(self, workflow, db: Session, trigger_node_id: int | None = None) -> "CompiledGraph":
        all_nodes = (
            db.query(WorkflowNode)
            .filter(WorkflowNode.workflow_id == workflow.id)
            .order_by(WorkflowNode.id)
            .all()
        )
        all_edges = (
            db.query(WorkflowEdge)
            .filter(
                WorkflowEdge.workflow_id == workflow.id,
                WorkflowEdge.edge_label == "",
            )
            .order_by(WorkflowEdge.priority, WorkflowEdge.id)
            .all()
        )

        # If a trigger node fired, only include nodes reachable from it
        if trigger_node_id is not None:
            trigger_node = db.get(WorkflowNode, trigger_node_id)
            if trigger_node:
                reachable = _reachable_node_ids(trigger_node.node_id, all_edges)
                all_nodes = [n for n in all_nodes if n.node_id in reachable]
                all_edges = [e for e in all_edges if e.source_node_id in reachable and (e.target_node_id in reachable or e.target_node_id == "__end__")]

        trigger_nodes = {n.node_id for n in all_nodes if n.component_type.startswith("trigger_")}
        skip_nodes = trigger_nodes | {n.node_id for n in all_nodes if n.component_type in SUB_COMPONENT_TYPES}
        exec_nodes = [n for n in all_nodes if n.node_id not in skip_nodes]

        if not exec_nodes:
            raise ValueError(f"Workflow '{workflow.slug}' has no executable nodes")

        # Determine entry point
        entry_nodes = [n for n in exec_nodes if n.is_entry_point]
        if not entry_nodes:
            trigger_targets = [
                e.target_node_id for e in all_edges
                if e.source_node_id in trigger_nodes and e.target_node_id not in skip_nodes
            ]
            if trigger_targets:
                entry_nodes = [n for n in exec_nodes if n.node_id == trigger_targets[0]]
            if not entry_nodes:
                entry_nodes = exec_nodes[:1]
        entry_node = entry_nodes[0]

        interrupt_before = [n.node_id for n in all_nodes if n.interrupt_before]
        interrupt_after = [n.node_id for n in all_nodes if n.interrupt_after]

        graph = StateGraph(WorkflowState)

        from components import get_component_factory

        for node in exec_nodes:
            factory = get_component_factory(node.component_type)
            node_fn = factory(node)
            graph.add_node(node.node_id, node_fn)

        graph.set_entry_point(entry_node.node_id)

        exec_edges = [e for e in all_edges if e.source_node_id not in skip_nodes and e.target_node_id not in skip_nodes]
        edges_by_source: dict[str, list] = {}
        for edge in exec_edges:
            edges_by_source.setdefault(edge.source_node_id, []).append(edge)

        for source_id, source_edges in edges_by_source.items():
            conditional = [e for e in source_edges if e.edge_type == "conditional"]
            direct = [e for e in source_edges if e.edge_type == "direct"]

            if conditional:
                # Build path_map from individual conditional edges with condition_value
                path_map = {}
                for e in conditional:
                    val = getattr(e, "condition_value", "") or ""
                    if val:
                        target = END if e.target_node_id == "__end__" else e.target_node_id
                        path_map[val] = target
                # Fallback: legacy condition_mapping on first edge
                if not path_map:
                    edge = conditional[0]
                    mapping = edge.condition_mapping or {}
                    for route_val, target_id in mapping.items():
                        path_map[route_val] = END if target_id == "__end__" else target_id
                graph.add_conditional_edges(source_id, _make_route_fn(source_id), path_map)
            elif direct:
                target = direct[0].target_node_id
                if target == "__end__" or not target:
                    graph.add_edge(source_id, END)
                else:
                    graph.add_edge(source_id, target)
            else:
                graph.add_edge(source_id, END)

        sources_with_edges = set(edges_by_source.keys())
        for node in exec_nodes:
            if node.node_id not in sources_with_edges:
                graph.add_edge(node.node_id, END)

        checkpointer = MemorySaver()
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_before=interrupt_before or None,
            interrupt_after=interrupt_after or None,
        )

        logger.info(
            "Built graph for workflow '%s': %d nodes, %d edges",
            workflow.slug, len(exec_nodes), len(exec_edges),
        )
        return compiled


def _make_route_fn(source_node_id: str):
    def route_fn(state: dict) -> str:
        return state.get("route", "")
    return route_fn
