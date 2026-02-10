"""Unit tests for the DSL compiler — parsing, graph building, model resolution, fork & patch."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.dsl_compiler import (
    STEP_TYPE_MAP,
    TOOL_TYPE_MAP,
    TRIGGER_TYPE_MAP,
    _build_graph,
    _parse_dsl,
    _resolve_model,
    _slugify,
    _unique_slug,
    compile_dsl,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

MINIMAL_YAML = """\
name: Test Workflow
trigger: webhook
steps:
  - type: code
    id: code_1
    snippet: "print('hello')"
"""

AGENT_YAML = """\
name: Agent Flow
trigger: chat
model:
  capability: gpt-4
steps:
  - type: agent
    id: my_agent
    prompt: "You are a helpful assistant"
    tools:
      - calculator
      - type: web_search
        searxng_url: http://localhost:8888
"""

FORK_YAML = """\
based_on: source-workflow
name: Forked Flow
patches:
  - action: update_prompt
    step_id: agent_1
    prompt: "New prompt"
"""

HTTP_YAML = """\
name: HTTP Flow
trigger: manual
steps:
  - type: http
    id: fetch_data
    url: https://example.com/api
    method: POST
    headers:
      Content-Type: application/json
    body: '{"key": "value"}'
    timeout: 60
"""


# ── Parse tests ──────────────────────────────────────────────────────────────


class TestParseDsl:
    def test_parse_minimal(self):
        parsed = _parse_dsl(MINIMAL_YAML)
        assert parsed["name"] == "Test Workflow"
        assert parsed["trigger"] == "webhook"
        assert len(parsed["steps"]) == 1

    def test_parse_invalid_yaml(self):
        with pytest.raises(ValueError, match="Invalid YAML"):
            _parse_dsl("{{not yaml")

    def test_parse_non_dict(self):
        with pytest.raises(ValueError, match="YAML mapping"):
            _parse_dsl("- just\n- a\n- list")

    def test_parse_missing_name(self):
        with pytest.raises(ValueError, match="`name`"):
            _parse_dsl("trigger: webhook\nsteps:\n  - type: code")

    def test_parse_missing_steps(self):
        with pytest.raises(ValueError, match="`steps`"):
            _parse_dsl("name: Test\ntrigger: webhook")

    def test_parse_empty_steps(self):
        with pytest.raises(ValueError, match="non-empty"):
            _parse_dsl("name: Test\nsteps: []")

    def test_parse_invalid_trigger(self):
        with pytest.raises(ValueError, match="Unknown trigger"):
            _parse_dsl("name: Test\ntrigger: invalid\nsteps:\n  - type: code")

    def test_parse_invalid_step_type(self):
        with pytest.raises(ValueError, match="Unknown step type"):
            _parse_dsl("name: Test\nsteps:\n  - type: unknown")

    def test_parse_step_missing_type(self):
        with pytest.raises(ValueError, match="missing `type`"):
            _parse_dsl("name: Test\nsteps:\n  - snippet: hello")

    def test_parse_step_not_dict(self):
        with pytest.raises(ValueError, match="must be a mapping"):
            _parse_dsl("name: Test\nsteps:\n  - just a string")

    def test_parse_fork_mode(self):
        parsed = _parse_dsl(FORK_YAML)
        assert parsed["based_on"] == "source-workflow"
        assert len(parsed["patches"]) == 1

    def test_parse_fork_missing_patches(self):
        with pytest.raises(ValueError, match="`patches`"):
            _parse_dsl("based_on: some-slug")

    def test_parse_fork_patches_not_list(self):
        with pytest.raises(ValueError, match="`patches` must be a list"):
            _parse_dsl("based_on: some-slug\npatches: not_a_list")

    def test_parse_default_trigger(self):
        yaml_str = "name: Test\nsteps:\n  - type: code\n    snippet: pass"
        parsed = _parse_dsl(yaml_str)
        assert parsed["trigger"] == "manual"

    def test_parse_all_valid_triggers(self):
        for trigger_name in TRIGGER_TYPE_MAP:
            yaml_str = f"name: Test\ntrigger: {trigger_name}\nsteps:\n  - type: code"
            parsed = _parse_dsl(yaml_str)
            assert parsed["trigger"] == trigger_name

    def test_parse_all_valid_step_types(self):
        for step_type in STEP_TYPE_MAP:
            yaml_str = f"name: Test\nsteps:\n  - type: {step_type}"
            parsed = _parse_dsl(yaml_str)
            assert parsed["steps"][0]["type"] == step_type


# ── Build graph tests ────────────────────────────────────────────────────────


class TestBuildGraph:
    def test_linear_code_step(self):
        parsed = _parse_dsl(MINIMAL_YAML)
        model_info = (None, None, None)
        nodes, edges = _build_graph(parsed, model_info, MagicMock())

        assert len(nodes) == 2  # trigger + code
        assert nodes[0]["component_type"] == "trigger_webhook"
        assert nodes[1]["component_type"] == "code"
        assert nodes[1]["config"]["code_snippet"] == "print('hello')"
        assert nodes[1]["is_entry_point"] is True

        assert len(edges) == 1
        assert edges[0]["source_node_id"] == "trigger_webhook_1"
        assert edges[0]["target_node_id"] == "code_1"

    def test_agent_with_model_and_tools(self):
        parsed = _parse_dsl(AGENT_YAML)
        model_info = (42, "gpt-4", 0.7)
        nodes, edges = _build_graph(parsed, model_info, MagicMock())

        # trigger + agent + ai_model + calculator tool + web_search tool = 5 nodes
        assert len(nodes) == 5

        agent_node = next(n for n in nodes if n["component_type"] == "agent")
        assert agent_node["config"]["system_prompt"] == "You are a helpful assistant"
        assert agent_node["config"]["llm_credential_id"] == 42

        model_node = next(n for n in nodes if n["component_type"] == "ai_model")
        assert model_node["config"]["llm_credential_id"] == 42

        tool_nodes = [n for n in nodes if n["component_type"] in ("calculator", "web_search")]
        assert len(tool_nodes) == 2

        # Check tool edges
        tool_edges = [e for e in edges if e["edge_label"] == "tool"]
        assert len(tool_edges) == 2

        # Check model edge
        llm_edges = [e for e in edges if e["edge_label"] == "llm"]
        assert len(llm_edges) == 1

    def test_http_step(self):
        parsed = _parse_dsl(HTTP_YAML)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        http_node = next(n for n in nodes if n["component_type"] == "http_request")
        ec = http_node["config"]["extra_config"]
        assert ec["url"] == "https://example.com/api"
        assert ec["method"] == "POST"
        assert ec["timeout"] == 60

    def test_multi_step_linear_chain(self):
        yaml_str = """\
