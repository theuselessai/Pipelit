"""Tests for the CLI setup and apply-fixture commands."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from conftest import TestSession


def _run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run CLI main() with the given args, capturing stdout/stderr and exit code."""
    from cli.__main__ import main

    captured_out = []
    captured_err = []
    exit_code = 0

    real_stdout_write = sys.stdout.write
    real_stderr_write = sys.stderr.write

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
            exit_code = int(e.code) if e.code is not None else 0

    return exit_code, "".join(captured_out), "".join(captured_err)


@pytest.fixture
def cli_db():
    """Patch SessionLocal so CLI commands use the test database."""
    session = TestSession()
    try:
        with patch("database.SessionLocal", return_value=session):
            yield session
    finally:
        session.close()


class TestCLISetup:
    def test_setup_creates_admin_user(self, cli_db, tmp_path):
        mock_env = {"sandbox_mode": "container", "rootfs_ready": False}
        with patch("services.environment.build_environment_report", return_value=mock_env), \
             patch("config.save_conf"), \
             patch("config.get_pipelit_dir", return_value=tmp_path / "pipelit"):
            code, out, err = _run_cli(["setup", "--username", "admin", "--password", "secret"])

        assert code == 0
        data = json.loads(out)
        assert data["username"] == "admin"
        assert data["setup_completed"] is True

        from models.user import UserProfile, UserRole
        user = cli_db.query(UserProfile).first()
        assert user is not None
        assert user.username == "admin"
        assert user.role == UserRole.ADMIN

    def test_setup_idempotent(self, cli_db, tmp_path):
        import bcrypt
        from models.user import APIKey, UserProfile, UserRole

        existing = UserProfile(
            username="existing-admin",
            password_hash=bcrypt.hashpw(b"pass", bcrypt.gensalt()).decode(),
            role=UserRole.ADMIN,
        )
        cli_db.add(existing)
        cli_db.flush()
        cli_db.add(APIKey(user_id=existing.id, key="existing-key"))
        cli_db.commit()

        code, out, err = _run_cli(["setup", "--username", "another", "--password", "pass"])

        assert code == 0
        data = json.loads(out)
        assert data["username"] == "existing-admin"
        assert data["setup_completed"] is True
        assert cli_db.query(UserProfile).count() == 1

    def test_setup_creates_workspace_dir(self, cli_db, tmp_path):
        mock_env = {"sandbox_mode": "container", "rootfs_ready": False}
        pipelit_dir = tmp_path / "pipelit"
        with patch("services.environment.build_environment_report", return_value=mock_env), \
             patch("config.save_conf"), \
             patch("config.get_pipelit_dir", return_value=pipelit_dir):
            code, out, err = _run_cli(["setup", "--username", "admin", "--password", "secret"])

        assert code == 0
        assert (pipelit_dir / "workspaces" / "default").is_dir()
        assert (pipelit_dir / "workspaces" / "default" / ".tmp").is_dir()

    def test_setup_writes_conf(self, cli_db, tmp_path):
        mock_env = {"sandbox_mode": "bwrap", "rootfs_ready": True}
        mock_save = MagicMock()
        with patch("services.environment.build_environment_report", return_value=mock_env), \
             patch("config.save_conf", mock_save), \
             patch("config.get_pipelit_dir", return_value=tmp_path / "pipelit"):
            code, out, err = _run_cli([
                "setup", "--username", "admin", "--password", "secret",
                "--sandbox-mode", "bwrap",
            ])

        assert code == 0
        mock_save.assert_called_once()
        conf = mock_save.call_args[0][0]
        assert conf.setup_completed is True
        assert conf.sandbox_mode == "bwrap"

    def test_setup_triggers_rootfs_when_bwrap(self, cli_db, tmp_path):
        mock_env = {"sandbox_mode": "bwrap", "rootfs_ready": False}
        mock_prepare = MagicMock()
        with patch("services.environment.build_environment_report", return_value=mock_env), \
             patch("config.save_conf"), \
             patch("config.get_pipelit_dir", return_value=tmp_path / "pipelit"), \
             patch("services.rootfs.prepare_golden_image", mock_prepare):
            code, out, err = _run_cli(["setup", "--username", "admin", "--password", "secret"])

        assert code == 0
        mock_prepare.assert_called_once_with(tier=2)


