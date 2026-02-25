"""Tests for skill node type — registration, edge validation, skill resolution."""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from database import get_db
from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode, COMPONENT_TYPE_TO_CONFIG

# Force node_type_defs to load so NODE_TYPE_REGISTRY is populated
import schemas.node_type_defs  # noqa: F401


# ── Local fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def app(db):
    from main import app as _app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_client(client, api_key):
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


# ── Registration tests ────────────────────────────────────────────────────────


def test_skill_in_node_type_registry():
    """skill is registered in NODE_TYPE_REGISTRY."""
    from schemas.node_types import NODE_TYPE_REGISTRY
    assert "skill" in NODE_TYPE_REGISTRY


def test_skill_not_executable():
    """skill nodes should not be executable (they are config-only sub-components)."""
    from schemas.node_types import NODE_TYPE_REGISTRY
    assert NODE_TYPE_REGISTRY["skill"].executable is False


def test_skill_in_topology_sub_component_types():
    """skill is in topology SUB_COMPONENT_TYPES so it is skipped during graph building."""
    from services.topology import SUB_COMPONENT_TYPES
    assert "skill" in SUB_COMPONENT_TYPES


def test_skill_in_builder_sub_component_types():
    """skill is in builder SUB_COMPONENT_TYPES so it is skipped during graph compilation."""
    from services.builder import SUB_COMPONENT_TYPES
    assert "skill" in SUB_COMPONENT_TYPES


def test_skill_in_component_type_to_config():
    """skill is mapped in COMPONENT_TYPE_TO_CONFIG for node creation."""
    assert "skill" in COMPONENT_TYPE_TO_CONFIG


def test_skill_polymorphic_identity(db):
    """skill polymorphic identity resolves correctly via SQLAlchemy STI."""
    cfg = BaseComponentConfig(component_type="skill", extra_config={"skill_path": "/tmp/skills"})
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    assert cfg.component_type == "skill"
    assert cfg.extra_config == {"skill_path": "/tmp/skills"}


def test_agent_requires_skills():
    """agent and deep_agent should have requires_skills=True."""
    from schemas.node_types import NODE_TYPE_REGISTRY
    assert NODE_TYPE_REGISTRY["agent"].requires_skills is True
    assert NODE_TYPE_REGISTRY["deep_agent"].requires_skills is True


def test_non_ai_nodes_do_not_require_skills():
    """Nodes other than agent/deep_agent should not require skills."""
    from schemas.node_types import NODE_TYPE_REGISTRY
    for ct, spec in NODE_TYPE_REGISTRY.items():
        if ct not in ("agent", "deep_agent"):
            assert spec.requires_skills is False, f"{ct} should not require skills"


# ── Edge validation tests ─────────────────────────────────────────────────────


def test_skill_edge_to_agent_valid():
    """A skill→agent edge with 'skills' handle should validate successfully."""
    from validation.edges import EdgeValidator
    errors = EdgeValidator.validate_edge("skill", "agent", target_handle="skills")
    assert errors == []


def test_skill_edge_to_deep_agent_valid():
    """A skill→deep_agent edge with 'skills' handle should validate successfully."""
    from validation.edges import EdgeValidator
    errors = EdgeValidator.validate_edge("skill", "deep_agent", target_handle="skills")
    assert errors == []


def test_skill_edge_to_non_agent_invalid():
    """A skill→switch edge with 'skills' handle should fail (switch doesn't require skills)."""
    from validation.edges import EdgeValidator
    errors = EdgeValidator.validate_edge("skill", "switch", target_handle="skills")
    assert len(errors) == 1
    assert "does not accept" in errors[0]


def test_skill_edge_to_categorizer_invalid():
    """categorizer doesn't accept skills connections."""
    from validation.edges import EdgeValidator
    errors = EdgeValidator.validate_edge("skill", "categorizer", target_handle="skills")
    assert len(errors) == 1
    assert "does not accept" in errors[0]


# ── API edge creation tests ──────────────────────────────────────────────────


