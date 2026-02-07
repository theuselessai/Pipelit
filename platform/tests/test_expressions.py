"""Tests for the Jinja2 expression resolver."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure platform/ is importable
_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from services.expressions import resolve_config_expressions, resolve_expressions


def test_simple_variable():
    result = resolve_expressions(
        "Hello {{ agent_1.output }}",
        {"agent_1": {"output": "world"}},
    )
    assert result == "Hello world"


def test_nested_access():
    result = resolve_expressions(
        "Category: {{ cat_1.category }}",
        {"cat_1": {"category": "FOOD", "raw": '{"category":"FOOD"}'}},
    )
    assert result == "Category: FOOD"


def test_no_expressions():
    result = resolve_expressions("plain text", {})
    assert result == "plain text"


def test_undefined_variable_returns_original():
    template = "Hello {{ nonexistent.value }}"
    result = resolve_expressions(template, {})
    assert result == template


def test_trigger_access():
    result = resolve_expressions(
        "User said: {{ trigger.text }}",
        {},
        trigger={"text": "hello there"},
    )
    assert result == "User said: hello there"


def test_recursive_config():
    config = {
        "greeting": "Hello {{ agent_1.output }}",
        "nested": {
            "value": "Category is {{ cat_1.category }}",
            "number": 42,
        },
        "items": ["{{ trigger.text }}", "static"],
        "bool_val": True,
    }
    result = resolve_config_expressions(
        config,
        {"agent_1": {"output": "world"}, "cat_1": {"category": "FOOD"}},
        trigger={"text": "hi"},
    )
    assert result["greeting"] == "Hello world"
    assert result["nested"]["value"] == "Category is FOOD"
    assert result["nested"]["number"] == 42
    assert result["items"] == ["hi", "static"]
    assert result["bool_val"] is True


def test_jinja_filters():
    result = resolve_expressions(
        "{{ cat_1.category | upper }}",
        {"cat_1": {"category": "food"}},
    )
    assert result == "FOOD"


def test_empty_template():
    assert resolve_expressions("", {}) == ""
    assert resolve_expressions(None, {}) is None


def test_no_braces_passthrough():
    result = resolve_expressions("just plain text no braces", {"a": {"b": "c"}})
    assert result == "just plain text no braces"


def test_empty_config():
    assert resolve_config_expressions({}, {}) == {}
    assert resolve_config_expressions(None, {}) is None


def test_ternary_expression():
    result = resolve_expressions(
        "{{ 'yes' if agent_1.output else 'no' }}",
        {"agent_1": {"output": "hello"}},
    )
    assert result == "yes"

    result2 = resolve_expressions(
        "{{ 'yes' if agent_1.output else 'no' }}",
        {"agent_1": {"output": ""}},
    )
    assert result2 == "no"
