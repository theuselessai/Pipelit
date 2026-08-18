"""Edge validation — type compatibility and required input checks."""

from __future__ import annotations

from sqlalchemy.orm import Session

from schemas.binary_catalogs import catalog_for, operation_output_ports, operations_for
from schemas.binary_verbs import VERBS, verb_operations, verbs_for
from schemas.node_types import DataType, PortDefinition, get_node_type

# Node types whose output ports are derived per node — from the configured
# (binary, operation) — rather than declared once on the type's spec.
BINARY_NODE_TYPES = ("binary_op", "binary_auth")

# Machine-readable code carried by an EdgeIssue when a binary node's ports
# cannot be resolved. The two production callers treat exactly this class
# differently: edge creation filters it out (sketch-first — a freshly added
# binary node has no operation yet), while /validate/ reports it with its
# specific reason. The filtering happens AT THE EDGE-CREATION CALLER, never
# here: if this module stopped emitting the condition, /validate/ would go
# silent too and the condition would be invisible from both paths.
UNRESOLVED_PORTS = "unresolved_ports"


class EdgeIssue(str):
    """A validation error message carrying a machine-readable code.

    A plain `str` subclass so every existing consumer — JSON serialisation,
    substring assertions, the `f"Edge a → b: {err}"` wrapping — keeps working,
    while a caller that needs to distinguish ONE class of error can read
    `.code` instead of parsing prose.
    """

    code: str

    def __new__(cls, message: str, code: str = "invalid") -> "EdgeIssue":
        obj = super().__new__(cls, message)
        obj.code = code
        return obj


def _extra_config(node) -> dict:
    config = getattr(node, "component_config", None)
    if config is None:
        return {}
    return getattr(config, "extra_config", None) or {}