def test_create_skill_edge_via_api(auth_client, workflow, db):
    """Creating a skill edge between skill→agent via API should succeed."""
    # Create skill node
    resp = auth_client.post(
        f"/api/v1/workflows/{workflow.slug}/nodes/",
        json={"component_type": "skill", "position_x": 100, "position_y": 100},
    )
    assert resp.status_code == 201
    skill_node_id = resp.json()["node_id"]

    # Create agent node
    resp = auth_client.post(
        f"/api/v1/workflows/{workflow.slug}/nodes/",
        json={"component_type": "agent", "position_x": 300, "position_y": 100},
    )
    assert resp.status_code == 201
    agent_node_id = resp.json()["node_id"]

    # Create skill edge
    resp = auth_client.post(
        f"/api/v1/workflows/{workflow.slug}/edges/",
        json={
            "source_node_id": skill_node_id,
            "target_node_id": agent_node_id,
            "edge_label": "skill",
        },
    )
    assert resp.status_code == 201
    edge = resp.json()
    assert edge["edge_label"] == "skill"
    assert edge["source_node_id"] == skill_node_id
    assert edge["target_node_id"] == agent_node_id


def test_create_skill_edge_to_non_agent_rejected(auth_client, workflow, db):
    """Creating a skill edge to a non-agent node should return 422."""
    # Create skill node
    resp = auth_client.post(
        f"/api/v1/workflows/{workflow.slug}/nodes/",
        json={"component_type": "skill", "position_x": 100, "position_y": 100},
    )
    assert resp.status_code == 201
    skill_node_id = resp.json()["node_id"]

    # Create switch node
    resp = auth_client.post(
        f"/api/v1/workflows/{workflow.slug}/nodes/",
        json={"component_type": "switch", "position_x": 300, "position_y": 100},
    )
    assert resp.status_code == 201
    switch_node_id = resp.json()["node_id"]

    # Try to create skill edge to switch — should fail
    resp = auth_client.post(
        f"/api/v1/workflows/{workflow.slug}/edges/",
        json={
            "source_node_id": skill_node_id,
            "target_node_id": switch_node_id,
            "edge_label": "skill",
        },
    )
    assert resp.status_code == 422


# ── _resolve_skills tests ────────────────────────────────────────────────────


def _make_agent_with_skills(db, workflow, skill_paths):
    """Helper: create an agent node with connected skill nodes.

    Returns the agent WorkflowNode.
    """
    agent_cfg = BaseComponentConfig(component_type="agent", system_prompt="test")
    db.add(agent_cfg)
    db.flush()
    agent_node = WorkflowNode(
        workflow_id=workflow.id,
        node_id="agent_test",
        component_type="agent",
        component_config_id=agent_cfg.id,
    )
    db.add(agent_node)

    for i, path in enumerate(skill_paths):
        cfg = BaseComponentConfig(
            component_type="skill",
            extra_config={"skill_path": path, "skill_source": "filesystem"},
        )
        db.add(cfg)
        db.flush()
        snode = WorkflowNode(
            workflow_id=workflow.id,
            node_id=f"skill_{i:03d}",
            component_type="skill",
            component_config_id=cfg.id,
        )
        db.add(snode)
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id=f"skill_{i:03d}",
            target_node_id="agent_test",
            edge_label="skill",
        )
        db.add(edge)

    db.commit()
    db.refresh(agent_node)
    return agent_node


def test_resolve_skills_empty(db, workflow):
    """_resolve_skills returns empty list when no skill edges exist."""
    agent_cfg = BaseComponentConfig(component_type="agent", system_prompt="test")
    db.add(agent_cfg)
    db.flush()
    agent_node = WorkflowNode(
        workflow_id=workflow.id,
        node_id="agent_empty",
        component_type="agent",
        component_config_id=agent_cfg.id,
    )
    db.add(agent_node)
    db.commit()
    db.refresh(agent_node)

    with patch("database.SessionLocal", return_value=db), \
         patch.object(db, "close"):
        from components._agent_shared import _resolve_skills
        result = _resolve_skills(agent_node)
        assert result == []


def test_resolve_skills_single(db, workflow):
    """_resolve_skills returns one path when one skill node is connected."""
    agent_node = _make_agent_with_skills(db, workflow, ["/custom/skills"])

    with patch("database.SessionLocal", return_value=db), \
         patch.object(db, "close"):
        from components._agent_shared import _resolve_skills
        result = _resolve_skills(agent_node)
        assert result == ["/custom/skills"]


