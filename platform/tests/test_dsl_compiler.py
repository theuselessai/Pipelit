"""Unit tests for the DSL compiler — parsing, graph building, model resolution, fork & patch."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.dsl_compiler import (
    MODEL_PREFERENCE_TABLE,
    STEP_TYPE_MAP,
    TOOL_TYPE_MAP,
    TRIGGER_TYPE_MAP,
    _build_graph,
    _build_step_config,
    _discover_model,
    _parse_dsl,
    _parse_over_expression,
    _resolve_model,
    _resolve_tool_inherit,
    _score_model,
    _slugify,
    _unique_slug,
    compile_dsl,
    validate_dsl,
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

    def test_parse_duplicate_step_ids(self):
        yaml_str = (
            "name: Test\n"
            "steps:\n"
            "  - type: code\n"
            "    id: my_step\n"
            "    snippet: pass\n"
            "  - type: code\n"
            "    id: my_step\n"
            "    snippet: pass\n"
        )
        with pytest.raises(ValueError, match="Duplicate step ID 'my_step'"):
            _parse_dsl(yaml_str)

    def test_parse_duplicate_auto_ids(self):
        """Two code steps without explicit IDs get auto-IDs code_1/code_2 — no collision."""
        yaml_str = "name: Test\nsteps:\n  - type: code\n  - type: code"
        parsed = _parse_dsl(yaml_str)
        assert len(parsed["steps"]) == 2


# ── Build graph tests ────────────────────────────────────────────────────────


class TestBuildGraph:
    def test_linear_code_step(self):
        parsed = _parse_dsl(MINIMAL_YAML)
        model_info = (None, None, None)
        nodes, edges = _build_graph(parsed, model_info, MagicMock())

        assert len(nodes) == 2  # trigger + code
        assert nodes[0]["component_type"] == "trigger_webhook"
        assert nodes[1]["component_type"] == "code"
        assert nodes[1]["config"]["extra_config"]["code"] == "print('hello')"
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
        assert edges[0]["source_node_id"] == "trigger_webhook_1"
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

    def test_null_inline_tool_raises(self):
        yaml_str = """\
name: Null Tool
steps:
  - type: agent
    id: my_agent
    tools:
      - null
"""
        parsed = _parse_dsl(yaml_str)
        with pytest.raises(ValueError, match="must be a string or mapping"):
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

    def test_capability_matches_provider_type(self):
        """When capability matches provider_type, prefer that credential."""
        cred_openai = SimpleNamespace(base_credentials_id=5, provider_type="openai_compatible")
        cred_anthropic = SimpleNamespace(base_credentials_id=9, provider_type="anthropic")
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = [cred_openai, cred_anthropic]

        result = _resolve_model({"capability": "anthropic"}, None, mock_db)
        assert result == (9, "anthropic", None)

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
             "config": {"component_type": "code", "extra_config": {"code": "print(1)", "language": "python"}}},
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

    def test_patch_update_prompt_snippet(self):
        from services.dsl_compiler import _patch_update_prompt
        nodes = self._make_node_dicts()
        _patch_update_prompt(nodes, {"step_id": "code_1", "snippet": "print(2)"})
        code = next(n for n in nodes if n["node_id"] == "code_1")
        assert code["config"]["extra_config"]["code"] == "print(2)"

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
        # Verify added code step uses extra_config
        inserted = next(n for n in nodes if n["node_id"] == "inserted_code")
        assert inserted["config"]["extra_config"]["code"] == "print(2)"

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


# ── Switch step tests ────────────────────────────────────────────────────────


class TestSwitchStep:
    def test_switch_basic_rules(self):
        yaml_str = """\
