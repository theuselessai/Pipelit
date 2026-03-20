"""Validate Gherkin tool component — syntax parsing and lint checks."""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

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
            parser.parse(gherkin_spec)
        except Exception as e:
            result["valid"] = False
            error_info = {"message": str(e), "line": 0}
            # Try to extract line number from the error message
            err_str = str(e)
            if "(" in err_str and ":" in err_str:
                try:
                    # gherkin-official errors often contain "(line:col)" patterns
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

        # ── Tier 2: Lint via gherlint CLI ────────────────────────────────
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".feature",
                delete=False,
            ) as tmp:
                tmp.write(gherkin_spec)
                tmp_path = tmp.name

            try:
                proc = subprocess.run(
                    ["gherlint", "lint", tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                _parse_gherlint_output(
                    proc.stdout, proc.stderr, proc.returncode, result
                )
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except FileNotFoundError:
            logger.debug("gherlint not found on PATH, skipping lint checks")
        except subprocess.TimeoutExpired:
            logger.warning("gherlint timed out after 30s")
        except Exception:
            logger.debug("gherlint lint failed", exc_info=True)

        return json.dumps(result)

    return validate_gherkin


def _parse_gherlint_output(
    stdout: str, stderr: str, returncode: int, result: dict
) -> None:
    """Parse gherlint CLI output and populate result dict."""
    output = (stdout + "\n" + stderr).strip()
    if not output:
        return

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # gherlint output format is typically:
        # filename:line:col: CODE message
        # or just warning/error messages
        entry = _parse_lint_line(line)
        if entry is None:
            continue

        code = entry.get("code", "")
        # Convention: Cxxx = convention, Wxxx = warning, Exxx = error
        if code.startswith("E"):
            result["lint_errors"].append(entry)
            result["valid"] = False
        else:
            # W, C, and other codes are treated as warnings
            result["lint_warnings"].append(entry)


def _parse_lint_line(line: str) -> dict | None:
    """Parse a single gherlint output line into a structured dict.

    Expected formats:
        filename.feature:10:1: C0101 Step should start with a capital letter
        filename.feature:5: W0301 Scenario has no Given step
        C0101: Step should start with a capital letter (line 10)
    """
    # Format: path:line:col: CODE message
    parts = line.split(":", maxsplit=3)
    if len(parts) >= 4:
        try:
            line_no = int(parts[1].strip())
            remainder = parts[3].strip() if len(parts) > 3 else parts[2].strip()
            code, _, message = remainder.partition(" ")
            if code and code[0].isalpha() and any(c.isdigit() for c in code):
                return {"code": code, "message": message.strip(), "line": line_no}
        except (ValueError, IndexError):
            pass

    # Format: path:line: CODE message (no column)
    if len(parts) >= 3:
        try:
            line_no = int(parts[1].strip())
            remainder = parts[2].strip()
            code, _, message = remainder.partition(" ")
            if code and code[0].isalpha() and any(c.isdigit() for c in code):
                return {"code": code, "message": message.strip(), "line": line_no}
        except (ValueError, IndexError):
            pass

    # Format: CODE: message (line N) or CODE message
    if line and line[0].isalpha():
        code_part = line.split()[0].rstrip(":")
        if any(c.isdigit() for c in code_part):
            message = line[len(code_part):].strip().lstrip(": ")
            line_no = 0
            # Try to extract (line N) from message
            if "(line" in message:
                try:
                    idx = message.index("(line")
                    num = message[idx + 5:].split(")")[0].strip()
                    line_no = int(num)
                    message = message[:idx].strip()
                except (ValueError, IndexError):
                    pass
            return {"code": code_part, "message": message, "line": line_no}

    return None
