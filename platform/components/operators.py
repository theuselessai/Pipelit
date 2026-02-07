"""Shared operator definitions for switch, filter, and other rule-based components."""

from __future__ import annotations

import re
from datetime import datetime


def _to_num(v):
    """Safely coerce to float."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_dt(v):
    """Safely coerce to datetime (ISO 8601)."""
    if isinstance(v, datetime):
        return v
    if not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _to_bool(v):
    """Coerce to boolean."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return bool(v)


OPERATORS: dict[str, callable] = {
    # Universal
    "exists": lambda fv, _rv: fv is not None,
    "does_not_exist": lambda fv, _rv: fv is None,
    "is_empty": lambda fv, _rv: fv is None or fv == "" or fv == [] or fv == {},
    "is_not_empty": lambda fv, _rv: fv is not None and fv != "" and fv != [] and fv != {},

    # String / equality
    "equals": lambda fv, rv: str(fv) == str(rv),
    "not_equals": lambda fv, rv: str(fv) != str(rv),
    "contains": lambda fv, rv: (
        rv in fv if isinstance(fv, list)
        else str(rv) in str(fv)
    ),
    "not_contains": lambda fv, rv: (
        rv not in fv if isinstance(fv, list)
        else str(rv) not in str(fv)
    ),
    "starts_with": lambda fv, rv: str(fv).startswith(str(rv)),
    "not_starts_with": lambda fv, rv: not str(fv).startswith(str(rv)),
    "ends_with": lambda fv, rv: str(fv).endswith(str(rv)),
    "not_ends_with": lambda fv, rv: not str(fv).endswith(str(rv)),
    "matches_regex": lambda fv, rv: bool(re.search(str(rv), str(fv))),
    "not_matches_regex": lambda fv, rv: not bool(re.search(str(rv), str(fv))),

    # Number
    "gt": lambda fv, rv: (_to_num(fv) or 0) > (_to_num(rv) or 0),
    "lt": lambda fv, rv: (_to_num(fv) or 0) < (_to_num(rv) or 0),
    "gte": lambda fv, rv: (_to_num(fv) or 0) >= (_to_num(rv) or 0),
    "lte": lambda fv, rv: (_to_num(fv) or 0) <= (_to_num(rv) or 0),

    # Datetime
    "after": lambda fv, rv: ((_to_dt(fv) or datetime.min) > (_to_dt(rv) or datetime.max)),
    "before": lambda fv, rv: ((_to_dt(fv) or datetime.max) < (_to_dt(rv) or datetime.min)),
    "after_or_equal": lambda fv, rv: ((_to_dt(fv) or datetime.min) >= (_to_dt(rv) or datetime.max)),
    "before_or_equal": lambda fv, rv: ((_to_dt(fv) or datetime.max) <= (_to_dt(rv) or datetime.min)),

    # Boolean
    "is_true": lambda fv, _rv: _to_bool(fv) is True,
    "is_false": lambda fv, _rv: _to_bool(fv) is False,

    # Array length
    "length_eq": lambda fv, rv: len(fv) == int(rv) if isinstance(fv, (list, str)) else False,
    "length_neq": lambda fv, rv: len(fv) != int(rv) if isinstance(fv, (list, str)) else True,
    "length_gt": lambda fv, rv: len(fv) > int(rv) if isinstance(fv, (list, str)) else False,
    "length_lt": lambda fv, rv: len(fv) < int(rv) if isinstance(fv, (list, str)) else False,
    "length_gte": lambda fv, rv: len(fv) >= int(rv) if isinstance(fv, (list, str)) else False,
    "length_lte": lambda fv, rv: len(fv) <= int(rv) if isinstance(fv, (list, str)) else False,
}

UNARY_OPERATORS = {"exists", "does_not_exist", "is_empty", "is_not_empty", "is_true", "is_false"}


def _resolve_field(path: str, state: dict):
    """Resolve dotted path like 'state.node_outputs.foo' or 'node_outputs.foo' against state dict."""
    parts = path.split(".")
    if parts and parts[0] == "state":
        parts = parts[1:]

    current = state
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
