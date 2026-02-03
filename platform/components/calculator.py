"""Calculator tool component — safe math evaluation."""

from __future__ import annotations

import ast
import operator

from langchain_core.tools import tool

from components import register

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression: {type(node).__name__}")


@register("calculator")
def calculator_factory(node):
    """Return a LangChain tool that evaluates math expressions."""

    @tool
    def calculator(expression: str) -> str:
        """Evaluate a math expression. Supports +, -, *, /, //, %, **."""
        try:
            tree = ast.parse(expression.strip(), mode="eval")
            result = _safe_eval(tree)
            return str(result)
        except Exception as e:
            return f"Error: {e}"

    return calculator