name: Switch Test
steps:
  - type: switch
    id: my_switch
    rules:
      - field: category
        operator: equals
        value: A
        route: handle_a
      - field: category
        operator: equals
        value: B
        route: handle_b
  - type: code
    id: handle_a
    snippet: "print('A')"
  - type: code
    id: handle_b
    snippet: "print('B')"
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        switch_node = next(n for n in nodes if n["component_type"] == "switch")
        rules = switch_node["config"]["extra_config"]["rules"]
        assert len(rules) == 2
        assert rules[0]["id"] == "handle_a"
        assert rules[0]["field"] == "category"

    def test_switch_conditional_edges(self):
        yaml_str = """\
name: Switch Edges
steps:
  - type: switch
    id: sw
    rules:
      - field: x
        operator: equals
        value: "1"
        route: branch_a
      - field: x
        operator: equals
        value: "2"
        route: branch_b
  - type: code
    id: branch_a
  - type: code
    id: branch_b
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        cond_edges = [e for e in edges if e["edge_type"] == "conditional"]
        assert len(cond_edges) == 2
        assert any(e["condition_value"] == "branch_a" and e["target_node_id"] == "branch_a" for e in cond_edges)
        assert any(e["condition_value"] == "branch_b" and e["target_node_id"] == "branch_b" for e in cond_edges)

    def test_switch_default_fallback(self):
        yaml_str = """\
name: Switch Default
steps:
  - type: switch
    id: sw
    rules:
      - field: x
        operator: equals
        value: "1"
        route: branch_a
    default: fallback
  - type: code
    id: branch_a
  - type: code
    id: fallback
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        switch_node = next(n for n in nodes if n["component_type"] == "switch")
        assert switch_node["config"]["extra_config"]["enable_fallback"] is True

        other_edges = [e for e in edges if e.get("condition_value") == "__other__"]
        assert len(other_edges) == 1
        assert other_edges[0]["target_node_id"] == "fallback"

    def test_switch_claimed_targets_skip_linear_edge(self):
        yaml_str = """\
name: Switch Skip
steps:
  - type: switch
    id: sw
    rules:
      - field: x
        operator: equals
        value: "1"
        route: target_a
  - type: code
    id: target_a
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        # target_a should NOT have a direct linear edge from switch (switch uses conditional)
        # and target_a should not have a linear edge from trigger since it's claimed
        direct_edges_to_target = [
            e for e in edges
            if e["target_node_id"] == "target_a" and e["edge_type"] == "direct" and e["edge_label"] == ""
        ]
        assert len(direct_edges_to_target) == 0

    def test_switch_breaks_linear_chain(self):
        yaml_str = """\
name: Switch Chain Break
steps:
  - type: code
    id: before
  - type: switch
    id: sw
    rules:
      - field: x
        operator: equals
        value: "1"
        route: target_a
  - type: code
    id: target_a
  - type: code
    id: after
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        # Switch breaks the chain: no direct linear edge from switch → target_a
        # (target_a is reached via conditional edge only)
        direct_sw_to_target = [
            e for e in edges
            if e["source_node_id"] == "sw" and e["target_node_id"] == "target_a"
            and e["edge_type"] == "direct" and e["edge_label"] == ""
        ]
        assert len(direct_sw_to_target) == 0

        # But after target_a resumes the chain: target_a → after
        edges_to_after = [
            e for e in edges
            if e["source_node_id"] == "target_a" and e["target_node_id"] == "after"
        ]
        assert len(edges_to_after) == 1


# ── Loop step tests ──────────────────────────────────────────────────────────


class TestLoopStep:
    def test_loop_body_edges(self):
        yaml_str = """\
name: Loop Test
steps:
  - type: loop
    id: my_loop
    over: "{{ data_source.items }}"
    body:
      - type: code
        id: process_item
        snippet: "print(item)"
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        loop_node = next(n for n in nodes if n["component_type"] == "loop")
        assert loop_node["config"]["extra_config"]["source_node"] == "data_source"
        assert loop_node["config"]["extra_config"]["field"] == "items"

        # Check loop_body edge
        body_edges = [e for e in edges if e["edge_label"] == "loop_body"]
        assert len(body_edges) == 1
        assert body_edges[0]["source_node_id"] == "my_loop"
        assert body_edges[0]["target_node_id"] == "process_item"

        # Check loop_return edge
        return_edges = [e for e in edges if e["edge_label"] == "loop_return"]
        assert len(return_edges) == 1
        assert return_edges[0]["source_node_id"] == "process_item"
        assert return_edges[0]["target_node_id"] == "my_loop"

    def test_loop_multi_body_steps(self):
        yaml_str = """\