def test_resolve_skills_multiple(db, workflow):
    """_resolve_skills returns multiple paths when multiple skill nodes are connected."""
    agent_node = _make_agent_with_skills(db, workflow, ["/skills/web", "/skills/code"])

    with patch("database.SessionLocal", return_value=db), \
         patch.object(db, "close"):
        from components._agent_shared import _resolve_skills
        result = _resolve_skills(agent_node)
        assert len(result) == 2
        assert "/skills/web" in result
        assert "/skills/code" in result


def test_resolve_skills_empty_path_uses_default(db, workflow):
    """_resolve_skills falls back to platform default when skill_path is empty."""
    agent_node = _make_agent_with_skills(db, workflow, [""])

    with patch("database.SessionLocal", return_value=db), \
         patch.object(db, "close"):
        from components._agent_shared import _resolve_skills
        result = _resolve_skills(agent_node)
        assert len(result) == 1
        # Should end with the platform default path
        assert result[0].endswith(".config/pipelit/skills")


# ── Workflow validation tests ─────────────────────────────────────────────────


def test_validate_workflow_with_skill_edge(db, workflow):
    """Full workflow validation passes with a properly connected skill edge."""
    from validation.edges import EdgeValidator

    agent_node = _make_agent_with_skills(db, workflow, ["/tmp/skills"])

    errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
    # No errors related to the skill edge
    skill_errors = [e for e in errors if "skill" in e.lower()]
    assert skill_errors == []


# ── Config setting test ───────────────────────────────────────────────────────


def test_skills_dir_setting():
    """SKILLS_DIR setting exists and defaults to empty string."""
    from config import Settings
    s = Settings(FIELD_ENCRYPTION_KEY="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwPT0=")
    assert hasattr(s, "SKILLS_DIR")
    # Default is empty string (resolved to ~/.config/pipelit/skills/ at runtime)
    assert s.SKILLS_DIR == ""


# ── Tilde expansion tests ─────────────────────────────────────────────────


def test_resolve_skills_expands_tilde(db, workflow):
    """_resolve_skills expands ~ to the user's home directory."""
    agent_node = _make_agent_with_skills(db, workflow, ["~/my_skills"])

    with patch("database.SessionLocal", return_value=db), \
         patch.object(db, "close"):
        from components._agent_shared import _resolve_skills
        result = _resolve_skills(agent_node)
        assert len(result) == 1
        assert "~" not in result[0]
        assert result[0] == os.path.expanduser("~/my_skills")


# ── skills/ subdirectory auto-detection tests ─────────────────────────────


def test_resolve_skills_auto_detects_skills_subdir(db, workflow, tmp_path):
    """_resolve_skills uses skills/ subdir when it contains SKILL.md files."""
    # Create <tmp>/skills/web-research/SKILL.md
    skill_dir = tmp_path / "skills" / "web-research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: web-research\n---\n")

    agent_node = _make_agent_with_skills(db, workflow, [str(tmp_path)])

    with patch("database.SessionLocal", return_value=db), \
         patch.object(db, "close"):
        from components._agent_shared import _resolve_skills
        result = _resolve_skills(agent_node)
        assert len(result) == 1
        assert result[0] == str(tmp_path / "skills")


def test_resolve_skills_no_subdir_detection_without_skill_md(db, workflow, tmp_path):
    """_resolve_skills does NOT use skills/ subdir if no SKILL.md files exist inside."""
    # Create <tmp>/skills/ with just an empty directory
    (tmp_path / "skills" / "empty").mkdir(parents=True)

    agent_node = _make_agent_with_skills(db, workflow, [str(tmp_path)])

    with patch("database.SessionLocal", return_value=db), \
         patch.object(db, "close"):
        from components._agent_shared import _resolve_skills
        result = _resolve_skills(agent_node)
        assert len(result) == 1
        # Should stay at the original path, not descend into skills/
        assert result[0] == str(tmp_path)


def test_resolve_skills_no_subdir_detection_when_skills_missing(db, workflow, tmp_path):
    """_resolve_skills keeps the original path when no skills/ subdir exists."""
    agent_node = _make_agent_with_skills(db, workflow, [str(tmp_path)])

    with patch("database.SessionLocal", return_value=db), \
         patch.object(db, "close"):
        from components._agent_shared import _resolve_skills
        result = _resolve_skills(agent_node)
        assert len(result) == 1
        assert result[0] == str(tmp_path)