name: Multi
trigger: webhook
steps:
  - type: code
    id: step_1
  - type: code
    id: step_2
  - type: code
    id: step_3
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        # trigger + 3 code nodes
        assert len(nodes) == 4

        # 3 edges: trigger→step_1, step_1→step_2, step_2→step_3
        assert len(edges) == 3
        assert edges[0]["target_node_id"] == "step_1"
        assert edges[1]["source_node_id"] == "step_1"
        assert edges[1]["target_node_id"] == "step_2"
        assert edges[2]["source_node_id"] == "step_2"
        assert edges[2]["target_node_id"] == "step_3"

        # Only first exec step has is_entry_point
        assert nodes[1]["is_entry_point"] is True
        assert nodes[2]["is_entry_point"] is False

    def test_agent_memory_flag(self):
        yaml_str = """\
name: Memory Agent
steps:
  - type: agent
    id: mem_agent
    memory: true
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        agent_node = next(n for n in nodes if n["component_type"] == "agent")
        assert agent_node["config"]["extra_config"]["conversation_memory"] is True

    def test_auto_generated_step_ids(self):
        yaml_str = """\
name: Auto IDs
steps:
  - type: code
  - type: agent
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        # Auto IDs: code_1 and agent_2
        assert nodes[1]["node_id"] == "code_1"
        assert nodes[2]["node_id"] == "agent_2"

    def test_invalid_inline_tool(self):
        yaml_str = """\
name: Bad Tool
steps:
  - type: agent
    tools:
      - nonexistent_tool
"""
        parsed = _parse_dsl(yaml_str)
        with pytest.raises(ValueError, match="Unknown inline tool"):
            _build_graph(parsed, (None, None, None), MagicMock())

    def test_tool_with_config(self):
        yaml_str = """\
name: Tool Config
steps:
  - type: agent
    id: my_agent
    tools:
      - type: web_search
        searxng_url: http://localhost:8888
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        ws_node = next(n for n in nodes if n["component_type"] == "web_search")
        assert ws_node["config"]["extra_config"]["searxng_url"] == "http://localhost:8888"

    def test_trigger_types(self):
        for trigger_name, comp_type in TRIGGER_TYPE_MAP.items():
            yaml_str = f"name: T\ntrigger: {trigger_name}\nsteps:\n  - type: code"
            parsed = _parse_dsl(yaml_str)
            nodes, _ = _build_graph(parsed, (None, None, None), MagicMock())
            assert nodes[0]["component_type"] == comp_type

    def test_agent_step_level_model_override(self):
        yaml_str = """\
