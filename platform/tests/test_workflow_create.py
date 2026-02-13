"""Integration tests for the workflow_create tool + DSL compiler with DB fixtures."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from models.credential import BaseCredential, LLMProviderCredential
from models.node import (
    COMPONENT_TYPE_TO_CONFIG,
    BaseComponentConfig,
    WorkflowEdge,
    WorkflowNode,
)
from models.workflow import Workflow
from services.dsl_compiler import compile_dsl


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def llm_credential(db, user_profile):
    base = BaseCredential(
        user_profile_id=user_profile.id,
        name="Test OpenAI",
        credential_type="llm",
    )
    db.add(base)
    db.flush()
    llm = LLMProviderCredential(
        base_credentials_id=base.id,
        provider_type="openai_compatible",
        api_key="sk-test-key",
        base_url="https://api.openai.com/v1",
    )
    db.add(llm)
    db.commit()
    db.refresh(base)
    return base


@pytest.fixture
def source_workflow(db, user_profile):
    """Create a source workflow with a trigger, agent, and code node for fork tests."""
    wf = Workflow(
        name="Source Workflow",
        slug="source-workflow",
        owner_id=user_profile.id,
        is_active=True,
        tags=["source", "test"],
    )
    db.add(wf)
    db.flush()

    # Trigger
    trigger_cfg = BaseComponentConfig(
        component_type="trigger_chat",
        is_active=True,
        trigger_config={},
    )
    db.add(trigger_cfg)
    db.flush()
    trigger_node = WorkflowNode(
        workflow_id=wf.id,
        node_id="trigger_chat_1",
        component_type="trigger_chat",
        component_config_id=trigger_cfg.id,
        position_x=0,
        position_y=200,
    )
    db.add(trigger_node)

    # Agent
    agent_cfg = BaseComponentConfig(
        component_type="agent",
        system_prompt="You are helpful",
        extra_config={},
    )
    db.add(agent_cfg)
    db.flush()
    agent_node = WorkflowNode(
        workflow_id=wf.id,
        node_id="agent_1",
        component_type="agent",
        component_config_id=agent_cfg.id,
        is_entry_point=True,
        position_x=300,
        position_y=200,
    )
    db.add(agent_node)

    # Code
    code_cfg = BaseComponentConfig(
        component_type="code",
        code_snippet="print('done')",
        code_language="python",
    )
    db.add(code_cfg)
    db.flush()
    code_node = WorkflowNode(
        workflow_id=wf.id,
        node_id="code_1",
        component_type="code",
        component_config_id=code_cfg.id,
        position_x=600,
        position_y=200,
    )
    db.add(code_node)

    # Edges
    db.add(WorkflowEdge(
        workflow_id=wf.id,
        source_node_id="trigger_chat_1",
        target_node_id="agent_1",
        edge_type="direct",
    ))
    db.add(WorkflowEdge(
        workflow_id=wf.id,
        source_node_id="agent_1",
        target_node_id="code_1",
        edge_type="direct",
    ))

    db.commit()
    db.refresh(wf)
    return wf


# ── Tool factory tests ───────────────────────────────────────────────────────


class TestToolFactory:
    def test_factory_returns_tool_list(self):
        from components.workflow_create import workflow_create_factory

        node = SimpleNamespace(workflow_id=1, node_id="wc_1")
        tools = workflow_create_factory(node)
        assert isinstance(tools, list)
        assert len(tools) == 1
        assert tools[0].name == "workflow_create"

    def test_tool_has_correct_args(self):
        from components.workflow_create import workflow_create_factory

        node = SimpleNamespace(workflow_id=1, node_id="wc_1")
        tool = workflow_create_factory(node)[0]
        schema = tool.args_schema.model_json_schema()
        assert "dsl" in schema["properties"]
        assert "tags" in schema["properties"]


# ── Registration tests ───────────────────────────────────────────────────────


class TestRegistration:
    def test_in_component_registry(self):
        from components import COMPONENT_REGISTRY
        assert "workflow_create" in COMPONENT_REGISTRY

    def test_in_node_type_registry(self):
        import schemas.node_type_defs  # noqa: F401 — triggers registration
        from schemas.node_types import NODE_TYPE_REGISTRY
        assert "workflow_create" in NODE_TYPE_REGISTRY
        spec = NODE_TYPE_REGISTRY["workflow_create"]
        assert spec.category == "agent"

    def test_in_component_type_to_config(self):
        assert "workflow_create" in COMPONENT_TYPE_TO_CONFIG

    def test_in_builder_sub_component_types(self):
        from services.builder import SUB_COMPONENT_TYPES
        assert "workflow_create" in SUB_COMPONENT_TYPES

    def test_in_topology_sub_component_types(self):
        from services.topology import SUB_COMPONENT_TYPES
        assert "workflow_create" in SUB_COMPONENT_TYPES

    def test_spawn_and_await_also_registered(self):
        """spawn_and_await was missing from ComponentTypeStr — verify it's now included."""
        from schemas.node import ComponentTypeStr
        # ComponentTypeStr is a Literal — check its args
        import typing
        args = typing.get_args(ComponentTypeStr)
        assert "spawn_and_await" in args
        assert "workflow_create" in args