# ── Permission error graceful handling ─────────────────────────────────────


def test_resolve_skills_permission_error_skips_path(db, workflow):
    """_resolve_skills skips a skill path when os.path.expanduser raises."""
    agent_node = _make_agent_with_skills(db, workflow, ["/some/path"])

    with patch("database.SessionLocal", return_value=db), \
         patch.object(db, "close"), \
         patch("os.path.expanduser", side_effect=OSError("permission denied")):
        from components._agent_shared import _resolve_skills
        result = _resolve_skills(agent_node)
        assert result == []


# ── SkillAwareBackend tests ───────────────────────────────────────────────


class TestSkillAwareBackend:
    """Tests for SkillAwareBackend routing logic."""

    def _make_backend(self, skill_paths):
        from components._agent_shared import SkillAwareBackend

        default = MagicMock()
        backend = SkillAwareBackend(default, skill_paths)
        return backend, default

    def test_is_skill_path_exact_match(self):
        backend, _ = self._make_backend(["/home/user/skills"])
        assert backend._is_skill_path("/home/user/skills") is True

    def test_is_skill_path_child(self):
        backend, _ = self._make_backend(["/home/user/skills"])
        assert backend._is_skill_path("/home/user/skills/web-research/SKILL.md") is True

    def test_is_skill_path_non_match(self):
        backend, _ = self._make_backend(["/home/user/skills"])
        assert backend._is_skill_path("/home/user/other") is False

    def test_is_skill_path_partial_prefix_no_match(self):
        """'/home/user/skills-extra' should NOT match '/home/user/skills'."""
        backend, _ = self._make_backend(["/home/user/skills"])
        assert backend._is_skill_path("/home/user/skills-extra") is False

    def test_ls_info_routes_skill_path_to_filesystem(self):
        backend, default = self._make_backend(["/home/user/skills"])
        with patch.object(backend._fs, "ls_info", return_value=[{"path": "/home/user/skills/web"}]) as fs_ls:
            result = backend.ls_info("/home/user/skills")
            fs_ls.assert_called_once_with("/home/user/skills")
            default.ls_info.assert_not_called()
            assert result == [{"path": "/home/user/skills/web"}]

    def test_ls_info_routes_non_skill_to_default(self):
        backend, default = self._make_backend(["/home/user/skills"])
        default.ls_info.return_value = [{"path": "/workspace/src"}]
        result = backend.ls_info("/workspace")
        default.ls_info.assert_called_once_with("/workspace")
        assert result == [{"path": "/workspace/src"}]

    def test_read_routes_skill_path_to_filesystem(self):
        backend, default = self._make_backend(["/skills"])
        with patch.object(backend._fs, "read", return_value="# SKILL.md content") as fs_read:
            result = backend.read("/skills/web/SKILL.md")
            fs_read.assert_called_once_with("/skills/web/SKILL.md", 0, 2000)
            default.read.assert_not_called()
            assert result == "# SKILL.md content"

    def test_read_routes_non_skill_to_default(self):
        backend, default = self._make_backend(["/skills"])
        default.read.return_value = "file content"
        result = backend.read("/workspace/main.py")
        default.read.assert_called_once_with("/workspace/main.py", 0, 2000)
        assert result == "file content"

    def test_download_files_splits_paths(self):
        backend, default = self._make_backend(["/skills"])
        skill_resp = MagicMock()
        other_resp = MagicMock()
        with patch.object(backend._fs, "download_files", return_value=[skill_resp]) as fs_dl:
            default.download_files.return_value = [other_resp]
            result = backend.download_files(["/skills/web/SKILL.md", "/workspace/file.py"])
            fs_dl.assert_called_once_with(["/skills/web/SKILL.md"])
            default.download_files.assert_called_once_with(["/workspace/file.py"])
            assert result == [skill_resp, other_resp]

    def test_download_files_all_skill_paths(self):
        backend, default = self._make_backend(["/skills"])
        r1, r2 = MagicMock(), MagicMock()
        with patch.object(backend._fs, "download_files", return_value=[r1, r2]):
            result = backend.download_files(["/skills/a/SKILL.md", "/skills/b/SKILL.md"])
            default.download_files.assert_not_called()
            assert result == [r1, r2]

    def test_getattr_delegates_to_default(self):
        """Unknown methods are delegated to the default backend via __getattr__."""
        backend, default = self._make_backend(["/skills"])
        default.write.return_value = "ok"
        result = backend.write("/workspace/out.txt", "content")
        default.write.assert_called_once_with("/workspace/out.txt", "content")
        assert result == "ok"


