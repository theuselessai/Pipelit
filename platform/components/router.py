"""Router component — rule-based routing on state fields."""

from __future__ import annotations

from components import register


@register("router")
def router_factory(node):
    """Build a router graph node."""
    extra = node.component_config.extra_config
    condition_field = extra.get("condition_field", "route")
    condition_expression = extra.get("condition_expression")

    def router_node(state: dict) -> dict:
        if condition_expression:
            route = _evaluate_expression(condition_expression, state)
        else:
            route = str(state.get(condition_field, ""))

        return {"_route": route, "route": route}

    return router_node


def _evaluate_expression(expression: str, state: dict) -> str:
    """Evaluate a simple condition expression against state.

    Supports:
      - field references: "state.route", "state.node_outputs.categorizer.category"
      - equality checks: "state.route == 'chat'"
    """
    # Simple field access: "state.field.subfield"
    if "==" not in expression:
        return str(_resolve_field(expression.strip(), state))

    # Equality check — returns the matched value or empty string
    left, right = expression.split("==", 1)
    left_val = str(_resolve_field(left.strip(), state))
    right_val = right.strip().strip("'\"")
    return right_val if left_val == right_val else ""


def _resolve_field(path: str, state: dict):
    """Resolve dotted path like 'state.node_outputs.foo' against state dict."""
    parts = path.split(".")
    if parts and parts[0] == "state":
        parts = parts[1:]

    current = state
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return ""
    return current if current is not None else ""
