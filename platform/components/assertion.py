"""Assertion component — evaluates all rules and routes pass/fail."""

from __future__ import annotations

from components import register
from components.operators import evaluate_rules


@register("assertion")
def assertion_factory(node):
    """Build an assertion graph node that checks all rules against state."""
    extra = node.component_config.extra_config
    rules = extra.get("rules", [])

    def assertion_node(state: dict) -> dict:
        if not rules:
            return {
                "_route": "pass",
                "output": {"passed": True, "results": []},
            }

        results = evaluate_rules(rules, state, mode="all")

        results_list = []
        for rule, result in zip(rules, results):
            results_list.append({
                "check": f"{rule.get('field', '')} {rule.get('operator', 'equals')} {rule.get('value', '')}",
                "passed": result["passed"],
                "actual": result["actual_value"],
                "expected": rule.get("value", ""),
            })

        all_passed = all(r["passed"] for r in results)

        return {
            "_route": "pass" if all_passed else "fail",
            "output": {
                "passed": all_passed,
                "results": results_list,
            },
        }

    return assertion_node
