"""Jinja2 expression resolver for node config fields.

Resolves ``{{ nodeId.portName }}`` expressions in system prompts,
extra_config values, and other string config fields.
"""

from __future__ import annotations

import logging

from jinja2 import BaseLoader, Environment, StrictUndefined, UndefinedError

logger = logging.getLogger(__name__)

_env = Environment(
    loader=BaseLoader(),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    autoescape=False,
)


def resolve_expressions(
    template_str: str,
    node_outputs: dict,
    trigger: dict | None = None,
) -> str:
    """Resolve ``{{ nodeId.portName }}`` expressions in a string.

    Context: each node_id is a top-level variable, plus ``trigger``.
    On error (undefined variable, syntax error), returns the original string
    for graceful degradation.
    """
    if not template_str or "{{" not in template_str:
        return template_str

    context = dict(node_outputs)
    if trigger is not None:
        context["trigger"] = trigger

    try:
        tpl = _env.from_string(template_str)
        return tpl.render(context)
    except (UndefinedError, Exception) as exc:
        logger.debug("Expression resolution failed: %s — returning original", exc)
        return template_str


def resolve_config_expressions(
    config: dict,
    node_outputs: dict,
    trigger: dict | None = None,
) -> dict:
    """Recursively resolve expressions in all string values of a config dict."""
    if not config:
        return config

    resolved = {}
    for key, value in config.items():
        if isinstance(value, str):
            resolved[key] = resolve_expressions(value, node_outputs, trigger)
        elif isinstance(value, dict):
            resolved[key] = resolve_config_expressions(value, node_outputs, trigger)
        elif isinstance(value, list):
            resolved[key] = [
                resolve_expressions(item, node_outputs, trigger)
                if isinstance(item, str)
                else resolve_config_expressions(item, node_outputs, trigger)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            resolved[key] = value
    return resolved