# ── End-to-end compile_dsl with DB ───────────────────────────────────────────


class TestCompileDslDB:
    @patch("services.dsl_compiler.broadcast", create=True)
    def test_create_simple_workflow(self, mock_broadcast, db, user_profile):
        yaml_str = """\
name: Simple Test
trigger: manual
steps:
  - type: code
    id: code_1
    snippet: "print('hello')"
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True
        assert result["slug"] == "simple-test"
        assert result["node_count"] == 2  # trigger + code
        assert result["edge_count"] == 1
        assert result["mode"] == "created"

        # Verify in DB
        wf = db.query(Workflow).filter_by(slug="simple-test").first()
        assert wf is not None
        assert wf.owner_id == user_profile.id
        assert wf.is_callable is True

        nodes = db.query(WorkflowNode).filter_by(workflow_id=wf.id).all()
        assert len(nodes) == 2

        edges = db.query(WorkflowEdge).filter_by(workflow_id=wf.id).all()
        assert len(edges) == 1

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_create_agent_workflow_with_model(self, mock_broadcast, db, user_profile, llm_credential):
        yaml_str = f"""\
name: Agent Test
trigger: chat
model:
  credential_id: {llm_credential.id}
  model_name: gpt-4
  temperature: 0.7
steps:
  - type: agent
    id: my_agent
    prompt: "You are a test agent"
    tools:
      - calculator
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True
        assert result["node_count"] == 4  # trigger + agent + ai_model + calculator

        wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        nodes = db.query(WorkflowNode).filter_by(workflow_id=wf.id).all()

        agent_node = next(n for n in nodes if n.component_type == "agent")
        assert agent_node.component_config.system_prompt == "You are a test agent"

        model_node = next(n for n in nodes if n.component_type == "ai_model")
        assert model_node.component_config.model_name == "gpt-4"

        calc_node = next(n for n in nodes if n.component_type == "calculator")
        assert calc_node is not None

        # Verify tool edge
        tool_edges = [
            e for e in db.query(WorkflowEdge).filter_by(workflow_id=wf.id).all()
            if e.edge_label == "tool"
        ]
        assert len(tool_edges) == 1

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_slug_uniqueness(self, mock_broadcast, db, user_profile):
        yaml_str = """\
name: Unique Test
trigger: manual
steps:
  - type: code
    snippet: pass
"""
        result1 = compile_dsl(yaml_str, user_profile.id, db)
        assert result1["success"] is True
        assert result1["slug"] == "unique-test"

        result2 = compile_dsl(yaml_str, user_profile.id, db)
        assert result2["success"] is True
        assert result2["slug"] == "unique-test-2"

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_create_with_tags(self, mock_broadcast, db, user_profile):
        yaml_str = """\
name: Tagged Workflow
tags:
  - automation
  - testing
steps:
  - type: code
    snippet: pass
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True

        wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        assert "automation" in wf.tags
        assert "testing" in wf.tags

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_dict_form_trigger(self, mock_broadcast, db, user_profile):
        """Dict-form trigger (type: manual) should work same as string form."""
        yaml_str = """\