# ── SandboxedSkillAwareBackend tests ──────────────────────────────────────


class TestSandboxedSkillAwareBackend:
    """Tests for SandboxedSkillAwareBackend — execute delegation + isinstance."""

    def _make_sandbox_backend(self, skill_paths):
        from components._agent_shared import SandboxedSkillAwareBackend

        default = MagicMock()
        default.id = "sandbox-123"
        backend = SandboxedSkillAwareBackend(default, skill_paths)
        return backend, default

    def test_isinstance_sandbox_backend_protocol(self):
        """SandboxedSkillAwareBackend passes isinstance(SandboxBackendProtocol)."""
        from deepagents.backends.protocol import SandboxBackendProtocol
        backend, _ = self._make_sandbox_backend(["/skills"])
        assert isinstance(backend, SandboxBackendProtocol)

    def test_id_delegates_to_default(self):
        """id property delegates to the underlying default backend."""
        backend, default = self._make_sandbox_backend(["/skills"])
        assert backend.id == "sandbox-123"

    def test_execute_delegates_to_default(self):
        """execute() delegates to the underlying default backend."""
        from deepagents.backends.protocol import ExecuteResponse

        backend, default = self._make_sandbox_backend(["/skills"])
        expected = ExecuteResponse(output="hello", exit_code=0)
        default.execute.return_value = expected

        result = backend.execute("echo hello", timeout=30)
        default.execute.assert_called_once_with("echo hello", timeout=30)
        assert result is expected

    def test_execute_delegates_without_timeout(self):
        """execute() passes timeout=None when not specified."""
        from deepagents.backends.protocol import ExecuteResponse

        backend, default = self._make_sandbox_backend(["/skills"])
        default.execute.return_value = ExecuteResponse(output="ok", exit_code=0)

        backend.execute("ls")
        default.execute.assert_called_once_with("ls", timeout=None)

    @pytest.mark.asyncio
    async def test_aexecute_delegates_to_default(self):
        """aexecute() delegates to the underlying default backend."""
        from unittest.mock import AsyncMock
        from deepagents.backends.protocol import ExecuteResponse

        backend, default = self._make_sandbox_backend(["/skills"])
        expected = ExecuteResponse(output="async hello", exit_code=0)
        default.aexecute = AsyncMock(return_value=expected)

        result = await backend.aexecute("echo hello", timeout=60)
        default.aexecute.assert_called_once_with("echo hello", timeout=60)
        assert result is expected

    def test_skill_path_routing_still_works(self):
        """File routing to skill paths is preserved from SkillAwareBackend."""
        backend, default = self._make_sandbox_backend(["/skills"])
        with patch.object(backend._fs, "read", return_value="# SKILL.md") as fs_read:
            result = backend.read("/skills/web/SKILL.md")
            fs_read.assert_called_once_with("/skills/web/SKILL.md", 0, 2000)
            default.read.assert_not_called()
            assert result == "# SKILL.md"

    def test_is_subclass_of_skill_aware_backend(self):
        """SandboxedSkillAwareBackend is a subclass of SkillAwareBackend."""
        from components._agent_shared import SandboxedSkillAwareBackend, SkillAwareBackend
        assert issubclass(SandboxedSkillAwareBackend, SkillAwareBackend)

    def test_plain_skill_aware_backend_not_sandbox_protocol(self):
        """Plain SkillAwareBackend does NOT pass isinstance(SandboxBackendProtocol)."""
        from components._agent_shared import SkillAwareBackend
        from deepagents.backends.protocol import SandboxBackendProtocol

        default = MagicMock()
        backend = SkillAwareBackend(default, ["/skills"])
        assert not isinstance(backend, SandboxBackendProtocol)


# ── _make_skill_aware_backend factory tests ───────────────────────────────


