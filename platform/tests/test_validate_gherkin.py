"""Tests for the validate_gherkin tool component."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

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

MALFORMED_FEATURE = """\
This is not valid Gherkin at all
  No Feature keyword here
  Just random indented text
"""

NO_GIVEN_FEATURE = """\
Feature: Missing Given
  Scenario: No given step
    When the user clicks submit
    Then something happens
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
    @patch("subprocess.run")
    def test_valid_gherkin_returns_valid(self, mock_run):
        """Valid Gherkin spec should return valid: true with no errors."""
        mock_run.return_value = MagicMock(
            stdout="", stderr="", returncode=0,
        )
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is True
        assert result["parse_errors"] == []
        assert result["lint_errors"] == []

    @patch("subprocess.run")
    def test_valid_gherkin_no_lint_errors(self, mock_run):
        """When gherlint reports no issues, lint_errors should be empty."""
        mock_run.return_value = MagicMock(
            stdout="", stderr="", returncode=0,
        )
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["lint_errors"] == []


class TestValidateGherkinSyntaxError:
    def test_malformed_gherkin_returns_parse_error(self):
        """Malformed Gherkin (bad keyword) should produce a parse error."""
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": MALFORMED_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0
        assert result["parse_errors"][0]["message"]


class TestValidateGherkinLintWarnings:
    @patch("subprocess.run")
    def test_lint_warnings_populated(self, mock_run):
        """Lint warnings should be captured from gherlint output."""
        mock_run.return_value = MagicMock(
            stdout="test.feature:3:1: C0101 Step should start with a capital letter\n",
            stderr="",
            returncode=0,
        )
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is True
        assert len(result["lint_warnings"]) == 1
        assert result["lint_warnings"][0]["code"] == "C0101"
        assert result["lint_warnings"][0]["line"] == 3

    @patch("subprocess.run")
    def test_lint_errors_set_valid_false(self, mock_run):
        """Lint errors (E-codes) should set valid to false."""
        mock_run.return_value = MagicMock(
            stdout="test.feature:5:1: E0001 Critical error found\n",
            stderr="",
            returncode=1,
        )
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["lint_errors"]) == 1
        assert result["lint_errors"][0]["code"] == "E0001"

    @patch("subprocess.run")
    def test_multiple_warnings_and_errors(self, mock_run):
        """Multiple lint issues should all be captured."""
        mock_run.return_value = MagicMock(
            stdout=(
                "test.feature:3:1: C0101 Step lowercase\n"
                "test.feature:5:1: W0301 Missing Given\n"
                "test.feature:8:1: E0001 Critical problem\n"
            ),
            stderr="",
            returncode=1,
        )
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["lint_warnings"]) == 2  # C0101 + W0301
        assert len(result["lint_errors"]) == 1    # E0001


class TestValidateGherkinEmptyInput:
    def test_empty_string_returns_error(self):
        """Empty string should return valid: false with an error."""
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": ""})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0
        assert "empty" in result["parse_errors"][0]["message"].lower()

    def test_whitespace_only_returns_error(self):
        """Whitespace-only input should be treated as empty."""
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": "   \n\t\n  "})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0


class TestValidateGherkinNonGherkin:
    def test_random_text_returns_parse_error(self):
        """Non-Gherkin text should produce a parse error."""
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": "This is just random text, not Gherkin at all."})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0

    def test_python_code_returns_parse_error(self):
        """Python code input should produce a parse error."""
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": "def hello():\n    print('hello')\n"})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0


class TestValidateGherkinGherlintUnavailable:
    @patch("subprocess.run", side_effect=FileNotFoundError("gherlint not found"))
    def test_missing_gherlint_still_validates_syntax(self, mock_run):
        """When gherlint is not installed, syntax validation still works."""
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is True
        assert result["parse_errors"] == []
        # Lint results empty since gherlint unavailable
        assert result["lint_warnings"] == []
        assert result["lint_errors"] == []

    @patch("subprocess.run", side_effect=FileNotFoundError("gherlint not found"))
    def test_missing_gherlint_syntax_error_still_caught(self, mock_run):
        """Syntax errors are caught even without gherlint."""
        tool = _get_tool()
        raw = tool.invoke({"gherkin_spec": MALFORMED_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["parse_errors"]) > 0


class TestParseLintLine:
    def test_standard_format(self):
        from components.validate_gherkin import _parse_lint_line
        entry = _parse_lint_line("test.feature:10:1: C0101 Step should start with a capital letter")
        assert entry is not None
        assert entry["code"] == "C0101"
        assert entry["line"] == 10
        assert "capital" in entry["message"].lower()

    def test_no_column_format(self):
        from components.validate_gherkin import _parse_lint_line
        entry = _parse_lint_line("test.feature:5: W0301 Scenario has no Given step")
        assert entry is not None
        assert entry["code"] == "W0301"
        assert entry["line"] == 5

    def test_bare_code_format(self):
        from components.validate_gherkin import _parse_lint_line
        entry = _parse_lint_line("C0101: Step should start with a capital letter")
        assert entry is not None
        assert entry["code"] == "C0101"

    def test_non_lint_line_returns_none(self):
        from components.validate_gherkin import _parse_lint_line
        assert _parse_lint_line("") is None
        assert _parse_lint_line("some random output") is None