name: Dict Trigger Test
trigger:
  type: manual
steps:
  - type: code
    id: code_1
    snippet: "return {'ok': True}"
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True
        assert result["node_count"] == 2

        wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        nodes = db.query(WorkflowNode).filter_by(workflow_id=wf.id).all()
        trigger = next(n for n in nodes if n.component_type.startswith("trigger_"))
        assert trigger.component_type == "trigger_manual"

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_code_key_alias_for_snippet(self, mock_broadcast, db, user_profile):
        """LLMs often use 'code' instead of 'snippet' — both should work."""
        yaml_str = """\
name: Code Alias Test
trigger: manual
steps:
  - type: code
    id: code_1
    code: "return {'hello': 'world'}"
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True

        wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        nodes = db.query(WorkflowNode).filter_by(workflow_id=wf.id).all()
        code_node = next(n for n in nodes if n.component_type == "code")
        assert code_node.component_config.extra_config["code"] == "return {'hello': 'world'}"

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_nested_config_code(self, mock_broadcast, db, user_profile):
        """LLMs sometimes nest code under config: {code: ...}."""
        yaml_str = """\
name: Nested Config Test
trigger: manual
steps:
  - type: code
    id: code_1
    config:
      code: "return {'nested': True}"
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True

        wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        nodes = db.query(WorkflowNode).filter_by(workflow_id=wf.id).all()
        code_node = next(n for n in nodes if n.component_type == "code")
        assert code_node.component_config.extra_config["code"] == "return {'nested': True}"


# ── Fork & patch DB tests ───────────────────────────────────────────────────


class TestForkDB:
    @patch("services.dsl_compiler.broadcast", create=True)
    def test_fork_basic(self, mock_broadcast, db, user_profile, source_workflow):
        yaml_str = """\
based_on: source-workflow
name: Forked Workflow
patches:
  - action: update_prompt
    step_id: agent_1
    prompt: "Updated prompt"
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True
        assert result["mode"] == "forked"
        assert result["slug"] == "forked-workflow"

        # Source preserved
        source_nodes = db.query(WorkflowNode).filter_by(workflow_id=source_workflow.id).all()
        source_agent = next(n for n in source_nodes if n.node_id == "agent_1")
        assert source_agent.component_config.system_prompt == "You are helpful"

        # Fork has updated prompt
        forked_wf = db.query(Workflow).filter_by(slug="forked-workflow").first()
        assert forked_wf.forked_from_id == source_workflow.id
        forked_nodes = db.query(WorkflowNode).filter_by(workflow_id=forked_wf.id).all()
        forked_agent = next(n for n in forked_nodes if n.node_id == "agent_1")
        assert forked_agent.component_config.system_prompt == "Updated prompt"

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_fork_add_step(self, mock_broadcast, db, user_profile, source_workflow):
        yaml_str = """\
based_on: source-workflow
name: Fork Add Step
patches:
  - action: add_step
    after: agent_1
    step:
      type: code
      id: inserted_step
      snippet: "print('inserted')"
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True

        forked_wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        nodes = db.query(WorkflowNode).filter_by(workflow_id=forked_wf.id).all()
        assert any(n.node_id == "inserted_step" for n in nodes)
        # 3 original + 1 inserted = 4 nodes
        assert len(nodes) == 4

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_fork_remove_step(self, mock_broadcast, db, user_profile, source_workflow):
        yaml_str = """\
based_on: source-workflow
name: Fork Remove Step
patches:
  - action: remove_step
    step_id: code_1
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True

        forked_wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        nodes = db.query(WorkflowNode).filter_by(workflow_id=forked_wf.id).all()
        assert not any(n.node_id == "code_1" for n in nodes)
        assert len(nodes) == 2  # trigger + agent only

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_fork_add_tool(self, mock_broadcast, db, user_profile, source_workflow):
        yaml_str = """\