def _default_operation(component_type: str) -> str | None:
    """The schema-declared default operation for a node type, if any."""
    spec = get_node_type(component_type)
    if not spec:
        return None
    return ((spec.config_schema.get("properties") or {}).get("operation") or {}).get("default")


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
    def _output_ports(node) -> tuple[list[PortDefinition] | None, EdgeIssue | None]:
        """Resolve a node's output ports, per node.

        Returns ``(ports, issue)``. ``ports is None`` means they cannot be
        known. For a genuinely unknown component_type that is ``(None, None)``
        — forward compatibility, the caller allows the edge. For a
        `binary_op`/`binary_auth` node it is ``(None, EdgeIssue(...))`` with
        ``code=UNRESOLVED_PORTS``, naming WHICH failure it is: no binary set,
        binary not registered here (no readable catalog), no operation
        selected, or an operation the binary does not offer. Never a silent
        empty list — `resolve_expressions` turns a vanished port into the
        literal ``{{ node.port }}`` downstream, so "cannot know" must stay
        detectable, and this is where it is detected.
        """
        component_type = node.component_type

        if component_type == "binary_op":
            config = _extra_config(node)
            binary = config.get("binary")
            if not binary:
                return None, EdgeIssue(
                    "binary_op node's output ports cannot be resolved: no binary set",
                    code=UNRESOLVED_PORTS,
                )
            operation = config.get("operation") or _default_operation(component_type)
            if not operation:
                return None, EdgeIssue(
                    "binary_op node's output ports cannot be resolved: no operation selected",
                    code=UNRESOLVED_PORTS,
                )
            ports = operation_output_ports(binary, operation)
            if ports is not None:
                return ports, None
            if catalog_for(binary) is None:
                return None, EdgeIssue(
                    "binary_op node's output ports cannot be resolved: "
                    f"binary '{binary}' has no registered catalog here",
                    code=UNRESOLVED_PORTS,
                )
            return None, EdgeIssue(
                "binary_op node's output ports cannot be resolved: "
                f"binary '{binary}' does not offer operation '{operation}'",
                code=UNRESOLVED_PORTS,
            )

        if component_type == "binary_auth":
            config = _extra_config(node)
            operation = config.get("operation") or _default_operation(component_type)
            if not operation:
                return None, EdgeIssue(
                    "binary_auth node's output ports cannot be resolved: no operation selected",
                    code=UNRESOLVED_PORTS,
                )
            verb = VERBS.get(operation)
            if verb is None:
                return None, EdgeIssue(
                    "binary_auth node's output ports cannot be resolved: "
                    f"the protocol does not define verb '{operation}'",
                    code=UNRESOLVED_PORTS,
                )
            return [
                PortDefinition(name=name, data_type=data_type, description=description)
                for name, data_type, description in verb["outputs"]
            ], None

        spec = get_node_type(component_type)
        if spec is None:
            # Unknown type — allow (forward compatibility)
            return None, None
        return spec.outputs, None

    @staticmethod
    def validate_edge(
        source_node,
        target_node,
        source_handle: str | None = None,
        target_handle: str | None = None,
    ) -> list[str]:
        """Validate a single edge between two nodes. Returns error strings (empty = valid).

        Takes node objects — `.component_type` and `.component_config.extra_config`
        are consulted — because a binary node's output ports depend on its
        configured operation, not on its type. Entries may be `EdgeIssue`s;
        the one class with ``code=UNRESOLVED_PORTS`` is what edge creation
        filters out and /validate/ keeps.
        """
        errors: list[str] = []

        # Sub-component edges (llm, tool, output_parser, skills) are always valid
        # if the target requires them
        if target_handle in ("model", "tools", "output_parser", "skills"):
            source_spec = get_node_type(source_node.component_type)
            target_spec = get_node_type(target_node.component_type)
            if not source_spec or not target_spec:
                # Unknown types — allow (forward compatibility)
                return errors
            handle_to_flag = {
                "model": "requires_model",
                "tools": "requires_tools",
                "output_parser": "requires_output_parser",
                "skills": "requires_skills",
            }
            flag = handle_to_flag.get(target_handle, "")
            if flag and not getattr(target_spec, flag, False):
                errors.append(
                    f"Node type '{target_node.component_type}' does not accept "
                    f"'{target_handle}' connections"
                )
            return errors

        source_ports, unresolved = EdgeValidator._output_ports(source_node)
        if unresolved is not None:
            errors.append(unresolved)

        target_spec = get_node_type(target_node.component_type)
        if source_ports is None or target_spec is None:
            # Unknown (non-binary) source or target type: errors is empty —
            # allowed, forward compatibility. A binary source whose ports
            # cannot be resolved: the tagged issue is already in errors.
            return errors

        # For direct/conditional edges, check output→input type compatibility
        if source_ports and target_spec.inputs:
            # Use first output and first input for basic compatibility check
            src_type = source_ports[0].data_type
            tgt_type = target_spec.inputs[0].data_type
            if not EdgeValidator.is_type_compatible(src_type, tgt_type):
                errors.append(
                    f"Type mismatch: {source_node.component_type} outputs '{src_type.value}' "
                    f"but {target_node.component_type} expects '{tgt_type.value}'"
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
            if not src:
                errors.append(f"Edge references unknown source node '{edge.source_node_id}'")
                continue

            # Conditional edges: validate condition_value and target
            if edge.edge_type == "conditional":
                cv = getattr(edge, "condition_value", "") or ""
                if not cv:
                    errors.append(f"Conditional edge from '{edge.source_node_id}' is missing condition_value")
                if not edge.target_node_id:
                    errors.append(f"Conditional edge from '{edge.source_node_id}' is missing target_node_id")
                elif edge.target_node_id != "__end__" and edge.target_node_id not in node_map:
                    errors.append(f"Conditional edge from '{edge.source_node_id}' targets unknown node '{edge.target_node_id}'")
                if src.component_type != "switch":
                    errors.append(f"Conditional edge from '{edge.source_node_id}' ({src.component_type}): only 'switch' nodes can have conditional edges")
                continue

            tgt = node_map.get(edge.target_node_id)
            if not tgt:
                errors.append(f"Edge references unknown target node '{edge.target_node_id}'")
                continue

            # Skip loop flow-control edges (no type compatibility needed)
            if edge.edge_label in ("loop_body", "loop_return"):
                continue

            # Map edge_label to target handle
            label_to_handle = {"llm": "model", "tool": "tools", "output_parser": "output_parser", "skill": "skills"}
            target_handle = label_to_handle.get(edge.edge_label) if edge.edge_label else None

            edge_errors = EdgeValidator.validate_edge(
                src, tgt,
                target_handle=target_handle,
            )
            for err in edge_errors:
                # Keep the machine-readable code through the wrapping.
                errors.append(EdgeIssue(
                    f"Edge {edge.source_node_id} → {edge.target_node_id}: {err}",
                    code=getattr(err, "code", "invalid"),
                ))

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

            errors.extend(_binary_operation_errors(node, spec))

        return errors


def _binary_operation_errors(node, spec) -> list[str]:
    """Design-time checks for any node driven by an operation table.

    The table is resolved PER NODE: a built-in whose spec declares
    `x-operations` (mailbox_action) uses that, unchanged; `binary_op` uses the
    configured binary's catalog (`operations_for`); `binary_auth` uses the
    protocol's verb table composed for its binary (`verbs_for`), since a
    catalog may declare what `auth login` and `env add` carry. A
    binary node whose table cannot be resolved — no binary set, no readable
    catalog registered here — gets an explicit error, never a silent skip.

    Caught here rather than at run time because the answer is knowable when the
    workflow is built: the schema already says which operations need an identity
    and which parameters they require. Finding out instead by running the
    workflow means discovering it against a real backend, which for a mutating
    operation is the expensive place to learn.
    """
    config = (node.component_config.extra_config or {}) if node.component_config else {}
    label = f"Node '{node.node_id}' ({node.component_type})"

    if node.component_type == "binary_op":
        binary = config.get("binary")
        if not binary:
            return [f"{label} has no binary set"]
        operations = operations_for(binary)
        if operations is None:
            return [f"{label} names binary '{binary}', which has no registered catalog here"]
    elif node.component_type == "binary_auth":
        if not config.get("binary"):
            return [f"{label} has no binary set"]
        # Composed for this node's binary, exactly as the component composes it
        # at run time: what `auth login` and `env add` require is partly the
        # binary's to declare, and validating against the static fallback would
        # demand fields a declaring binary never asked for. An unresolvable
        # binary composes nothing and validates against the fallback.
        operations = verb_operations(verbs_for(config["binary"]))
    else:
        operations = spec.config_schema.get("x-operations")
        if not operations:
            return []

    # A schema may declare a default, which the component applies when the key is
    # absent. Ignoring it here would fail every node that has never been opened.
    default = ((spec.config_schema.get("properties") or {}).get("operation") or {}).get("default")
    operation = config.get("operation") or default

    if not operation:
        return [f"{label} has no operation selected"]
    if operation not in operations:
        return [f"{label} names operation '{operation}', which this node type does not offer"]

    errors: list[str] = []
    op = operations[operation]

    if op.get("session_required") and not str(config.get("session") or "").strip():
        errors.append(
            f"{label} runs '{operation}', which requires an identity, but no session is set"
        )

    # A required parameter left empty fails at the binary with BAD_PARAMS. The
    # catalog declares them, so say so now instead.
    required = (op.get("params") or {}).get("required") or []
    missing = [k for k in required if not str(config.get(k) or "").strip()]
    if missing:
        errors.append(f"{label} is missing required parameter(s): {', '.join(sorted(missing))}")

    return errors