name: Override
model:
  credential_id: 1
  model_name: gpt-3.5
steps:
  - type: agent
    id: custom_agent
    model:
      credential_id: 99
      model_name: claude-opus
      temperature: 0.1
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (1, "gpt-3.5", None), MagicMock())

        agent_node = next(n for n in nodes if n["component_type"] == "agent")
        assert agent_node["config"]["llm_credential_id"] == 99
        assert agent_node["config"]["model_name"] == "claude-opus"


# ── Model resolution tests ──────────────────────────────────────────────────


class TestResolveModel:
    def test_empty_spec(self):
        assert _resolve_model({}, None, MagicMock()) == (None, None, None)

    def test_direct_credential_id(self):
        result = _resolve_model(
            {"credential_id": 42, "model_name": "gpt-4", "temperature": 0.5},
            None, MagicMock(),
        )
        assert result == (42, "gpt-4", 0.5)

    def test_inherit_from_parent_config(self):
        parent_config = SimpleNamespace(
            llm_credential_id=10, model_name="claude-3", temperature=0.3,
        )
        parent_node = SimpleNamespace(
            workflow_id=1, node_id="agent_1", component_config=parent_config,
        )
        mock_db = MagicMock()
        # No llm edges found — fallback to config directly
        mock_db.query.return_value.filter_by.return_value.all.return_value = []

        result = _resolve_model({"inherit": True}, parent_node, mock_db)
        assert result == (10, "claude-3", 0.3)

    def test_inherit_from_ai_model_edge(self):
        ai_config = SimpleNamespace(
            llm_credential_id=20, model_name="gpt-4o", temperature=0.7,
        )
        ai_node = SimpleNamespace(
            component_config=ai_config,
        )
        parent_config = SimpleNamespace(
            llm_credential_id=None, model_name=None, temperature=None,
        )
        parent_node = SimpleNamespace(
            workflow_id=1, node_id="agent_1", component_config=parent_config,
        )
        mock_edge = SimpleNamespace(source_node_id="ai_model_1")
        mock_db = MagicMock()
        # Mock edge query
        mock_db.query.return_value.filter_by.return_value.all.return_value = [mock_edge]
        # Mock ai_node lookup
        mock_db.query.return_value.filter_by.return_value.first.return_value = ai_node

        result = _resolve_model({"inherit": True}, parent_node, mock_db)
        assert result == (20, "gpt-4o", 0.7)

    def test_inherit_no_parent_raises(self):
        with pytest.raises(ValueError, match="Cannot inherit"):
            parent = SimpleNamespace(
                workflow_id=1, node_id="x", component_config=None,
            )
            mock_db = MagicMock()
            _resolve_model({"inherit": True}, parent, mock_db)

    def test_capability_with_credentials(self):
        mock_cred = SimpleNamespace(
            base_credentials_id=5, provider_type="openai_compatible",
        )
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = [mock_cred]

        result = _resolve_model({"capability": "gpt-4", "temperature": 0.5}, None, mock_db)
        # First credential returned since it's the first available
        assert result == (5, "gpt-4", 0.5)

    def test_capability_no_credentials_raises(self):
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = []

        with pytest.raises(ValueError, match="No LLM credential"):
            _resolve_model({"capability": "gpt-4"}, None, mock_db)


