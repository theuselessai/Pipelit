"""Validate Gherkin tool component — syntax parsing and structural lint checks.

Tier 1: Syntax validation via gherkin-official parser.
Tier 2: Structural lint checks via pure Python against the parsed AST.
No external lint tools or subprocess calls required.
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register

logger = logging.getLogger(__name__)


@register("validate_gherkin")
def validate_gherkin_factory(node):
    """Return a LangChain tool that validates Gherkin .feature specs."""

    @tool
    def validate_gherkin(gherkin_spec: str) -> str:
        """Validate a Gherkin feature spec for syntax errors and lint warnings.

        Args:
            gherkin_spec: The Gherkin feature specification text to validate.

        Returns:
            JSON string with validation results including parse_errors,
            lint_warnings, and lint_errors.
        """
        result = {
            "valid": True,
            "parse_errors": [],
            "lint_warnings": [],
            "lint_errors": [],
        }

        if not gherkin_spec or not gherkin_spec.strip():
            result["valid"] = False
            result["parse_errors"].append({
                "message": "Empty Gherkin spec provided",
                "line": 0,
            })
            return json.dumps(result)

        # ── Tier 1: Syntax check via gherkin-official parser ─────────────
        try:
            from gherkin.parser import Parser

            parser = Parser()
            doc = parser.parse(gherkin_spec)
        except Exception as e:
            result["valid"] = False
            error_info = {"message": str(e), "line": 0}
            err_str = str(e)
            if "(" in err_str and ":" in err_str:
                try:
                    parts = err_str.split("(")
                    for part in parts:
                        if ":" in part and ")" in part:
                            line_part = part.split(":")[0].strip()
                            if line_part.isdigit():
                                error_info["line"] = int(line_part)
                                break
                except (ValueError, IndexError):
                    pass
            result["parse_errors"].append(error_info)
            return json.dumps(result)

        # ── Tier 2: Structural lint checks against parsed AST ────────────
        _lint_ast(doc, result)

        return json.dumps(result)

    return validate_gherkin


def _lint_ast(doc: dict, result: dict) -> None:
    """Run structural lint checks against a parsed Gherkin AST."""
    feature = doc.get("feature")

    if not feature:
        result["lint_errors"].append({
            "code": "E001",
            "message": "No Feature block found",
            "line": 0,
        })
        result["valid"] = False
        return

    # Check feature has a name
    if not feature.get("name", "").strip():
        result["lint_warnings"].append({
            "code": "W001",
            "message": "Feature has no name",
            "line": feature.get("location", {}).get("line", 0),
        })

    children = feature.get("children", [])
    scenarios = [c for c in children if "scenario" in c]
    backgrounds = [c for c in children if "background" in c]

    # Check feature has scenarios
    if not scenarios:
        result["lint_warnings"].append({
            "code": "W002",
            "message": "Feature has no scenarios",
            "line": feature.get("location", {}).get("line", 0),
        })
        return

    # Check for duplicate scenario names
    seen_names: dict[str, int] = {}
    for child in scenarios:
        sc = child["scenario"]
        name = sc.get("name", "").strip()
        line = sc.get("location", {}).get("line", 0)
        if name:
            if name in seen_names:
                result["lint_warnings"].append({
                    "code": "W003",
                    "message": f"Duplicate scenario name: '{name}' (first at line {seen_names[name]})",
                    "line": line,
                })
            else:
                seen_names[name] = line

    # Check each scenario
    for child in scenarios:
        sc = child["scenario"]
        name = sc.get("name", "").strip()
        line = sc.get("location", {}).get("line", 0)
        steps = sc.get("steps", [])

        # Unnamed scenario
        if not name:
            result["lint_warnings"].append({
                "code": "W004",
                "message": "Scenario has no name",
                "line": line,
            })

        # Empty scenario
        if not steps:
            result["lint_warnings"].append({
                "code": "W005",
                "message": f"Scenario '{name or '(unnamed)'}' has no steps",
                "line": line,
            })
            continue

        # Extract keyword types (Given, When, Then, And, But, *)
        keywords = [s.get("keyword", "").strip() for s in steps]

        # Check for missing Given
        if "Given" not in keywords:
            result["lint_warnings"].append({
                "code": "C001",
                "message": f"Scenario '{name or '(unnamed)'}' has no Given step",
                "line": line,
            })

        # Check for missing When
        if "When" not in keywords:
            result["lint_warnings"].append({
                "code": "C002",
                "message": f"Scenario '{name or '(unnamed)'}' has no When step",
                "line": line,
            })

        # Check for missing Then
        if "Then" not in keywords:
            result["lint_warnings"].append({
                "code": "C003",
                "message": f"Scenario '{name or '(unnamed)'}' has no Then step",
                "line": line,
            })

    # Check backgrounds
    for child in backgrounds:
        bg = child["background"]
        bg_steps = bg.get("steps", [])
        bg_line = bg.get("location", {}).get("line", 0)

        if not bg_steps:
            result["lint_warnings"].append({
                "code": "W006",
                "message": "Background has no steps",
                "line": bg_line,
            })

        # Background should only contain Given steps
        for step in bg_steps:
            kw = step.get("keyword", "").strip()
            if kw not in ("Given", "And", "But", "*"):
                result["lint_warnings"].append({
                    "code": "C004",
                    "message": f"Background contains non-Given step: '{kw}'",
                    "line": step.get("location", {}).get("line", 0),
                })