name: Loop Multi Body
steps:
  - type: loop
    id: my_loop
    over: source.items
    body:
      - type: code
        id: step_a
      - type: code
        id: step_b
      - type: code
        id: step_c
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        # loop_body: loop → step_a
        body_edges = [e for e in edges if e["edge_label"] == "loop_body"]
        assert body_edges[0]["target_node_id"] == "step_a"

        # step_a → step_b, step_b → step_c (direct body edges)
        assert any(e["source_node_id"] == "step_a" and e["target_node_id"] == "step_b" for e in edges)
        assert any(e["source_node_id"] == "step_b" and e["target_node_id"] == "step_c" for e in edges)

        # loop_return: step_c → loop
        return_edges = [e for e in edges if e["edge_label"] == "loop_return"]
        assert return_edges[0]["source_node_id"] == "step_c"

    def test_loop_empty_body_raises(self):
        yaml_str = """\
name: Empty Loop
steps:
  - type: loop
    id: my_loop
    over: source.items
    body: []
"""
        parsed = _parse_dsl(yaml_str)
        with pytest.raises(ValueError, match="non-empty `body`"):
            _build_graph(parsed, (None, None, None), MagicMock())

    def test_loop_continues_chain(self):
        yaml_str = """\
name: Loop Chain
steps:
  - type: loop
    id: my_loop
    over: source.items
    body:
      - type: code
        id: body_step
  - type: code
    id: after_loop
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        # Loop continues chain: my_loop → after_loop
        assert any(
            e["source_node_id"] == "my_loop" and e["target_node_id"] == "after_loop"
            and e["edge_label"] == ""
            for e in edges
        )

    def test_loop_body_positions(self):
        yaml_str = """\
name: Loop Positions
steps:
  - type: loop
    id: my_loop
    over: source.items
    body:
      - type: code
        id: body_a
      - type: code
        id: body_b
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        body_a = next(n for n in nodes if n["node_id"] == "body_a")
        body_b = next(n for n in nodes if n["node_id"] == "body_b")
        # Body nodes should be below loop (y=350) and spread horizontally
        assert body_a["position_y"] == 350
        assert body_b["position_y"] == 350
        assert body_b["position_x"] > body_a["position_x"]


# ── Over expression parsing tests ────────────────────────────────────────────


class TestParseOverExpression:
    def test_jinja2_expression(self):
        assert _parse_over_expression("{{ node_id.field }}") == ("node_id", "field")

    def test_plain_expression(self):
        assert _parse_over_expression("node_id.field") == ("node_id", "field")

    def test_no_field(self):
        assert _parse_over_expression("node_id") == ("node_id", "output")

    def test_empty(self):
        assert _parse_over_expression("") == ("", "")

    def test_jinja2_no_spaces(self):
        assert _parse_over_expression("{{node.items}}") == ("node", "items")


# ── Workflow step tests ──────────────────────────────────────────────────────


class TestWorkflowStep:
    def test_workflow_config(self):
        yaml_str = """\
name: Workflow Step Test
steps:
  - type: workflow
    id: call_sub
    workflow: my-subworkflow
    payload:
      key: value
"""
        parsed = _parse_dsl(yaml_str)
        mock_db = MagicMock()
        # Mock subworkflow lookup
        sub_wf = SimpleNamespace(id=42)
        mock_db.query.return_value.filter_by.return_value.first.return_value = sub_wf

        nodes, edges = _build_graph(parsed, (None, None, None), mock_db)

        wf_node = next(n for n in nodes if n["component_type"] == "workflow")
        assert wf_node["config"]["extra_config"]["target_workflow"] == "my-subworkflow"
        assert wf_node["config"]["extra_config"]["input_mapping"] == {"key": "value"}
        assert wf_node["subworkflow_id"] == 42

    def test_workflow_subworkflow_not_found(self):
        yaml_str = """\
name: WF Missing
steps:
  - type: workflow
    id: call_sub
    workflow: nonexistent
"""
        parsed = _parse_dsl(yaml_str)
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        nodes, edges = _build_graph(parsed, (None, None, None), mock_db)

        wf_node = next(n for n in nodes if n["component_type"] == "workflow")
        # No subworkflow_id set when not found
        assert "subworkflow_id" not in wf_node


