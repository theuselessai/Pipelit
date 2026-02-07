"""Switch component — routes to different branches based on configurable rules."""

from __future__ import annotations

from components import register
from components.operators import OPERATORS, UNARY_OPERATORS, _resolve_field


@register("switch")
def switch_factory(node):
    """Build a switch graph node."""
    extra = node.component_config.extra_config

    # New rule-based mode
    rules = extra.get("rules")
    if rules:
        enable_fallback = extra.get("enable_fallback", False)

        def switch_node(state: dict) -> dict:
            route = ""
            for rule in rules:
                field_path = rule.get("field", "")
                operator = rule.get("operator", "equals")
                value = rule.get("value", "")
                rule_id = rule.get("id", "")

                field_val = _resolve_field(field_path, state)
                op_fn = OPERATORS.get(operator)
                if op_fn and op_fn(field_val, value):
                    route = rule_id
                    break

            if not route and enable_fallback:
                route = "__other__"

            return {"_route": route, "route": route}

        return switch_node

    # Legacy mode: condition_field / condition_expression
    condition_field = extra.get("condition_field", "route")
    condition_expression = extra.get("condition_expression")

    def switch_node_legacy(state: dict) -> dict:
        if condition_expression:
            route = _evaluate_expression(condition_expression, state)
        else:
            route = str(state.get(condition_field, ""))

        return {"_route": route, "route": route}

    return switch_node_legacy


def _evaluate_expression(expression: str, state: dict) -> str:
    """Evaluate a simple condition expression against state.

    Supports:
      - field references: "state.route", "state.node_outputs.categorizer.category"
      - equality checks: "state.route == 'chat'"
    """
    if "==" not in expression:
        return str(_resolve_field(expression.strip(), state))

    left, right = expression.split("==", 1)
    left_val = str(_resolve_field(left.strip(), state))
    right_val = right.strip().strip("'\"")
    return right_val if left_val == right_val else ""
