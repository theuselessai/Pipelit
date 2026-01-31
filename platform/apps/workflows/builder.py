"""WorkflowBuilder — compiles Django Workflow models into LangGraph CompiledGraph."""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from apps.workflows.components import get_component_factory
from apps.workflows.state import WorkflowState

logger = logging.getLogger(__name__)


class WorkflowBuilder:
    """Builds a LangGraph CompiledGraph from a Workflow model instance."""

    def build(self, workflow) -> "CompiledGraph":
        """Compile a Workflow into a LangGraph graph.

        Args:
            workflow: Workflow model instance (with prefetched nodes/edges).

        Returns:
            CompiledGraph ready for .invoke() or .stream().
        """
        nodes = list(
            workflow.nodes.select_related("component_config")
            .all()
            .order_by("id")
        )
        # Only use control-flow edges (empty label) for graph structure.
        # Labeled edges (llm, tool, etc.) are data references, not control flow.
        edges = list(
            workflow.edges.filter(edge_label="")
            .order_by("priority", "id")
        )

        if not nodes:
            raise ValueError(f"Workflow '{workflow.slug}' has no nodes")

        # Find entry point
        entry_nodes = [n for n in nodes if n.is_entry_point]
        if not entry_nodes:
            raise ValueError(f"Workflow '{workflow.slug}' has no entry point node")
        entry_node = entry_nodes[0]

        # Build node map
        node_map = {n.node_id: n for n in nodes}

        # Collect interrupt nodes
        interrupt_before = [n.node_id for n in nodes if n.interrupt_before]
        interrupt_after = [n.node_id for n in nodes if n.interrupt_after]

        # Create state graph
        graph = StateGraph(WorkflowState)

        # Add nodes
        for node in nodes:
            factory = get_component_factory(node.component_type)
            node_fn = factory(node)
            graph.add_node(node.node_id, node_fn)

        # Set entry point
        graph.set_entry_point(entry_node.node_id)

        # Group edges by source
        edges_by_source: dict[str, list] = {}
        for edge in edges:
            edges_by_source.setdefault(edge.source_node_id, []).append(edge)

        # Add edges
        for source_id, source_edges in edges_by_source.items():
            conditional = [e for e in source_edges if e.edge_type == "conditional"]
            direct = [e for e in source_edges if e.edge_type == "direct"]

            if conditional:
                # Build conditional routing
                edge = conditional[0]  # One conditional edge per source
                mapping = edge.condition_mapping or {}

                # Build path map: route_value -> node_id
                path_map = {}
                for route_val, target_id in mapping.items():
                    if target_id == "__end__":
                        path_map[route_val] = END
                    else:
                        path_map[route_val] = target_id

                graph.add_conditional_edges(
                    source_id,
                    _make_route_fn(source_id),
                    path_map,
                )
            elif direct:
                # Single direct edge
                target = direct[0].target_node_id
                if target == "__end__" or not target:
                    graph.add_edge(source_id, END)
                else:
                    graph.add_edge(source_id, target)
            else:
                # No outgoing edges — goes to END
                graph.add_edge(source_id, END)

        # Nodes without outgoing edges go to END
        sources_with_edges = set(edges_by_source.keys())
        for node in nodes:
            if node.node_id not in sources_with_edges:
                graph.add_edge(node.node_id, END)

        # Compile
        checkpointer = MemorySaver()
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_before=interrupt_before or None,
            interrupt_after=interrupt_after or None,
        )

        logger.info(
            "Built graph for workflow '%s': %d nodes, %d edges",
            workflow.slug,
            len(nodes),
            len(edges),
        )
        return compiled


def _make_route_fn(source_node_id: str):
    """Create a routing function that reads the 'route' field from state."""

    def route_fn(state: dict) -> str:
        return state.get("route", "")

    return route_fn