class TestMakeSkillAwareBackend:
    """Tests for the _make_skill_aware_backend factory function."""

    def test_factory_with_class_backend(self):
        """Factory correctly instantiates a class-based backend (like StateBackend)."""
        from components._agent_shared import _make_skill_aware_backend, SkillAwareBackend

        class MockBackendClass:
            def __init__(self, tool_runtime):
                self.tool_runtime = tool_runtime

        factory = _make_skill_aware_backend(MockBackendClass, ["/skills"])
        runtime = MagicMock()
        result = factory(runtime)

        assert isinstance(result, SkillAwareBackend)
        assert isinstance(result._default, MockBackendClass)
        assert result._default.tool_runtime is runtime

    def test_factory_with_instance_backend(self):
        """Factory wraps an existing backend instance directly."""
        from components._agent_shared import _make_skill_aware_backend, SkillAwareBackend

        # Use a plain object with ls_info to simulate a backend instance
        # (MagicMock is always callable, so it would be treated as a factory)
        class FakeBackend:
            def ls_info(self, path):
                return []

        existing_backend = FakeBackend()
        factory = _make_skill_aware_backend(existing_backend, ["/skills"])
        runtime = MagicMock()
        result = factory(runtime)

        assert isinstance(result, SkillAwareBackend)
        assert result._default is existing_backend

    def test_factory_preserves_skill_paths(self):
        """Factory passes skill paths through to SkillAwareBackend."""
        from components._agent_shared import _make_skill_aware_backend

        paths = ["/skills/web", "/skills/code"]
        factory = _make_skill_aware_backend(MagicMock(), paths)
        result = factory(MagicMock())

        assert result._skill_paths == ["/skills/web", "/skills/code"]

    def test_factory_returns_sandboxed_variant_for_sandbox_backend(self):
        """Factory returns SandboxedSkillAwareBackend when default is SandboxBackendProtocol."""
        from components._agent_shared import _make_skill_aware_backend, SandboxedSkillAwareBackend
        from components.sandboxed_backend import SandboxedShellBackend

        # SandboxedShellBackend inherits from LocalShellBackend which is a SandboxBackendProtocol
        sandbox_backend = MagicMock(spec=SandboxedShellBackend)
        sandbox_backend.ls_info = MagicMock()  # has ls_info → treated as instance

        factory = _make_skill_aware_backend(sandbox_backend, ["/skills"])
        result = factory(MagicMock())

        assert isinstance(result, SandboxedSkillAwareBackend)

    def test_factory_returns_plain_variant_for_non_sandbox_backend(self):
        """Factory returns plain SkillAwareBackend when default is NOT SandboxBackendProtocol."""
        from components._agent_shared import _make_skill_aware_backend, SkillAwareBackend, SandboxedSkillAwareBackend

        class FakeStateBackend:
            def __init__(self, tool_runtime):
                pass

        factory = _make_skill_aware_backend(FakeStateBackend, ["/skills"])
        result = factory(MagicMock())

        assert isinstance(result, SkillAwareBackend)
        assert not isinstance(result, SandboxedSkillAwareBackend)


# ── Workspace backend tests ───────────────────────────────────────────────


def test_get_workspace_dir_creates_directory(tmp_path):
    """_get_workspace_dir creates the directory and returns an absolute path."""
    workspace = str(tmp_path / "ws" / "default")
    with patch("config.settings") as mock_settings:
        mock_settings.WORKSPACE_DIR = workspace
        from components._agent_shared import _get_workspace_dir
        result = _get_workspace_dir()
        assert result == workspace
        assert os.path.isdir(workspace)


def test_get_workspace_dir_default_path():
    """_get_workspace_dir falls back to ~/.config/pipelit/workspaces/default."""
    with patch("config.settings") as mock_settings:
        mock_settings.WORKSPACE_DIR = ""
        from components._agent_shared import _get_workspace_dir
        result = _get_workspace_dir()
        assert result.endswith(os.path.join(".config", "pipelit", "workspaces", "default"))
        assert os.path.isabs(result)


def test_build_backend_returns_sandboxed_shell_backend(tmp_path):
    """_build_backend returns a SandboxedShellBackend with virtual_mode=True."""
    workspace = str(tmp_path / "agent_workspace")
    extra = {"filesystem_root_dir": workspace}

    from components.deep_agent import _build_backend
    from components.sandboxed_backend import SandboxedShellBackend
    backend = _build_backend(extra)

    assert isinstance(backend, SandboxedShellBackend)
    assert backend.virtual_mode is True
    assert str(backend.cwd) == workspace
    assert os.path.isdir(workspace)


