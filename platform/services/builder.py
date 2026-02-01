"""WorkflowBuilder — compiles Workflow models into LangGraph CompiledGraph."""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from models.node import WorkflowEdge, WorkflowNode
from services.state import WorkflowState

logger = logging.getLogger(__name__)


class WorkflowBuilder:
    """Builds a LangGraph CompiledGraph from a Workflow model instance."""

    def build(self, workflow, db: Session) -> "CompiledGraph":
        nodes = (
            db.query(WorkflowNode)
            .filter(WorkflowNode.workflow_id == workflow.id)
            .order_by(WorkflowNode.id)
            .all()
        )
        edges = (
            db.query(WorkflowEdge)
            .filter(
                WorkflowEdge.workflow_id == workflow.id,
                WorkflowEdge.edge_label == "",
            )
            .order_by(WorkflowEdge.priority, WorkflowEdge.id)
            .all()
        )

        if not nodes:
            raise ValueError(f"Workflow '{workflow.slug}' has no nodes")

        entry_nodes = [n for n in nodes if n.is_entry_point]
        if not entry_nodes:
            raise ValueError(f"Workflow '{workflow.slug}' has no entry point node")
        entry_node = entry_nodes[0]

        interrupt_before = [n.node_id for n in nodes if n.interrupt_before]
        interrupt_after = [n.node_id for n in nodes if n.interrupt_after]

        graph = StateGraph(WorkflowState)

        # Import component factory
        from components import get_component_factory

        for node in nodes:
            factory = get_component_factory(node.component_type)
            node_fn = factory(node)
            graph.add_node(node.node_id, node_fn)

        graph.set_entry_point(entry_node.node_id)

        edges_by_source: dict[str, list] = {}
        for edge in edges:
            edges_by_source.setdefault(edge.source_node_id, []).append(edge)

        for source_id, source_edges in edges_by_source.items():
            conditional = [e for e in source_edges if e.edge_type == "conditional"]
            direct = [e for e in source_edges if e.edge_type == "direct"]

            if conditional:
                edge = conditional[0]
                mapping = edge.condition_mapping or {}
                path_map = {}
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
        for node in nodes:
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
            workflow.slug, len(nodes), len(edges),
        )
        return compiled


def _make_route_fn(source_node_id: str):
    def route_fn(state: dict) -> str:
        return state.get("route", "")
    return route_fn