based_on: source-workflow
name: Fork Add Tool
patches:
  - action: add_tool
    step_id: agent_1
    tool: calculator
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True

        forked_wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        nodes = db.query(WorkflowNode).filter_by(workflow_id=forked_wf.id).all()
        calc_nodes = [n for n in nodes if n.component_type == "calculator"]
        assert len(calc_nodes) == 1

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_fork_nonexistent_source(self, mock_broadcast, db, user_profile):
        yaml_str = """\
based_on: does-not-exist
patches:
  - action: update_prompt
    step_id: x
    prompt: y
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is False
        assert "not found" in result["error"]


# ── Model resolution with DB ────────────────────────────────────────────────


class TestModelResolutionDB:
    @patch("services.dsl_compiler.broadcast", create=True)
    def test_capability_resolution(self, mock_broadcast, db, user_profile, llm_credential):
        yaml_str = """\
name: Capability Test
trigger: chat
model:
  capability: gpt-4
steps:
  - type: agent
    id: smart_agent
    prompt: "Be smart"
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True

        wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        nodes = db.query(WorkflowNode).filter_by(workflow_id=wf.id).all()
        model_node = next((n for n in nodes if n.component_type == "ai_model"), None)
        assert model_node is not None
        assert model_node.component_config.model_name == "gpt-4"

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_direct_credential_id(self, mock_broadcast, db, user_profile, llm_credential):
        yaml_str = f"""\
name: Direct Cred
model:
  credential_id: {llm_credential.id}
  model_name: claude-3
  temperature: 0.5
steps:
  - type: agent
    prompt: test
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is True

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_no_credential_found(self, mock_broadcast, db, user_profile):
        yaml_str = """\
name: No Cred
model:
  capability: nonexistent-model
steps:
  - type: agent
    prompt: test
"""
        result = compile_dsl(yaml_str, user_profile.id, db)
        assert result["success"] is False
        assert "No LLM credential" in result["error"]


# ── Tool invocation test (with mocked DB session) ───────────────────────────


class TestToolInvocation:
    @patch("services.dsl_compiler.broadcast", create=True)
    def test_tool_end_to_end(self, mock_broadcast, db, user_profile, workflow):
        """Test the workflow_create tool function directly."""
        from components.workflow_create import workflow_create_factory

        # Create a workflow_create node attached to the test workflow
        cfg = BaseComponentConfig(component_type="workflow_create", extra_config={})
        db.add(cfg)
        db.flush()
        wc_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="wc_1",
            component_type="workflow_create",
            component_config_id=cfg.id,
        )
        db.add(wc_node)
        db.commit()

        node = SimpleNamespace(workflow_id=workflow.id, node_id="wc_1")
        tool = workflow_create_factory(node)[0]

        yaml_str = """\
name: Tool Created Workflow
trigger: manual
steps:
  - type: code
    snippet: "print('from tool')"
"""
        with patch("database.SessionLocal", return_value=db):
            # Prevent db.close() from actually closing our test session
            with patch.object(db, "close"):
                result_str = tool.invoke({"dsl": yaml_str})

        result = json.loads(result_str)
        assert result["success"] is True
        assert result["slug"] == "tool-created-workflow"

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_tool_with_tags(self, mock_broadcast, db, user_profile, workflow):
        from components.workflow_create import workflow_create_factory

        cfg = BaseComponentConfig(component_type="workflow_create", extra_config={})
        db.add(cfg)
        db.flush()
        wc_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="wc_2",
            component_type="workflow_create",
            component_config_id=cfg.id,
        )
        db.add(wc_node)
        db.commit()

        node = SimpleNamespace(workflow_id=workflow.id, node_id="wc_2")
        tool = workflow_create_factory(node)[0]

        yaml_str = """\