class TestCLIApplyFixture:
    def test_unknown_fixture_fails(self, cli_db):
        code, out, err = _run_cli([
            "apply-fixture", "nonexistent",
            "--provider", "openai", "--model", "gpt-4o", "--api-key", "sk-test",
        ])
        assert code == 1
        data = json.loads(err)
        assert "Unknown fixture" in data["error"]

    def test_apply_fixture_requires_user(self, cli_db):
        code, out, err = _run_cli([
            "apply-fixture", "default-agent",
            "--provider", "openai", "--model", "gpt-4o", "--api-key", "sk-test",
        ])
        assert code == 1
        data = json.loads(err)
        assert "No user found" in data["error"]

    def test_apply_fixture_creates_workflow(self, cli_db, user_profile):
        code, out, err = _run_cli([
            "apply-fixture", "default-agent",
            "--provider", "openai", "--model", "gpt-4o", "--api-key", "sk-test",
        ])

        assert code == 0
        data = json.loads(out)
        assert data["workflow_slug"] == "default-agent"
        assert data["trigger_node_id"] == "trigger_chat_1"

        from models.workflow import Workflow
        wf = cli_db.query(Workflow).filter(Workflow.slug == "default-agent").first()
        assert wf is not None
        assert wf.name == "Default Agent"

        from models.node import WorkflowNode, WorkflowEdge
        nodes = cli_db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf.id).all()
        assert len(nodes) == 6
        node_ids = {n.node_id for n in nodes}
        assert node_ids == {
            "trigger_chat_1", "ai_model_1", "deep_agent_1",
            "memory_read_1", "memory_write_1", "skill_1",
        }

        edges = cli_db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf.id).all()
        assert len(edges) == 5

    def test_apply_fixture_creates_credential(self, cli_db, user_profile):
        _run_cli([
            "apply-fixture", "default-agent",
            "--provider", "venice", "--model", "deepseek-r1-671b", "--api-key", "sk-test",
        ])

        from models.credential import BaseCredential, LLMProviderCredential
        cred = cli_db.query(BaseCredential).first()
        assert cred is not None
        assert cred.name == "venice (default)"
        assert cred.credential_type == "llm"

        llm_cred = cli_db.query(LLMProviderCredential).first()
        assert llm_cred is not None
        assert llm_cred.provider_type == "venice"

    def test_apply_fixture_idempotent(self, cli_db, user_profile):
        _run_cli([
            "apply-fixture", "default-agent",
            "--provider", "openai", "--model", "gpt-4o", "--api-key", "sk-test",
        ])

        code, out, err = _run_cli([
            "apply-fixture", "default-agent",
            "--provider", "openai", "--model", "gpt-4o", "--api-key", "sk-other",
        ])

        assert code == 0
        data = json.loads(out)
        assert data["workflow_slug"] == "default-agent"
        assert data["trigger_node_id"] == "trigger_chat_1"

        from models.workflow import Workflow
        assert cli_db.query(Workflow).count() == 1

    def test_apply_fixture_edge_labels(self, cli_db, user_profile):
        _run_cli([
            "apply-fixture", "default-agent",
            "--provider", "openai", "--model", "gpt-4o", "--api-key", "sk-test",
        ])

        from models.node import WorkflowEdge
        from models.workflow import Workflow
        wf = cli_db.query(Workflow).filter(Workflow.slug == "default-agent").first()
        edges = cli_db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf.id).all()
        edge_map = {(e.source_node_id, e.target_node_id): e.edge_label for e in edges}

        assert edge_map[("trigger_chat_1", "deep_agent_1")] == ""
        assert edge_map[("ai_model_1", "deep_agent_1")] == "llm"
        assert edge_map[("memory_read_1", "deep_agent_1")] == "tool"
        assert edge_map[("memory_write_1", "deep_agent_1")] == "tool"
        assert edge_map[("skill_1", "deep_agent_1")] == "skill"

    def test_apply_fixture_deep_agent_config(self, cli_db, user_profile):
        _run_cli([
            "apply-fixture", "default-agent",
            "--provider", "openai", "--model", "gpt-4o", "--api-key", "sk-test",
        ])

        from models.node import BaseComponentConfig, WorkflowNode
        from models.workflow import Workflow
        wf = cli_db.query(Workflow).filter(Workflow.slug == "default-agent").first()
        agent_node = (
            cli_db.query(WorkflowNode)
            .filter(WorkflowNode.workflow_id == wf.id, WorkflowNode.node_id == "deep_agent_1")
            .first()
        )
        cfg = cli_db.query(BaseComponentConfig).get(agent_node.component_config_id)
        assert cfg.extra_config.get("conversation_memory") is True
