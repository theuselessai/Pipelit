"""Edge validation — type compatibility and required input checks."""

from __future__ import annotations

from sqlalchemy.orm import Session

from schemas.node_types import DataType, get_node_type


# Types that are universally compatible as source or target
_COMPATIBLE_PAIRS: set[tuple[DataType, DataType]] = {
    (DataType.STRING, DataType.ANY),
    (DataType.NUMBER, DataType.ANY),
    (DataType.BOOLEAN, DataType.ANY),
    (DataType.OBJECT, DataType.ANY),
    (DataType.ARRAY, DataType.ANY),
    (DataType.MESSAGE, DataType.ANY),
    (DataType.MESSAGES, DataType.ANY),
    (DataType.IMAGE, DataType.ANY),
    (DataType.FILE, DataType.ANY),
    (DataType.ANY, DataType.ANY),
    # Message coercions
    (DataType.MESSAGE, DataType.MESSAGES),
    (DataType.STRING, DataType.MESSAGE),
    (DataType.STRING, DataType.MESSAGES),
}


class EdgeValidator:
    @staticmethod
    def is_type_compatible(source_type: DataType, target_type: DataType) -> bool:
        if source_type == target_type:
            return True
        if target_type == DataType.ANY or source_type == DataType.ANY:
            return True
        return (source_type, target_type) in _COMPATIBLE_PAIRS

    @staticmethod
    def validate_edge(
        source_node_type: str,
        target_node_type: str,
        source_handle: str | None = None,
        target_handle: str | None = None,
    ) -> list[str]:
        """Validate a single edge. Returns list of error strings (empty = valid)."""
        errors: list[str] = []

        source_spec = get_node_type(source_node_type)
        target_spec = get_node_type(target_node_type)

        if not source_spec or not target_spec:
            # Unknown types — allow (forward compatibility)
            return errors

        # Sub-component edges (llm, tool, memory, output_parser) are always valid
        # if the target requires them
        if target_handle in ("model", "tools", "memory", "output_parser"):
            handle_to_flag = {
                "model": "requires_model",
                "tools": "requires_tools",
                "memory": "requires_memory",
                "output_parser": "requires_output_parser",
            }
            flag = handle_to_flag.get(target_handle, "")
            if flag and not getattr(target_spec, flag, False):
                errors.append(
                    f"Node type '{target_node_type}' does not accept '{target_handle}' connections"
                )
            return errors

        # For direct/conditional edges, check output→input type compatibility
        if source_spec.outputs and target_spec.inputs:
            # Use first output and first input for basic compatibility check
            src_type = source_spec.outputs[0].data_type
            tgt_type = target_spec.inputs[0].data_type
            if not EdgeValidator.is_type_compatible(src_type, tgt_type):
                errors.append(
                    f"Type mismatch: {source_node_type} outputs '{src_type.value}' "
                    f"but {target_node_type} expects '{tgt_type.value}'"
                )

        return errors

    @staticmethod
    def validate_workflow_edges(workflow_id: int, db: Session) -> list[str]:
        """Validate all edges in a workflow. Returns list of error strings."""
        from models.node import WorkflowEdge, WorkflowNode

        errors: list[str] = []
        nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()
        edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).all()

        node_map = {n.node_id: n for n in nodes}

        for edge in edges:
            src = node_map.get(edge.source_node_id)
            tgt = node_map.get(edge.target_node_id)
            if not src:
                errors.append(f"Edge references unknown source node '{edge.source_node_id}'")
                continue
            if not tgt:
                errors.append(f"Edge references unknown target node '{edge.target_node_id}'")
                continue

            # Map edge_label to target handle
            label_to_handle = {"llm": "model", "tool": "tools", "memory": "memory", "output_parser": "output_parser"}
            target_handle = label_to_handle.get(edge.edge_label) if edge.edge_label else None

            edge_errors = EdgeValidator.validate_edge(
                src.component_type, tgt.component_type,
                target_handle=target_handle,
            )
            for err in edge_errors:
                errors.append(f"Edge {edge.source_node_id} → {edge.target_node_id}: {err}")

        return errors

    @staticmethod
    def validate_required_inputs(workflow_id: int, db: Session) -> list[str]:
        """Check that nodes with required inputs have incoming edges."""
        from models.node import WorkflowEdge, WorkflowNode

        errors: list[str] = []
        nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()
        edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).all()

        # Build set of nodes that have incoming direct edges
        nodes_with_input = {e.target_node_id for e in edges if not e.edge_label}
        # Build set of nodes with sub-component connections
        nodes_with_model = {e.target_node_id for e in edges if e.edge_label == "llm"}

        for node in nodes:
            spec = get_node_type(node.component_type)
            if not spec:
                continue

            # Skip triggers — they don't need incoming edges
            if node.component_type.startswith("trigger_"):
                continue

            # Check if node needs a model connection
            if spec.requires_model and node.node_id not in nodes_with_model:
                errors.append(f"Node '{node.node_id}' ({node.component_type}) requires a model connection")

        return errors