def test_build_backend_uses_default_workspace(tmp_path):
    """_build_backend uses _get_workspace_dir() when no root_dir in extra."""
    workspace = str(tmp_path / "default_ws")
    with patch("components._agent_shared._get_workspace_dir", return_value=workspace):
        from components.deep_agent import _build_backend
        backend = _build_backend({})

    from components.sandboxed_backend import SandboxedShellBackend
    assert isinstance(backend, SandboxedShellBackend)
    assert backend.virtual_mode is True


def test_workspace_dir_setting():
    """WORKSPACE_DIR setting exists and defaults to empty string."""
    from config import Settings
    s = Settings(FIELD_ENCRYPTION_KEY="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwPT0=")
    assert hasattr(s, "WORKSPACE_DIR")
    assert s.WORKSPACE_DIR == ""


# ── Async SkillAwareBackend tests ──────────────────────────────────────────


class TestSkillAwareBackendAsync:
    """Tests for async methods on SkillAwareBackend."""

    def _make_backend(self, skill_paths):
        from components._agent_shared import SkillAwareBackend

        default = MagicMock()
        backend = SkillAwareBackend(default, skill_paths)
        return backend, default

    @pytest.mark.asyncio
    async def test_als_info_routes_skill_path(self):
        backend, default = self._make_backend(["/home/user/skills"])
        with patch.object(
            backend._fs, "als_info", new_callable=AsyncMock,
            return_value=[{"path": "/home/user/skills/web"}],
        ) as fs_als:
            result = await backend.als_info("/home/user/skills")
            fs_als.assert_called_once_with("/home/user/skills")
            default.als_info.assert_not_called()
            assert result == [{"path": "/home/user/skills/web"}]

    @pytest.mark.asyncio
    async def test_als_info_routes_non_skill(self):
        backend, default = self._make_backend(["/home/user/skills"])
        default.als_info = AsyncMock(return_value=[{"path": "/workspace/src"}])
        result = await backend.als_info("/workspace")
        default.als_info.assert_called_once_with("/workspace")
        assert result == [{"path": "/workspace/src"}]

    @pytest.mark.asyncio
    async def test_aread_routes_skill_path(self):
        backend, default = self._make_backend(["/skills"])
        with patch.object(
            backend._fs, "aread", new_callable=AsyncMock,
            return_value="# SKILL.md content",
        ) as fs_aread:
            result = await backend.aread("/skills/web/SKILL.md")
            fs_aread.assert_called_once_with("/skills/web/SKILL.md", 0, 2000)
            default.aread.assert_not_called()
            assert result == "# SKILL.md content"

    @pytest.mark.asyncio
    async def test_aread_routes_non_skill(self):
        backend, default = self._make_backend(["/skills"])
        default.aread = AsyncMock(return_value="file content")
        result = await backend.aread("/workspace/main.py")
        default.aread.assert_called_once_with("/workspace/main.py", 0, 2000)
        assert result == "file content"

    @pytest.mark.asyncio
    async def test_adownload_files_splits_paths(self):
        backend, default = self._make_backend(["/skills"])
        skill_resp = MagicMock()
        other_resp = MagicMock()
        with patch.object(
            backend._fs, "adownload_files", new_callable=AsyncMock,
            return_value=[skill_resp],
        ) as fs_dl:
            default.adownload_files = AsyncMock(return_value=[other_resp])
            result = await backend.adownload_files(
                ["/skills/web/SKILL.md", "/workspace/file.py"]
            )
            fs_dl.assert_called_once_with(["/skills/web/SKILL.md"])
            default.adownload_files.assert_called_once_with(["/workspace/file.py"])
            assert result == [skill_resp, other_resp]

    @pytest.mark.asyncio
    async def test_adownload_files_all_skill_paths(self):
        backend, default = self._make_backend(["/skills"])
        r1, r2 = MagicMock(), MagicMock()
        with patch.object(
            backend._fs, "adownload_files", new_callable=AsyncMock,
            return_value=[r1, r2],
        ):
            result = await backend.adownload_files(
                ["/skills/a/SKILL.md", "/skills/b/SKILL.md"]
            )
            default.adownload_files.assert_not_called()
            assert result == [r1, r2]

    @pytest.mark.asyncio
    async def test_adownload_files_all_default_paths(self):
        backend, default = self._make_backend(["/skills"])
        r1, r2 = MagicMock(), MagicMock()
        default.adownload_files = AsyncMock(return_value=[r1, r2])
        result = await backend.adownload_files(
            ["/workspace/a.py", "/workspace/b.py"]
        )
        default.adownload_files.assert_called_once_with(
            ["/workspace/a.py", "/workspace/b.py"]
        )
        assert result == [r1, r2]


