"""Tests for the validate_gherkin tool component."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)


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


def _exec_resp(output="", exit_code=0):
    """Build a fake backend.execute() response."""
    resp = MagicMock()
    resp.output = output
    resp.exit_code = exit_code
    return resp


def _get_tool(lint_resp=None):
    """Create a validate_gherkin tool instance.

    When *lint_resp* is None, no sandbox backend is injected (lint skipped).
    When *lint_resp* is provided, a mock backend returning that response is used.
    """
    from components.validate_gherkin import validate_gherkin_factory
    node = _make_node()

    if lint_resp is None:
        # No workspace → no backend → lint tier skipped
        with patch("components.run_command._resolve_parent_workspace", return_value={}):
            return validate_gherkin_factory(node)

    mock_backend = MagicMock()
    mock_backend.execute.return_value = lint_resp
    with (
        patch("components.run_command._resolve_parent_workspace", return_value={"workspace_id": "test-ws"}),
        patch("components._agent_shared._build_backend", return_value=mock_backend),
    ):
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
    def test_valid_gherkin_returns_valid(self):
        """Valid Gherkin spec should return valid: true with no errors."""
        tool = _get_tool(lint_resp=_exec_resp(output="", exit_code=0))
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is True
        assert result["parse_errors"] == []
        assert result["lint_errors"] == []

    def test_valid_gherkin_no_lint_errors(self):
        """When gherlint reports no issues, lint_errors should be empty."""
        tool = _get_tool(lint_resp=_exec_resp(output="", exit_code=0))
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
    def test_lint_warnings_populated(self):
        """Lint warnings should be captured from gherlint output."""
        resp = _exec_resp(
            output="test.feature:3:1: C0101 Step should start with a capital letter\n",
            exit_code=0,
        )
        tool = _get_tool(lint_resp=resp)
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is True
        assert len(result["lint_warnings"]) == 1
        assert result["lint_warnings"][0]["code"] == "C0101"
        assert result["lint_warnings"][0]["line"] == 3

    def test_lint_errors_set_valid_false(self):
        """Lint errors (E-codes) should set valid to false."""
        resp = _exec_resp(
            output="test.feature:5:1: E0001 Critical error found\n",
            exit_code=1,
        )
        tool = _get_tool(lint_resp=resp)
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is False
        assert len(result["lint_errors"]) == 1
        assert result["lint_errors"][0]["code"] == "E0001"

    def test_multiple_warnings_and_errors(self):
        """Multiple lint issues should all be captured."""
        resp = _exec_resp(
            output=(
                "test.feature:3:1: C0101 Step lowercase\n"
                "test.feature:5:1: W0301 Missing Given\n"
                "test.feature:8:1: E0001 Critical problem\n"
            ),
            exit_code=1,
        )
        tool = _get_tool(lint_resp=resp)
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


class TestValidateGherkinNoBackend:
    def test_no_backend_still_validates_syntax(self):
        """When no sandbox backend is available, syntax validation still works."""
        tool = _get_tool()  # no lint_resp → no backend
        raw = tool.invoke({"gherkin_spec": VALID_FEATURE})
        result = json.loads(raw)

        assert result["valid"] is True
        assert result["parse_errors"] == []
        # Lint results empty since no backend available
        assert result["lint_warnings"] == []
        assert result["lint_errors"] == []

    def test_no_backend_syntax_error_still_caught(self):
        """Syntax errors are caught even without a backend."""
        tool = _get_tool()  # no lint_resp → no backend
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
