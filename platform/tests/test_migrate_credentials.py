"""Tests for the deprecated migrate-credentials CLI command.

Phase 1(b) hard cutover: pipelit no longer stores LLM API keys (the
encrypted ``llm_credentials.api_key`` column was dropped), so the one-shot
DB→agentgateway migration is end-of-life. The command is kept only as a
stub that fails loudly with guidance — every invocation (including the old
``--rollback`` / ``--dry-run`` / ``--force`` / ``--populate-routes`` flags)
exits non-zero without touching the DB or the agentgateway directory.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest


def _run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run CLI main() with the given args, capturing stdout/stderr and exit code."""
    from cli.__main__ import main

    captured_out = []
    captured_err = []
    exit_code = 0

    def mock_stdout_write(s):
        captured_out.append(s)
        return len(s)

    def mock_stderr_write(s):
        captured_err.append(s)
        return len(s)

    with patch.object(sys, "argv", ["cli"] + args), \
         patch.object(sys.stdout, "write", mock_stdout_write), \
         patch.object(sys.stderr, "write", mock_stderr_write):
        try:
            main()
        except SystemExit as e:
            try:
                exit_code = int(e.code) if e.code is not None else 0
            except (TypeError, ValueError):
                exit_code = 1

    return exit_code, "".join(captured_out), "".join(captured_err)


@pytest.fixture
def agw_dir(tmp_path):
    """A pristine agentgateway directory tree — must never be touched."""
    (tmp_path / "config.d" / "backends").mkdir(parents=True)
    (tmp_path / "keys").mkdir()
    return tmp_path


def _tree_snapshot(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class TestMigrateCredentialsDeprecated:
    def test_plain_invocation_fails_with_deprecation(self):
        code, out, err = _run_cli(["migrate-credentials"])

        assert code != 0
        data = json.loads(out)
        assert data["error"] == "deprecated"
        assert "agentgateway" in data["message"]
        assert "deprecated" in err.lower()

    @pytest.mark.parametrize(
        "flags",
        [
            ["--rollback"],
            ["--dry-run"],
            ["--force"],
            ["--populate-routes"],
            ["--rollback", "--dry-run"],
        ],
    )
    def test_legacy_flags_still_parse_but_fail_deprecated(self, flags):
        """Old invocations get the deprecation message, not an argparse error."""
        code, out, err = _run_cli(["migrate-credentials"] + flags)

        assert code != 0
        data = json.loads(out)
        assert data["error"] == "deprecated"

    def test_no_filesystem_writes(self, agw_dir):
        """The stub must not touch the agentgateway directory."""
        before = _tree_snapshot(agw_dir)

        with patch("config.settings") as mock_settings:
            mock_settings.AGENTGATEWAY_DIR = str(agw_dir)
            code, out, err = _run_cli(["migrate-credentials"])

        assert code != 0
        assert _tree_snapshot(agw_dir) == before

    def test_exit_code_is_2(self):
        """Distinct exit code so scripts can tell deprecation from crash."""
        code, _, _ = _run_cli(["migrate-credentials"])
        assert code == 2

    def test_migration_machinery_removed(self):
        """The old migration internals are gone from the CLI module."""
        import cli.__main__ as cli_main

        for removed in (
            "_rollback_migration",
            "_resolve_provider_name",
            "_model_to_slug",
            "_parse_base_url",
            "_set_env_var",
        ):
            assert not hasattr(cli_main, removed), removed