# ── Agent factory skill integration tests ──────────────────────────────────


class TestAgentFactorySkills:
    """Tests for agent_factory() with skill_paths."""

    def test_agent_factory_with_skills(self):
        """agent_factory appends SkillsMiddleware when skill_paths are resolved."""
        mock_node = MagicMock()
        mock_node.node_id = "agent_001"
        mock_node.workflow_id = 1
        mock_node.workflow.slug = "test-wf"
        mock_node.component_config.concrete.system_prompt = "You are helpful."
        mock_node.component_config.concrete.extra_config = {}
        mock_node.component_config.concrete.max_tokens = None

        mock_skills_mw_cls = MagicMock()
        mock_skills_mw_instance = MagicMock()
        mock_skills_mw_cls.return_value = mock_skills_mw_instance

        mock_fs_backend_cls = MagicMock()
        mock_fs_backend_instance = MagicMock()
        mock_fs_backend_cls.return_value = mock_fs_backend_instance

        with patch("components.agent._resolve_skills", return_value=["/skills/web"]), \
             patch("components.agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.agent._resolve_tools", return_value=([], {})), \
             patch("components.agent.get_model_name_for_node", return_value="test-model"), \
             patch("deepagents.middleware.skills.SkillsMiddleware", mock_skills_mw_cls), \
             patch("deepagents.backends.filesystem.FilesystemBackend", mock_fs_backend_cls), \
             patch("components.agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock(invoke=MagicMock(return_value={"messages": []}))
            from components.agent import agent_factory
            agent_factory(mock_node)

            # SkillsMiddleware should have been instantiated
            mock_skills_mw_cls.assert_called_once()
            call_kwargs = mock_skills_mw_cls.call_args
            assert call_kwargs[1]["backend"] is mock_fs_backend_instance
            assert call_kwargs[1]["sources"] == ["/skills/web"]

            # create_agent should have received middlewares list including skills mw
            create_call_kwargs = mock_create.call_args[1]
            assert mock_skills_mw_instance in create_call_kwargs["middleware"]


# ── Deep agent factory skill integration tests ─────────────────────────────


class TestDeepAgentFactorySkills:
    """Tests for deep_agent_factory() with skill_paths."""

    def test_deep_agent_factory_with_skills(self):
        """deep_agent_factory wraps backend with _make_skill_aware_backend when skills present."""
        mock_node = MagicMock()
        mock_node.node_id = "deep_agent_001"
        mock_node.workflow_id = 1
        mock_node.workflow.slug = "test-wf"
        mock_node.component_config.concrete.system_prompt = "You are helpful."
        mock_node.component_config.concrete.extra_config = {}
        mock_node.component_config.concrete.max_tokens = None

        mock_backend = MagicMock()
        mock_skill_factory = MagicMock()

        with patch("components.deep_agent._resolve_skills", return_value=["/skills/code"]), \
             patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent.get_model_name_for_node", return_value="test-model"), \
             patch("components.deep_agent._build_backend", return_value=mock_backend), \
             patch("components.deep_agent._make_skill_aware_backend", return_value=mock_skill_factory) as mock_make_skill, \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock(invoke=MagicMock(return_value={"messages": []}))
            from components.deep_agent import deep_agent_factory
            deep_agent_factory(mock_node)

            # _make_skill_aware_backend should have been called with the backend and paths
            mock_make_skill.assert_called_once_with(mock_backend, ["/skills/code"])

            # create_deep_agent should receive the skill-aware factory as backend and skill_paths
            create_call_kwargs = mock_create.call_args[1]
            assert create_call_kwargs["backend"] is mock_skill_factory
            assert create_call_kwargs["skills"] == ["/skills/code"]
