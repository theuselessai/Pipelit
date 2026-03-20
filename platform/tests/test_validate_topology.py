"""Tests for the validate_topology tool component."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_node():
    """Build a minimal node-like object for the validate_topology factory."""
    config = SimpleNamespace(
        component_type="validate_topology",
        extra_config={},
        system_prompt="",
    )
    return SimpleNamespace(
        node_id="validate_topology_1",
        workflow_id=1,
        component_type="validate_topology",
        component_config=config,
    )


def _get_tool():
    """Create a validate_topology tool instance."""
    from components.validate_topology import validate_topology_factory
    return validate_topology_factory(_make_node())


VALID_YAML = """\
name: Test Workflow
trigger: chat
steps:
  - id: reply
    type: reply_chat
    prompt: "Hello"
"""

INVALID_YAML = """\
name: Bad Workflow
trigger: chat
steps:
  - id: broken_step
    type: nonexistent_type_xyz
"""

MALFORMED_YAML = """\
name: [unclosed bracket
  - invalid: yaml: here:
"""


# ── Registration ──────────────────────────────────────────────────────────────

class TestValidateTopologyRegistration:
    def test_registered_in_component_registry(self):
        from components import COMPONENT_REGISTRY
        assert "validate_topology" in COMPONENT_REGISTRY

    def test_factory_returns_tool(self):
        tool = _get_tool()
        assert hasattr(tool, "invoke")
        assert tool.name == "validate_topology"

    def test_registered_in_node_type_registry(self):
        import schemas.node_type_defs  # noqa: F401 — triggers register_node_type calls
        from schemas.node_types import NODE_TYPE_REGISTRY
        assert "validate_topology" in NODE_TYPE_REGISTRY

    def test_node_type_spec(self):
        import schemas.node_type_defs  # noqa: F401
        from schemas.node_types import NODE_TYPE_REGISTRY
        spec = NODE_TYPE_REGISTRY["validate_topology"]
        assert spec.category == "sub_component"
        assert spec.display_name == "Validate Topology"


# ── Happy path ────────────────────────────────────────────────────────────────

class TestValidateTopologyValid:
    def test_valid_yaml_returns_valid_true(self):
        """A DSL that compiles cleanly should return valid: true."""
        dsl_result = {"valid": True, "errors": [], "node_count": 2, "edge_count": 1}
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", return_value=dsl_result) as mock_validate:
            tool = _get_tool()
            raw = tool.invoke({"topology_yaml": VALID_YAML})

        result = json.loads(raw)
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["warnings"] == []
        assert result["node_count"] == 2
        assert result["edge_count"] == 1

    def test_valid_yaml_passes_yaml_to_validate_dsl(self):
        """The raw YAML string should be passed to validate_dsl."""
        dsl_result = {"valid": True, "errors": [], "node_count": 1, "edge_count": 0}
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", return_value=dsl_result) as mock_validate:
            tool = _get_tool()
            tool.invoke({"topology_yaml": VALID_YAML})

        mock_validate.assert_called_once_with(VALID_YAML, mock_db)


# ── Error cases ───────────────────────────────────────────────────────────────

class TestValidateTopologyErrors:
    def test_invalid_dsl_returns_valid_false(self):
        """A DSL with errors should return valid: false with errors list."""
        dsl_result = {"valid": False, "errors": ["Graph build error: unknown step type"], "node_count": 0, "edge_count": 0}
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", return_value=dsl_result):
            tool = _get_tool()
            raw = tool.invoke({"topology_yaml": INVALID_YAML})

        result = json.loads(raw)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_parse_error_returns_valid_false(self):
        """A YAML parse error should return valid: false."""
        dsl_result = {"valid": False, "errors": ["Parse error: mapping values are not allowed"], "node_count": 0, "edge_count": 0}
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", return_value=dsl_result):
            tool = _get_tool()
            raw = tool.invoke({"topology_yaml": MALFORMED_YAML})

        result = json.loads(raw)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_exception_from_validate_dsl_is_caught(self):
        """Unexpected exceptions from validate_dsl should be caught gracefully."""
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", side_effect=RuntimeError("DB offline")):
            tool = _get_tool()
            raw = tool.invoke({"topology_yaml": VALID_YAML})

        result = json.loads(raw)
        assert result["valid"] is False
        assert any("DB offline" in e for e in result["errors"])

    def test_db_session_is_closed_on_success(self):
        """SessionLocal() should always be closed after the call."""
        dsl_result = {"valid": True, "errors": [], "node_count": 1, "edge_count": 0}
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", return_value=dsl_result):
            tool = _get_tool()
            tool.invoke({"topology_yaml": VALID_YAML})

        mock_db.close.assert_called_once()

    def test_db_session_is_closed_on_error(self):
        """SessionLocal() should be closed even when validate_dsl raises."""
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", side_effect=Exception("oops")):
            tool = _get_tool()
            tool.invoke({"topology_yaml": VALID_YAML})

        mock_db.close.assert_called_once()


# ── Empty input ───────────────────────────────────────────────────────────────

class TestValidateTopologyEmptyInput:
    def test_empty_string_returns_error(self):
        tool = _get_tool()
        raw = tool.invoke({"topology_yaml": ""})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert "empty" in result["errors"][0].lower()

    def test_whitespace_only_returns_error(self):
        tool = _get_tool()
        raw = tool.invoke({"topology_yaml": "   \n\t\n  "})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_empty_input_does_not_call_db(self):
        """Empty input should short-circuit before touching the database."""
        with patch("components.validate_topology.SessionLocal") as mock_session:
            tool = _get_tool()
            tool.invoke({"topology_yaml": ""})

        mock_session.assert_not_called()


# ── Output shape ──────────────────────────────────────────────────────────────

class TestValidateTopologyOutputShape:
    def test_result_always_has_required_keys(self):
        """Result must always contain valid, errors, warnings, node_count, edge_count."""
        dsl_result = {"valid": True, "errors": [], "node_count": 3, "edge_count": 2}
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", return_value=dsl_result):
            tool = _get_tool()
            raw = tool.invoke({"topology_yaml": VALID_YAML})

        result = json.loads(raw)
        assert "valid" in result
        assert "errors" in result
        assert "warnings" in result
        assert "node_count" in result
        assert "edge_count" in result

    def test_warnings_always_list(self):
        """warnings should always be a list (even when validate_dsl doesn't return it)."""
        dsl_result = {"valid": True, "errors": [], "node_count": 1, "edge_count": 0}
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", return_value=dsl_result):
            tool = _get_tool()
            raw = tool.invoke({"topology_yaml": VALID_YAML})

        result = json.loads(raw)
        assert isinstance(result["warnings"], list)

    def test_returns_json_string(self):
        """Tool must return a valid JSON string."""
        dsl_result = {"valid": True, "errors": [], "node_count": 0, "edge_count": 0}
        mock_db = MagicMock()

        with patch("components.validate_topology.SessionLocal", return_value=mock_db), \
             patch("components.validate_topology.validate_dsl", return_value=dsl_result):
            tool = _get_tool()
            raw = tool.invoke({"topology_yaml": VALID_YAML})

        assert isinstance(raw, str)
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