# ── Human step tests ─────────────────────────────────────────────────────────


class TestHumanStep:
    def test_human_config(self):
        yaml_str = """\
name: Human Step Test
steps:
  - type: human
    id: confirm
    message: "Are you sure?"
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        human_node = next(n for n in nodes if n["component_type"] == "human_confirmation")
        assert human_node["config"]["extra_config"]["prompt"] == "Are you sure?"
        assert human_node["interrupt_before"] is True

    def test_human_linear_chain(self):
        yaml_str = """\
name: Human Chain
steps:
  - type: code
    id: before
  - type: human
    id: confirm
    message: "OK?"
  - type: code
    id: after
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        # Standard linear edges: before → confirm → after
        assert any(e["source_node_id"] == "before" and e["target_node_id"] == "confirm" for e in edges)
        assert any(e["source_node_id"] == "confirm" and e["target_node_id"] == "after" for e in edges)


# ── Transform step tests ─────────────────────────────────────────────────────


class TestTransformStep:
    def test_transform_maps_to_code(self):
        yaml_str = """\
name: Transform Test
steps:
  - type: transform
    id: fmt
    template: "Hello {name}"
"""
        parsed = _parse_dsl(yaml_str)
        nodes, edges = _build_graph(parsed, (None, None, None), MagicMock())

        # Transform maps to code component
        transform_node = next(n for n in nodes if n["node_id"] == "fmt")
        assert transform_node["component_type"] == "code"
        code = transform_node["config"]["extra_config"]["code"]
        assert "Hello {name}" in code
        assert transform_node["config"]["extra_config"]["language"] == "python"


# ── Discover model tests ─────────────────────────────────────────────────────


class TestDiscoverModel:
    def test_cheapest_preference(self):
        mock_cred = SimpleNamespace(
            base_credentials_id=1,
            provider_type="anthropic",
            api_key="test",
            base_url=None,
        )
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = [mock_cred]

        cred_id, model_name, temp = _discover_model("cheapest", 0.5, mock_db)
        assert cred_id == 1
        assert model_name is not None
        assert temp == 0.5
        # Cheapest anthropic model should be haiku (lowest cost)
        assert "haiku" in model_name.lower()

    def test_most_capable_preference(self):
        mock_cred = SimpleNamespace(
            base_credentials_id=1,
            provider_type="anthropic",
            api_key="test",
            base_url=None,
        )
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = [mock_cred]

        cred_id, model_name, temp = _discover_model("most_capable", None, mock_db)
        assert cred_id == 1
        # Most capable anthropic model should be opus
        assert "opus" in model_name.lower()

    def test_fastest_preference(self):
        mock_cred = SimpleNamespace(
            base_credentials_id=1,
            provider_type="anthropic",
            api_key="test",
            base_url=None,
        )
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = [mock_cred]

        cred_id, model_name, temp = _discover_model("fastest", None, mock_db)
        assert cred_id == 1
        # Fastest anthropic model should be haiku
        assert "haiku" in model_name.lower()

    def test_no_credentials_raises(self):
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = []

        with pytest.raises(ValueError, match="No LLM credentials"):
            _discover_model("cheapest", None, mock_db)

    def test_score_model_cheapest(self):
        score_cheap = _score_model("gpt-3.5-turbo-latest", "cheapest")
        score_expensive = _score_model("gpt-4-turbo-2024", "cheapest")
        assert score_cheap > score_expensive  # Cheaper model scores higher

    def test_score_model_most_capable(self):
        score_capable = _score_model("claude-opus-4-0", "most_capable")
        score_less = _score_model("claude-3-haiku-20240307", "most_capable")
        assert score_capable > score_less

    def test_score_model_unknown_returns_zero(self):
        score = _score_model("totally-unknown-model", "cheapest")
        assert score == 0.0

    def test_discover_via_resolve_model(self):
        mock_cred = SimpleNamespace(
            base_credentials_id=1,
            provider_type="anthropic",
            api_key="test",
            base_url=None,
        )
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = [mock_cred]

        result = _resolve_model({"discover": True, "preference": "cheapest"}, None, mock_db)
        assert result[0] == 1
        assert result[1] is not None