# ── Slug tests ───────────────────────────────────────────────────────────────


class TestSlugify:
    def test_basic(self):
        assert _slugify("My Workflow") == "my-workflow"

    def test_special_chars(self):
        assert _slugify("Hello World! @#$") == "hello-world"

    def test_multiple_spaces(self):
        assert _slugify("a   b   c") == "a-b-c"

    def test_underscores(self):
        assert _slugify("my_workflow_name") == "my-workflow-name"

    def test_empty(self):
        assert _slugify("") == ""

    def test_unique_slug_first_try(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        assert _unique_slug("My Flow", mock_db) == "my-flow"

    def test_unique_slug_collision(self):
        mock_db = MagicMock()
        # First call finds existing, second call (with -2) returns None
        mock_db.query.return_value.filter_by.return_value.first.side_effect = [
            SimpleNamespace(),  # "my-flow" exists
            None,               # "my-flow-2" doesn't exist
        ]
        assert _unique_slug("My Flow", mock_db) == "my-flow-2"

    def test_unique_slug_empty_name(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        assert _unique_slug("@#$!", mock_db) == "workflow"


# ── Fork & patch tests ──────────────────────────────────────────────────────


class TestForkPatches:
    """Test patch helpers via _compile_fork with mocked DB."""

    def _make_node_dicts(self):
        return [
            {"node_id": "trigger_chat_1", "component_type": "trigger_chat",
             "is_entry_point": False, "position_x": 0, "position_y": 200,
             "config": {"component_type": "trigger_chat", "is_active": True}},
            {"node_id": "agent_1", "component_type": "agent",
             "is_entry_point": True, "position_x": 300, "position_y": 200,
             "config": {"component_type": "agent", "system_prompt": "Original prompt"}},
            {"node_id": "code_1", "component_type": "code",
             "is_entry_point": False, "position_x": 600, "position_y": 200,
             "config": {"component_type": "code", "code_snippet": "print(1)"}},
        ]

    def _make_edge_dicts(self):
        return [
            {"source_node_id": "trigger_chat_1", "target_node_id": "agent_1",
             "edge_type": "direct", "edge_label": ""},
            {"source_node_id": "agent_1", "target_node_id": "code_1",
             "edge_type": "direct", "edge_label": ""},
        ]

    def test_patch_update_prompt(self):
        from services.dsl_compiler import _patch_update_prompt
        nodes = self._make_node_dicts()
        _patch_update_prompt(nodes, {"step_id": "agent_1", "prompt": "New prompt"})
        agent = next(n for n in nodes if n["node_id"] == "agent_1")
        assert agent["config"]["system_prompt"] == "New prompt"

    def test_patch_update_prompt_missing_step(self):
        from services.dsl_compiler import _patch_update_prompt
        nodes = self._make_node_dicts()
        with pytest.raises(ValueError, match="not found"):
            _patch_update_prompt(nodes, {"step_id": "nonexistent", "prompt": "X"})

    def test_patch_update_prompt_missing_step_id(self):
        from services.dsl_compiler import _patch_update_prompt
        with pytest.raises(ValueError, match="`step_id`"):
            _patch_update_prompt([], {})

    def test_patch_add_step_after(self):
        from services.dsl_compiler import _patch_add_step
        nodes = self._make_node_dicts()
        edges = self._make_edge_dicts()
        _patch_add_step(nodes, edges, {
            "after": "agent_1",
            "step": {"type": "code", "id": "inserted_code", "snippet": "print(2)"},
        })
        # New node added
        assert any(n["node_id"] == "inserted_code" for n in nodes)
        # Edge rewiring: agent_1 → inserted_code → code_1
        assert any(
            e["source_node_id"] == "agent_1" and e["target_node_id"] == "inserted_code"
            for e in edges
        )
        assert any(
            e["source_node_id"] == "inserted_code" and e["target_node_id"] == "code_1"
            for e in edges
        )

    def test_patch_remove_step(self):
        from services.dsl_compiler import _patch_remove_step
        nodes = self._make_node_dicts()
        edges = self._make_edge_dicts()
        _patch_remove_step(nodes, edges, {"step_id": "agent_1"})
        # Node removed
        assert not any(n["node_id"] == "agent_1" for n in nodes)
        # Edge reconnected: trigger → code_1
        assert any(
            e["source_node_id"] == "trigger_chat_1" and e["target_node_id"] == "code_1"
            for e in edges
        )

    def test_patch_add_tool(self):
        from services.dsl_compiler import _patch_add_tool
        nodes = self._make_node_dicts()
        edges = self._make_edge_dicts()
        _patch_add_tool(nodes, edges, {
            "step_id": "agent_1",
            "tool": "calculator",
        })
        tool_nodes = [n for n in nodes if n["component_type"] == "calculator"]
        assert len(tool_nodes) == 1
        tool_edges = [e for e in edges if e["edge_label"] == "tool"]
        assert len(tool_edges) == 1

    def test_patch_remove_tool(self):
        from services.dsl_compiler import _patch_remove_tool
        nodes = self._make_node_dicts()
        nodes.append({
            "node_id": "calculator_agent_1_1", "component_type": "calculator",
            "is_entry_point": False, "position_x": 400, "position_y": 400,
            "config": {},
        })
        edges = self._make_edge_dicts()
        edges.append({
            "source_node_id": "calculator_agent_1_1", "target_node_id": "agent_1",
            "edge_type": "direct", "edge_label": "tool",
        })
        _patch_remove_tool(nodes, edges, {"tool_node_id": "calculator_agent_1_1"})
        assert not any(n["node_id"] == "calculator_agent_1_1" for n in nodes)
        assert not any(e["edge_label"] == "tool" for e in edges)

    def test_patch_update_config(self):
        from services.dsl_compiler import _patch_update_config
        nodes = self._make_node_dicts()
        _patch_update_config(nodes, {
            "step_id": "agent_1",
            "config": {"conversation_memory": True, "timeout": 60},
        })
        agent = next(n for n in nodes if n["node_id"] == "agent_1")
        assert agent["config"]["extra_config"]["conversation_memory"] is True
        assert agent["config"]["extra_config"]["timeout"] == 60

    def test_patch_unknown_action(self):
        from services.dsl_compiler import _compile_fork
        mock_db = MagicMock()
        source_wf = SimpleNamespace(
            id=1, name="Source", slug="source", description="", tags=[],
        )
        mock_db.query.return_value.filter_by.return_value.first.return_value = source_wf
        mock_db.query.return_value.filter_by.return_value.all.return_value = []

        parsed = {
            "based_on": "source",
            "patches": [{"action": "explode"}],
        }
        with pytest.raises(ValueError, match="Unknown patch action"):
            _compile_fork(parsed, 1, mock_db)

    def test_patch_not_dict(self):
        from services.dsl_compiler import _compile_fork
        mock_db = MagicMock()
        source_wf = SimpleNamespace(
            id=1, name="Source", slug="source", description="", tags=[],
        )
        mock_db.query.return_value.filter_by.return_value.first.return_value = source_wf
        mock_db.query.return_value.filter_by.return_value.all.return_value = []

        parsed = {
            "based_on": "source",
            "patches": ["not a dict"],
        }
        with pytest.raises(ValueError, match="must be a mapping"):
            _compile_fork(parsed, 1, mock_db)


# ── compile_dsl integration (mocked DB) ─────────────────────────────────────


class TestCompileDslMocked:
    def test_compile_returns_error_on_bad_yaml(self):
        result = compile_dsl("{{bad", 1, MagicMock())
        assert result["success"] is False
        assert "Invalid YAML" in result["error"]

    def test_compile_returns_error_on_missing_name(self):
        result = compile_dsl("steps:\n  - type: code", 1, MagicMock())
        assert result["success"] is False

    def test_fork_missing_source(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        result = compile_dsl(
            "based_on: nonexistent\npatches:\n  - action: update_prompt\n    step_id: x\n    prompt: y",
            1, mock_db,
        )
        assert result["success"] is False
        assert "not found" in result["error"]
