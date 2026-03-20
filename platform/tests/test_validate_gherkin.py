"""Tests for the validate_gherkin tool component."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_node():
    """Build a minimal node-like object for the validate_gherkin factory."""
    config = SimpleNamespace(
        component_type="validate_gherkin",
        extra_config={},
        system_prompt="",
    )
    return SimpleNamespace(
        node_id="validate_gherkin_1",
        workflow_id=1,
        component_type="validate_gherkin",
        component_config=config,
    )


def _get_tool():
    """Create a validate_gherkin tool instance."""
    from components.validate_gherkin import validate_gherkin_factory
    node = _make_node()
    return validate_gherkin_factory(node)


VALID_FEATURE = """\
Feature: Login
  Scenario: Successful login
    Given the user is on the login page
    When the user enters valid credentials
    Then the user is redirected to the dashboard
"""

NO_GIVEN_FEATURE = """\
Feature: Missing Given
  Scenario: No given step
    When the user clicks submit
    Then something happens
"""

NO_WHEN_FEATURE = """\
Feature: Missing When
  Scenario: No when step
    Given some precondition
    Then something happens
"""

NO_THEN_FEATURE = """\
Feature: Missing Then
  Scenario: No then step
    Given some precondition
    When something happens
"""

EMPTY_SCENARIO = """\
Feature: Empty
  Scenario: Nothing here
"""

UNNAMED_SCENARIO = """\
Feature: Test
  Scenario:
    Given something
    When action
    Then result
"""

DUPLICATE_NAMES = """\
Feature: Dups
  Scenario: Do something
    Given x
    When y
    Then z
  Scenario: Do something
    Given a
    When b
    Then c
"""

UNNAMED_FEATURE = """\
Feature:
  Scenario: Test
    Given x
    When y
    Then z
"""

NO_SCENARIOS = """\
Feature: Empty feature
"""

BACKGROUND_WITH_WHEN = """\
Feature: Bad background
  Background:
    Given some setup
    When bad step in background
  Scenario: Test
    Given x
    When y
    Then z
"""


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestValidateGherkinRegistration:
    def test_registered_in_component_registry(self):
        from components import COMPONENT_REGISTRY
        assert "validate_gherkin" in COMPONENT_REGISTRY

    def test_factory_returns_tool(self):
        tool = _get_tool()
        assert hasattr(tool, "invoke")
        assert tool.name == "validate_gherkin"


class TestValidateGherkinValidSpec:
    def test_valid_gherkin_returns_valid(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is True
        assert result["parse_errors"] == []
        assert result["lint_errors"] == []
        assert result["lint_warnings"] == []


class TestValidateGherkinSyntaxError:
    def test_non_gherkin_text_returns_parse_error(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": "This is not Gherkin at all."})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0

    def test_python_code_returns_parse_error(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": "def hello():\n    print('hello')\n"})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0


class TestValidateGherkinEmptyInput:
    def test_empty_string_returns_error(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": ""})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0
        assert "empty" in result["parse_errors"][0]["message"].lower()

    def test_whitespace_only_returns_error(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": "   \n\t\n  "})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0


class TestValidateGherkinLintChecks:
    def test_missing_given(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": NO_GIVEN_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is True  # lint warnings don't fail validation
        codes = [w["code"] for w in result["lint_warnings"]]
        assert "C001" in codes

    def test_missing_when(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": NO_WHEN_FEATURE})
        result = json.loads(raw)

        codes = [w["code"] for w in result["lint_warnings"]]
        assert "C002" in codes

    def test_missing_then(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": NO_THEN_FEATURE})
        result = json.loads(raw)

        codes = [w["code"] for w in result["lint_warnings"]]
        assert "C003" in codes

    def test_empty_scenario(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": EMPTY_SCENARIO})
        result = json.loads(raw)

        codes = [w["code"] for w in result["lint_warnings"]]
        assert "W005" in codes

    def test_unnamed_scenario(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": UNNAMED_SCENARIO})
        result = json.loads(raw)

        codes = [w["code"] for w in result["lint_warnings"]]
        assert "W004" in codes

    def test_duplicate_scenario_names(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": DUPLICATE_NAMES})
        result = json.loads(raw)

        codes = [w["code"] for w in result["lint_warnings"]]
        assert "W003" in codes

    def test_unnamed_feature(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": UNNAMED_FEATURE})
        result = json.loads(raw)

        codes = [w["code"] for w in result["lint_warnings"]]
        assert "W001" in codes

    def test_no_scenarios(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": NO_SCENARIOS})
        result = json.loads(raw)

        codes = [w["code"] for w in result["lint_warnings"]]
        assert "W002" in codes

    def test_background_with_non_given_step(self):
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": BACKGROUND_WITH_WHEN})
        result = json.loads(raw)

        codes = [w["code"] for w in result["lint_warnings"]]
        assert "C004" in codes

    def test_valid_spec_no_warnings(self):
        """A well-formed spec should produce zero warnings."""
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["lint_warnings"] == []
        assert result["lint_errors"] == []


class TestLintAstDirect:
    """Test _lint_ast directly for edge cases."""

    def test_no_feature_key(self):
        from components.validate_gherkin import _lint_ast
        result = {"valid": True, "parse_errors": [], "lint_warnings": [], "lint_errors": []}
        _lint_ast({}, result)
        assert result["valid"] is False
        assert result["lint_errors"][0]["code"] == "E001"

    def test_feature_with_no_children(self):
        from components.validate_gherkin import _lint_ast
        result = {"valid": True, "parse_errors": [], "lint_warnings": [], "lint_errors": []}
        _lint_ast({"feature": {"name": "Test", "children": []}}, result)
        codes = [w["code"] for w in result["lint_warnings"]]
        assert "W002" in codes