name: Tagged Tool WF
trigger: manual
steps:
  - type: code
    snippet: pass
"""
        with patch("database.SessionLocal", return_value=db):
            with patch.object(db, "close"):
                result_str = tool.invoke({"dsl": yaml_str, "tags": "alpha, beta"})

        result = json.loads(result_str)
        assert result["success"] is True

        wf = db.query(Workflow).filter_by(slug=result["slug"]).first()
        assert "alpha" in wf.tags
        assert "beta" in wf.tags

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_tool_resolves_parent_via_edge(self, mock_broadcast, db, user_profile, workflow):
        """Tool follows the tool edge to find the parent agent node."""
        from components.workflow_create import workflow_create_factory

        # Create an agent node with LLM config
        agent_cfg = BaseComponentConfig(
            component_type="agent",
            system_prompt="I am the parent",
            extra_config={},
        )
        db.add(agent_cfg)
        db.flush()
        agent_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="agent_parent",
            component_type="agent",
            component_config_id=agent_cfg.id,
        )
        db.add(agent_node)

        # Create a workflow_create tool node
        wc_cfg = BaseComponentConfig(component_type="workflow_create", extra_config={})
        db.add(wc_cfg)
        db.flush()
        wc_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="wc_edge",
            component_type="workflow_create",
            component_config_id=wc_cfg.id,
        )
        db.add(wc_node)

        # Create a tool edge: wc_edge → agent_parent (edge_label="tool")
        db.add(WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id="wc_edge",
            target_node_id="agent_parent",
            edge_type="direct",
            edge_label="tool",
        ))
        db.commit()

        node = SimpleNamespace(workflow_id=workflow.id, node_id="wc_edge")
        tool = workflow_create_factory(node)[0]

        yaml_str = """\
name: Edge Resolved WF
trigger: manual
steps:
  - type: code
    snippet: "print('edge test')"
"""
        with patch("database.SessionLocal", return_value=db):
            with patch.object(db, "close"):
                result_str = tool.invoke({"dsl": yaml_str})

        result = json.loads(result_str)
        assert result["success"] is True
        assert result["slug"] == "edge-resolved-wf"

    @patch("services.dsl_compiler.broadcast", create=True)
    def test_tool_returns_error_on_exception(self, mock_broadcast, db, user_profile, workflow):
        """Tool returns error JSON and rolls back DB on exception."""
        from components.workflow_create import workflow_create_factory

        wc_cfg = BaseComponentConfig(component_type="workflow_create", extra_config={})
        db.add(wc_cfg)
        db.flush()
        wc_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="wc_err2",
            component_type="workflow_create",
            component_config_id=wc_cfg.id,
        )
        db.add(wc_node)
        db.commit()

        node = SimpleNamespace(workflow_id=workflow.id, node_id="wc_err2")
        tool = workflow_create_factory(node)[0]

        with patch("database.SessionLocal", return_value=db):
            with patch.object(db, "close"):
                with patch("services.dsl_compiler.compile_dsl", side_effect=RuntimeError("boom")):
                    result_str = tool.invoke({"dsl": "name: X\nsteps:\n  - type: code"})

        result = json.loads(result_str)
        assert result["success"] is False
        assert "boom" in result["error"]

    def test_tool_error_handling(self):
        from components.workflow_create import workflow_create_factory

        node = SimpleNamespace(workflow_id=999, node_id="wc_err")
        tool = workflow_create_factory(node)[0]

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("database.SessionLocal", return_value=mock_db):
            result_str = tool.invoke({"dsl": "name: X\nsteps:\n  - type: code"})

        result = json.loads(result_str)
        assert result["success"] is False
        assert "not found" in result["error"]