# ── Tool inherit tests ───────────────────────────────────────────────────────


class TestToolInherit:
    def _make_parent_with_tool(self):
        """Create mock parent node with a connected web_search tool."""
        parent_node = SimpleNamespace(
            workflow_id=1, node_id="agent_1",
        )
        tool_config = SimpleNamespace(
            extra_config={"searxng_url": "http://localhost:8888"},
        )
        tool_node = SimpleNamespace(
            component_type="web_search",
            component_config=tool_config,
        )
        mock_edge = SimpleNamespace(source_node_id="web_search_1")
        return parent_node, tool_node, mock_edge

    def test_resolves_from_parent(self):
        parent_node, tool_node, mock_edge = self._make_parent_with_tool()
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = [mock_edge]
        mock_db.query.return_value.filter_by.return_value.first.return_value = tool_node

        result = _resolve_tool_inherit("web_search", "searxng_url", parent_node, mock_db)
        assert result == "http://localhost:8888"

    def test_no_parent_raises(self):
        with pytest.raises(ValueError, match="no parent node"):
            _resolve_tool_inherit("web_search", "searxng_url", None, MagicMock())

    def test_no_matching_tool_raises(self):
        parent_node = SimpleNamespace(workflow_id=1, node_id="agent_1")
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = []

        with pytest.raises(ValueError, match="No matching tool"):
            _resolve_tool_inherit("web_search", "searxng_url", parent_node, mock_db)

    def test_no_matching_key_raises(self):
        parent_node = SimpleNamespace(workflow_id=1, node_id="agent_1")
        tool_config = SimpleNamespace(extra_config={"other_key": "value"})
        tool_node = SimpleNamespace(
            component_type="web_search", component_config=tool_config,
        )
        mock_edge = SimpleNamespace(source_node_id="web_search_1")
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = [mock_edge]
        mock_db.query.return_value.filter_by.return_value.first.return_value = tool_node

        with pytest.raises(ValueError, match="no key"):
            _resolve_tool_inherit("web_search", "searxng_url", parent_node, mock_db)


# ── Validate DSL tests ───────────────────────────────────────────────────────


class TestValidateDsl:
    def test_valid_dsl_returns_counts(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        result = validate_dsl(MINIMAL_YAML, mock_db)
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["node_count"] == 2  # trigger + code
        assert result["edge_count"] == 1

    def test_invalid_yaml_returns_errors(self):
        result = validate_dsl("{{bad yaml", MagicMock())
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert "Parse error" in result["errors"][0]

    def test_missing_steps_detected(self):
        result = validate_dsl("name: Test\ntrigger: webhook", MagicMock())
        assert result["valid"] is False
        assert any("steps" in e for e in result["errors"])

    def test_model_error_still_builds_graph(self):
        yaml_str = """\
name: Model Error
model:
  capability: nonexistent
steps:
  - type: code
    snippet: pass
"""
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = []
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        result = validate_dsl(yaml_str, mock_db)
        # Model error, but graph can still be partially built
        assert result["valid"] is False
        assert any("Model resolution" in e for e in result["errors"])
        # Graph was still built with fallback model_info
        assert result["node_count"] >= 2

    def test_fork_mode_validates_source(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        yaml_str = "based_on: nonexistent\npatches:\n  - action: update_prompt\n    step_id: x\n    prompt: y"
        result = validate_dsl(yaml_str, mock_db)
        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])


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
