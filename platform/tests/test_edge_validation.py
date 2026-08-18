"""Tests for edge validation — type compatibility and required input checks."""

from __future__ import annotations

import pytest

from schemas.node_types import DataType
import schemas.node_type_defs  # noqa: F401 — register node types
from validation.edges import EdgeValidator


class TestTypeCompatibility:
    """Test EdgeValidator.is_type_compatible()."""

    def test_same_type_always_compatible(self):
        for dt in DataType:
            assert EdgeValidator.is_type_compatible(dt, dt)

    def test_any_target_accepts_all(self):
        for dt in DataType:
            assert EdgeValidator.is_type_compatible(dt, DataType.ANY)

    def test_any_source_accepted_everywhere(self):
        for dt in DataType:
            assert EdgeValidator.is_type_compatible(DataType.ANY, dt)

    def test_string_to_message(self):
        assert EdgeValidator.is_type_compatible(DataType.STRING, DataType.MESSAGE)

    def test_string_to_messages(self):
        assert EdgeValidator.is_type_compatible(DataType.STRING, DataType.MESSAGES)

    def test_message_to_messages(self):
        assert EdgeValidator.is_type_compatible(DataType.MESSAGE, DataType.MESSAGES)

    def test_number_to_string_incompatible(self):
        assert not EdgeValidator.is_type_compatible(DataType.NUMBER, DataType.STRING)

    def test_boolean_to_string_incompatible(self):
        assert not EdgeValidator.is_type_compatible(DataType.BOOLEAN, DataType.STRING)

    def test_object_to_string_incompatible(self):
        assert not EdgeValidator.is_type_compatible(DataType.OBJECT, DataType.STRING)

    def test_array_to_object_incompatible(self):
        assert not EdgeValidator.is_type_compatible(DataType.ARRAY, DataType.OBJECT)

    def test_image_to_string_incompatible(self):
        assert not EdgeValidator.is_type_compatible(DataType.IMAGE, DataType.STRING)

    def test_file_to_message_incompatible(self):
        assert not EdgeValidator.is_type_compatible(DataType.FILE, DataType.MESSAGE)

    def test_messages_to_message_incompatible(self):
        assert not EdgeValidator.is_type_compatible(DataType.MESSAGES, DataType.MESSAGE)


# ─────────────────────────────────────────────────────────────────────────────
# Everything below exercises per-NODE validation: validate_edge takes node
# objects, because a binary node's output ports are derived from its configured
# operation, not from its type. TestTypeCompatibility above stays byte-identical
# to commit 4dd15d5 — it is the evidence that compatibility semantics did not
# drift while these call sites were rewritten.
# ─────────────────────────────────────────────────────────────────────────────

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import schemas.binary_catalogs as binary_catalogs
from schemas.node_types import (
    NODE_TYPE_REGISTRY,
    NodeTypeSpec,
    PortDefinition,
    get_node_type,
)
from services import plugins as plugins_module
from services.plugins import Registration, resolve, tree_checksum, tree_fingerprint
from validation.edges import UNRESOLVED_PORTS, _binary_operation_errors


def _node(component_type, node_id="n", **extra):
    """A stub with the two attributes validate_edge consults."""
    return SimpleNamespace(
        node_id=node_id,
        component_type=component_type,
        component_config=SimpleNamespace(extra_config=extra),
    )


def _demo_catalog(binary="demo-bin"):
    return {
        "protocol": 1,
        "binary": binary,
        "version": "1.0.0",
        "operations": [
            {
                "id": "things.doThing",
                "domain": "things",
                "summary": "Do the thing.",
                "session": {"required": True},
                "params": {"type": "object", "required": ["n"],
                           "properties": {"n": {"type": "string"}}},
                "outputs": [
                    {"name": "count", "type": "number", "description": ""},
                    {"name": "thing_id", "type": "string", "description": ""},
                ],
                "timeout_default_s": 5,
            },
            {
                "id": "things.listThings",
                "domain": "things",
                "summary": "List the things.",
                "session": {"required": False},
                "params": {"type": "object", "properties": {}},
                "outputs": [{"name": "things", "type": "array", "description": ""}],
                "timeout_default_s": 5,
            },
        ],
    }


@pytest.fixture
def binary_catalog_dir(tmp_path, monkeypatch):
    """A catalog directory holding demo-bin's catalog (invented fixture —
    catalogs are gitignored, so tests must not depend on a real one)."""
    catalogs = tmp_path / "catalogs"
    catalogs.mkdir()
    (catalogs / "demo-bin.json").write_text(json.dumps(_demo_catalog()))
    monkeypatch.setattr(binary_catalogs, "CATALOG_DIR", catalogs)
    return catalogs


@pytest.fixture
def registered_binaries(tmp_path, monkeypatch):
    """Two REGISTERED fake binaries, demo-bin and gone-bin, with catalogs.

    Registration (plugin dir + registration record) is what the write-time
    allowlist checks; the catalog file is what the validator reads. gone-bin
    exists so a test can register it, save nodes naming it, and then remove it
    — the lifecycle that leaves a saved node with an unresolvable binary.
    """
    root = tmp_path / "plugins"
    registrations = tmp_path / "registrations"
    catalogs = tmp_path / "catalogs"
    for d in (root, registrations, catalogs):
        d.mkdir()
    monkeypatch.setattr(plugins_module, "PLUGIN_DIR", root)
    monkeypatch.setattr(plugins_module, "REGISTRATION_DIR", registrations)
    monkeypatch.setattr(binary_catalogs, "CATALOG_DIR", catalogs)

    for name in ("demo-bin", "gone-bin"):
        directory = root / name
        directory.mkdir()
        (directory / "plugin.json").write_text(json.dumps({"exec": ["python3", "bin.py"]}))
        p = resolve(name, root)
        plugins_module.write_registration(Registration(
            binary=name, plugin=name, argv=p.argv,
            checksum=tree_checksum(directory),
            fingerprint=tree_fingerprint(directory),
            catalog_hash="sha256:" + "1" * 64,
            registered_at="2026-08-18T00:00:00+00:00",
        ))
        (catalogs / f"{name}.json").write_text(json.dumps(_demo_catalog(name)))
    return tmp_path


def _unregister(registered_binaries, name):
    """Remove a binary's catalog and registration — the saved nodes remain."""
    (registered_binaries / "catalogs" / f"{name}.json").unlink()
    (registered_binaries / "registrations" / f"{name}.plugin.json").unlink()


@pytest.fixture
def app(db):
    """A test FastAPI app with the DB dependency overridden."""
    from database import get_db
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
def auth_client(app, api_key):
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


class TestValidateEdge:
    """Test EdgeValidator.validate_edge() — node objects in, error strings out."""

    def test_compatible_direct_edge(self):
        errors = EdgeValidator.validate_edge(_node("trigger_manual"), _node("switch"))
        assert errors == []

    def test_incompatible_types(self):
        # filter outputs ARRAY, agent expects MESSAGES
        errors = EdgeValidator.validate_edge(_node("filter"), _node("agent"))
        assert len(errors) == 1
        assert "Type mismatch" in errors[0]

    def test_unknown_source_type_allows(self):
        errors = EdgeValidator.validate_edge(_node("unknown_type"), _node("agent"))
        assert errors == []

    def test_unknown_target_type_allows(self):
        errors = EdgeValidator.validate_edge(_node("trigger_manual"), _node("unknown_type"))
        assert errors == []

    def test_sub_component_model_handle_valid(self):
        errors = EdgeValidator.validate_edge(_node("ai_model"), _node("agent"), target_handle="model")
        assert errors == []

    def test_sub_component_tools_handle_valid(self):
        errors = EdgeValidator.validate_edge(_node("run_command"), _node("agent"), target_handle="tools")
        assert errors == []

    def test_sub_component_memory_as_tool_valid(self):
        errors = EdgeValidator.validate_edge(_node("memory_read"), _node("agent"), target_handle="tools")
        assert errors == []

    def test_sub_component_output_parser_valid(self):
        errors = EdgeValidator.validate_edge(_node("output_parser"), _node("categorizer"), target_handle="output_parser")
        assert errors == []

    def test_sub_component_handle_on_wrong_target(self):
        # switch does not accept model connections
        errors = EdgeValidator.validate_edge(_node("ai_model"), _node("switch"), target_handle="model")
        assert len(errors) == 1
        assert "does not accept" in errors[0]

    def test_sub_component_tools_on_non_tool_target(self):
        # switch does not accept tool connections
        errors = EdgeValidator.validate_edge(_node("run_command"), _node("switch"), target_handle="tools")
        assert len(errors) == 1
        assert "does not accept" in errors[0]


class TestBinaryPortResolution:
    """Binary nodes' output ports resolve per node, from (binary, operation).

    Unresolvable ports are a DISTINCTLY IDENTIFIABLE error class
    (code=UNRESOLVED_PORTS) naming which failure it is — never the silent
    empty list the forward-compat leniency returns for unknown types.
    """

    def test_ports_come_from_the_configured_operation(self, binary_catalog_dir):
        ports, issue = EdgeValidator._output_ports(
            _node("binary_op", binary="demo-bin", operation="things.doThing"))
        assert issue is None
        assert [p.name for p in ports] == ["count", "thing_id"]

    def test_resolvable_type_mismatch_is_still_refused(self, binary_catalog_dir):
        # things.doThing's first output is NUMBER; agent expects MESSAGES
        errors = EdgeValidator.validate_edge(
            _node("binary_op", binary="demo-bin", operation="things.doThing"),
            _node("agent"))
        assert len(errors) == 1
        assert "Type mismatch" in errors[0]

    def test_resolvable_compatible_edge_passes(self, binary_catalog_dir):
        errors = EdgeValidator.validate_edge(
            _node("binary_op", binary="demo-bin", operation="things.listThings"),
            _node("switch"))
        assert errors == []

    def test_no_binary_set(self, binary_catalog_dir):
        errors = EdgeValidator.validate_edge(_node("binary_op"), _node("switch"))
        assert len(errors) == 1
        assert getattr(errors[0], "code", None) == UNRESOLVED_PORTS
        assert "no binary set" in errors[0]

    def test_no_operation_selected(self, binary_catalog_dir):
        errors = EdgeValidator.validate_edge(
            _node("binary_op", binary="demo-bin"), _node("switch"))
        assert len(errors) == 1
        assert getattr(errors[0], "code", None) == UNRESOLVED_PORTS
        assert "no operation selected" in errors[0]

    def test_unknown_operation(self, binary_catalog_dir):
        errors = EdgeValidator.validate_edge(
            _node("binary_op", binary="demo-bin", operation="things.nope"), _node("switch"))
        assert len(errors) == 1
        assert getattr(errors[0], "code", None) == UNRESOLVED_PORTS
        assert "does not offer operation 'things.nope'" in errors[0]

    def test_unregistered_binary(self, binary_catalog_dir):
        errors = EdgeValidator.validate_edge(
            _node("binary_op", binary="ghost-bin", operation="things.doThing"), _node("switch"))
        assert len(errors) == 1
        assert getattr(errors[0], "code", None) == UNRESOLVED_PORTS
        assert "has no registered catalog here" in errors[0]

    def test_binary_auth_ports_come_from_the_verb_table(self):
        ports, issue = EdgeValidator._output_ports(
            _node("binary_auth", binary="demo-bin", operation="auth.sessionList"))
        assert issue is None
        assert [p.name for p in ports] == ["sessions"]

    def test_binary_auth_unknown_verb(self):
        errors = EdgeValidator.validate_edge(
            _node("binary_auth", binary="demo-bin", operation="auth.teleport"), _node("switch"))
        assert len(errors) == 1
        assert getattr(errors[0], "code", None) == UNRESOLVED_PORTS
        assert "auth.teleport" in errors[0]

    def test_binary_auth_no_operation(self):
        errors = EdgeValidator.validate_edge(
            _node("binary_auth", binary="demo-bin"), _node("switch"))
        assert len(errors) == 1
        assert getattr(errors[0], "code", None) == UNRESOLVED_PORTS

    def test_unknown_nonbinary_type_is_not_tagged(self):
        """Forward compatibility survives: a genuinely unknown type is allowed
        silently; only binary nodes get the unresolved_ports error class."""
        ports, issue = EdgeValidator._output_ports(_node("mystery_type"))
        assert ports is None and issue is None

    def test_workflow_edge_report_names_the_edge_and_keeps_the_code(
            self, db, workflow, binary_catalog_dir):
        """/validate/ reaches the condition through validate_workflow_edges, so
        the wrapped entry must keep both the edge and the machine code."""
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        cc_bin = BaseComponentConfig(component_type="binary_op",
                                     extra_config={"binary": "demo-bin"})
        db.add(cc_bin)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="bin_1",
                            component_type="binary_op", component_config_id=cc_bin.id))
        cc_switch = BaseComponentConfig(component_type="switch", extra_config={"rules": []})
        db.add(cc_switch)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="switch_1",
                            component_type="switch", component_config_id=cc_switch.id))
        db.add(WorkflowEdge(workflow_id=workflow.id, source_node_id="bin_1",
                            target_node_id="switch_1", edge_type="direct"))
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        matching = [e for e in errors if e.startswith("Edge bin_1 → switch_1:")]
        assert len(matching) == 1
        assert "no operation selected" in matching[0]
        assert getattr(matching[0], "code", None) == UNRESOLVED_PORTS


def _clashing_catalog(binary="clash-bin"):
    """ONE domain, TWO operations declaring the SAME output port name with
    DIFFERENT types — exactly the shape that used to make the now-deleted
    `_ports_for()` union widen the port to ANY across the whole domain."""
    return {
        "protocol": 1,
        "binary": binary,
        "version": "1.0.0",
        "operations": [
            {
                "id": "things.readLabel",
                "domain": "things",
                "summary": "Read a thing's label.",
                "session": {"required": False},
                "params": {"type": "object", "properties": {}},
                "outputs": [{"name": "x", "type": "string", "description": ""}],
                "timeout_default_s": 5,
            },
            {
                "id": "things.countThings",
                "domain": "things",
                "summary": "Count the things.",
                "session": {"required": False},
                "params": {"type": "object", "properties": {}},
                "outputs": [{"name": "x", "type": "number", "description": ""}],
                "timeout_default_s": 5,
            },
        ],
    }


@pytest.fixture
def clashing_catalog_dir(tmp_path, monkeypatch):
    """A catalog directory holding clash-bin's catalog (invented fixture —
    catalogs are gitignored, so tests must not depend on a real one)."""
    catalogs = tmp_path / "catalogs"
    catalogs.mkdir()
    (catalogs / "clash-bin.json").write_text(json.dumps(_clashing_catalog()))
    monkeypatch.setattr(binary_catalogs, "CATALOG_DIR", catalogs)
    return catalogs


@pytest.fixture
def number_sink(monkeypatch):
    """A fixture target type whose input accepts NUMBER but not STRING.

    No built-in node type has a NUMBER first input, and the regression below
    needs one: a target that ANY would satisfy but STRING must not."""
    monkeypatch.setitem(NODE_TYPE_REGISTRY, "number_sink", NodeTypeSpec(
        component_type="number_sink",
        display_name="Number sink",
        inputs=[PortDefinition(name="n", data_type=DataType.NUMBER)],
    ))


class TestNoAnyWideningAcrossOperations:
    """Regression: the deleted `_ports_for()` built ports as the UNION across
    all operations of a (binary, domain) pair, and when two operations in the
    same domain declared the same output port with different types it widened
    that port to ANY — so edges that were never type-safe passed validation
    in BOTH directions. Per-operation resolution removed the widening; these
    tests exercise the binary node as an edge SOURCE, the direction a node
    that is only ever a target never covers."""

    def test_port_shared_across_operations_keeps_its_per_operation_type(
            self, clashing_catalog_dir):
        ports, issue = EdgeValidator._output_ports(
            _node("binary_op", binary="clash-bin", operation="things.readLabel"))
        assert issue is None
        assert [p.name for p in ports] == ["x"]
        assert ports[0].data_type == DataType.STRING
        assert ports[0].data_type != DataType.ANY

        # The sibling operation keeps ITS type too — resolution is per
        # operation, not a domain-wide union.
        ports, issue = EdgeValidator._output_ports(
            _node("binary_op", binary="clash-bin", operation="things.countThings"))
        assert issue is None
        assert [p.name for p in ports] == ["x"]
        assert ports[0].data_type == DataType.NUMBER
        assert ports[0].data_type != DataType.ANY

    def test_edge_into_a_number_only_input_is_rejected(
            self, clashing_catalog_dir, number_sink):
        # Under ANY-widening the STRING output was ANY, ANY is compatible
        # with everything, and this edge was accepted. It must not be.
        errors = EdgeValidator.validate_edge(
            _node("binary_op", binary="clash-bin", operation="things.readLabel"),
            _node("number_sink"))
        assert len(errors) == 1
        assert "Type mismatch" in errors[0]
        assert "'string'" in errors[0] and "'number'" in errors[0]

    def test_edge_into_a_string_compatible_input_is_accepted(
            self, clashing_catalog_dir):
        # Discriminating half: run_command's first input is STRING, so the
        # same node's edge is valid — a validator that rejected everything
        # would fail here.
        errors = EdgeValidator.validate_edge(
            _node("binary_op", binary="clash-bin", operation="things.readLabel"),
            _node("run_command"))
        assert errors == []


class TestBinaryDesignTimeChecks:
    """_binary_operation_errors resolves the operations table per node."""

    def test_a_complete_binary_op_node_passes(self, binary_catalog_dir):
        node = _node("binary_op", binary="demo-bin", operation="things.doThing",
                     session="s1", n="1")
        assert _binary_operation_errors(node, get_node_type("binary_op")) == []

    def test_binary_op_missing_session_and_param(self, binary_catalog_dir):
        node = _node("binary_op", binary="demo-bin", operation="things.doThing")
        errors = _binary_operation_errors(node, get_node_type("binary_op"))
        assert any("requires an identity" in e for e in errors)
        assert any("missing required parameter(s): n" in e for e in errors)

    def test_binary_op_without_binary_is_an_explicit_error(self, binary_catalog_dir):
        errors = _binary_operation_errors(_node("binary_op"), get_node_type("binary_op"))
        assert errors == ["Node 'n' (binary_op) has no binary set"]

    def test_binary_op_with_unregistered_binary_is_an_explicit_error(self, binary_catalog_dir):
        node = _node("binary_op", binary="ghost-bin", operation="things.doThing")
        errors = _binary_operation_errors(node, get_node_type("binary_op"))
        assert errors == [
            "Node 'n' (binary_op) names binary 'ghost-bin', which has no registered catalog here"
        ]

    def test_binary_op_unknown_operation(self, binary_catalog_dir):
        node = _node("binary_op", binary="demo-bin", operation="things.nope")
        errors = _binary_operation_errors(node, get_node_type("binary_op"))
        assert any("does not offer" in e for e in errors)

    def test_binary_auth_without_binary_is_an_explicit_error(self):
        errors = _binary_operation_errors(_node("binary_auth"), get_node_type("binary_auth"))
        assert errors == ["Node 'n' (binary_auth) has no binary set"]

    def test_binary_auth_verbs_come_from_the_protocol_table(self):
        node = _node("binary_auth", binary="demo-bin", operation="auth.sessionList")
        assert _binary_operation_errors(node, get_node_type("binary_auth")) == []


class TestValidateWorkflowEdges:
    """Test EdgeValidator.validate_workflow_edges() with real DB objects."""

    def test_valid_workflow(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        # trigger_manual -> switch (OBJECT -> ANY = compatible)
        cc_trigger = BaseComponentConfig(component_type="trigger_manual", trigger_config={}, is_active=True)
        db.add(cc_trigger)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="trigger_1", component_type="trigger_manual", component_config_id=cc_trigger.id))

        cc_switch = BaseComponentConfig(component_type="switch", extra_config={"rules": []})
        db.add(cc_switch)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="switch_1", component_type="switch", component_config_id=cc_switch.id))

        db.add(WorkflowEdge(workflow_id=workflow.id, source_node_id="trigger_1", target_node_id="switch_1", edge_type="direct"))
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert errors == []

    def test_conditional_edge_requires_condition_value(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        cc_switch = BaseComponentConfig(component_type="switch", extra_config={})
        db.add(cc_switch)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="switch_1", component_type="switch", component_config_id=cc_switch.id))

        cc_agent = BaseComponentConfig(component_type="agent", system_prompt="test")
        db.add(cc_agent)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="agent_1", component_type="agent", component_config_id=cc_agent.id))

        db.add(WorkflowEdge(
            workflow_id=workflow.id, source_node_id="switch_1", target_node_id="agent_1",
            edge_type="conditional", condition_value="",
        ))
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert any("missing condition_value" in e for e in errors)

    def test_conditional_edge_only_from_switch(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        cc_agent = BaseComponentConfig(component_type="agent", system_prompt="test")
        db.add(cc_agent)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="agent_1", component_type="agent", component_config_id=cc_agent.id))

        cc_code = BaseComponentConfig(component_type="code")
        db.add(cc_code)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="code_1", component_type="code", component_config_id=cc_code.id))

        db.add(WorkflowEdge(
            workflow_id=workflow.id, source_node_id="agent_1", target_node_id="code_1",
            edge_type="conditional", condition_value="branch_a",
        ))
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert any("only 'switch' nodes" in e for e in errors)

    def test_loop_edges_skip_type_checks(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        cc_loop = BaseComponentConfig(component_type="loop", extra_config={})
        db.add(cc_loop)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="loop_1", component_type="loop", component_config_id=cc_loop.id))

        cc_code = BaseComponentConfig(component_type="code")
        db.add(cc_code)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="code_1", component_type="code", component_config_id=cc_code.id))

        # loop_body and loop_return edges should bypass type validation
        db.add(WorkflowEdge(workflow_id=workflow.id, source_node_id="loop_1", target_node_id="code_1", edge_label="loop_body"))
        db.add(WorkflowEdge(workflow_id=workflow.id, source_node_id="code_1", target_node_id="loop_1", edge_label="loop_return"))
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert errors == []

    def test_unknown_source_node(self, db, workflow):
        from models.node import WorkflowEdge

        db.add(WorkflowEdge(workflow_id=workflow.id, source_node_id="ghost", target_node_id="also_ghost", edge_type="direct"))
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert any("unknown source node" in e for e in errors)

    def test_unknown_target_node(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        cc = BaseComponentConfig(component_type="code")
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="code_1", component_type="code", component_config_id=cc.id))
        db.add(WorkflowEdge(workflow_id=workflow.id, source_node_id="code_1", target_node_id="ghost", edge_type="direct"))
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert any("unknown target node" in e for e in errors)


class TestValidateRequiredInputs:
    """Test EdgeValidator.validate_required_inputs()."""

    def test_agent_without_model_connection(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowNode

        cc = BaseComponentConfig(component_type="agent", system_prompt="test")
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="agent_1", component_type="agent", component_config_id=cc.id))
        db.commit()

        errors = EdgeValidator.validate_required_inputs(workflow.id, db)
        assert any("requires a model connection" in e for e in errors)

    def test_agent_with_model_connection(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        cc_model = BaseComponentConfig(component_type="ai_model", model_name="gpt-4o")
        db.add(cc_model)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="model_1", component_type="ai_model", component_config_id=cc_model.id))

        cc_agent = BaseComponentConfig(component_type="agent", system_prompt="test")
        db.add(cc_agent)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="agent_1", component_type="agent", component_config_id=cc_agent.id))

        db.add(WorkflowEdge(workflow_id=workflow.id, source_node_id="model_1", target_node_id="agent_1", edge_label="llm"))
        db.commit()

        errors = EdgeValidator.validate_required_inputs(workflow.id, db)
        assert not any("agent_1" in e for e in errors)

    def test_trigger_nodes_skip_validation(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowNode

        cc = BaseComponentConfig(component_type="trigger_manual", trigger_config={}, is_active=True)
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="trigger_1", component_type="trigger_manual", component_config_id=cc.id))
        db.commit()

        errors = EdgeValidator.validate_required_inputs(workflow.id, db)
        assert errors == []


def _post_node(client, slug, node_id, component_type="binary_op", **extra_config):
    return client.post(f"/api/v1/workflows/{slug}/nodes/", json={
        "node_id": node_id,
        "component_type": component_type,
        "config": {"extra_config": extra_config},
    })


def _post_edge(client, slug, source, target):
    return client.post(f"/api/v1/workflows/{slug}/edges/", json={
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": "direct",
    })


class TestPlantedViolationUnresolvedBinaryEdges:
    """Planted violation #1 — the two-path shape of the unresolved-ports class.

    Three binary_op nodes that cannot resolve their ports — no operation, an
    unknown operation, an unregistered binary. Edges from each MUST be
    accepted at POST /edges/ (sketch-first), and /validate/ MUST report each
    with its specific reason. The condition is never absent from both paths:
    if the edge-creation caller forgot to filter, the 201 assertions fail; if
    the validator stopped detecting (e.g. someone moved the filter inward),
    the edge-scoped /validate/ reports vanish and the set comparison fails —
    node-level errors alone cannot satisfy it.
    """

    def test_allowed_at_create_reported_at_validate_never_absent_from_both(
            self, auth_client, registered_binaries, workflow):
        slug = workflow.slug

        # A sink accepting anything, and the three unresolvable binary nodes.
        assert _post_node(auth_client, slug, "sink", component_type="switch",
                          rules=[]).status_code == 201
        assert _post_node(auth_client, slug, "bin_noop",
                          binary="demo-bin").status_code == 201
        assert _post_node(auth_client, slug, "bin_badop", binary="demo-bin",
                          operation="things.nope").status_code == 201
        # gone-bin is registered NOW, so the allowlist admits the node...
        assert _post_node(auth_client, slug, "bin_gone", binary="gone-bin",
                          operation="things.doThing", session="s1", n="1").status_code == 201
        # ...and then the plugin is removed, leaving the saved node behind.
        _unregister(registered_binaries, "gone-bin")

        # A RESOLVABLE, compatible binary edge for contrast: permitted and
        # never reported.
        assert _post_node(auth_client, slug, "bin_ok", binary="demo-bin",
                          operation="things.listThings").status_code == 201

        # (i) an edge from each unresolvable node is ACCEPTED at creation
        created = []
        for source in ("bin_noop", "bin_badop", "bin_gone"):
            response = _post_edge(auth_client, slug, source, "sink")
            assert response.status_code == 201, (source, response.json())
            created.append((source, "sink"))
        assert _post_edge(auth_client, slug, "bin_ok", "sink").status_code == 201

        # (ii) /validate/ REPORTS each one, with the specific reason
        response = auth_client.post(f"/api/v1/workflows/{slug}/validate/")
        assert response.status_code == 200
        report = response.json()
        assert report["valid"] is False
        errors = report["errors"]

        assert any("bin_noop" in e and "no operation selected" in e for e in errors)
        assert any("bin_badop" in e and "does not offer operation 'things.nope'" in e
                   for e in errors)
        assert any("bin_gone" in e and "has no registered catalog here" in e for e in errors)

        # (iii) the /validate/ report covers EXACTLY the edges creation
        # permitted. These are the EDGE-scoped entries produced by
        # validate_edge through validate_workflow_edges — if the validator
        # swallowed the condition (the filter moved inward), they disappear
        # even though node-level errors remain, and this fails.
        reported = set()
        for e in errors:
            if e.startswith("Edge ") and "cannot be resolved" in e:
                head = e.split(":", 1)[0]
                source, target = head[len("Edge "):].split(" → ")
                reported.add((source, target))
        assert reported == set(created)

        # The resolvable node is reported by neither path.
        assert not any("bin_ok" in e for e in errors)

    def test_type_mismatch_on_resolvable_binary_node_still_refused_at_create(
            self, auth_client, registered_binaries, workflow):
        """The creation caller must not skip validation wholesale."""
        slug = workflow.slug
        assert _post_node(auth_client, slug, "bin_num", binary="demo-bin",
                          operation="things.doThing", session="s1", n="1").status_code == 201
        assert _post_node(auth_client, slug, "agent_1",
                          component_type="agent").status_code == 201

        # things.doThing's first output is NUMBER; agent expects MESSAGES
        response = _post_edge(auth_client, slug, "bin_num", "agent_1")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert any("Type mismatch" in e for e in detail["validation_errors"])


class TestBinaryAllowlistOnWrite:
    """extra_config["binary"] is agent-writable; every write that sets or
    changes it goes through the server-side allowlist (verified_plugin)."""

    def test_a_path_is_never_storable(self, auth_client, registered_binaries, workflow):
        response = _post_node(auth_client, workflow.slug, "bin_path",
                              binary="../../usr/bin")
        assert response.status_code == 422

    def test_an_unregistered_binary_is_refused(self, auth_client, registered_binaries, workflow):
        response = _post_node(auth_client, workflow.slug, "bin_ghost", binary="ghost-bin")
        assert response.status_code == 422

    def test_a_registered_binary_is_accepted(self, auth_client, registered_binaries, workflow):
        response = _post_node(auth_client, workflow.slug, "bin_ok", binary="demo-bin")
        assert response.status_code == 201

    def test_binary_auth_goes_through_the_same_allowlist(
            self, auth_client, registered_binaries, workflow):
        assert _post_node(auth_client, workflow.slug, "auth_path",
                          component_type="binary_auth",
                          binary="../../usr/bin").status_code == 422
        assert _post_node(auth_client, workflow.slug, "auth_ok",
                          component_type="binary_auth",
                          binary="demo-bin").status_code == 201

    def test_a_node_may_be_created_without_a_binary(
            self, auth_client, registered_binaries, workflow):
        """Sketch-first: the name is checked whenever it is set, not before."""
        assert _post_node(auth_client, workflow.slug, "bin_blank").status_code == 201

    def test_update_changing_to_an_unregistered_binary_is_refused(
            self, auth_client, registered_binaries, workflow):
        slug = workflow.slug
        assert _post_node(auth_client, slug, "bin_1", binary="demo-bin").status_code == 201
        response = auth_client.patch(f"/api/v1/workflows/{slug}/nodes/bin_1/", json={
            "config": {"extra_config": {"binary": "ghost-bin"}},
        })
        assert response.status_code == 422

    def test_update_changing_to_a_registered_binary_is_accepted(
            self, auth_client, registered_binaries, workflow):
        slug = workflow.slug
        assert _post_node(auth_client, slug, "bin_1", binary="demo-bin").status_code == 201
        response = auth_client.patch(f"/api/v1/workflows/{slug}/nodes/bin_1/", json={
            "config": {"extra_config": {"binary": "gone-bin"}},
        })
        assert response.status_code == 200

    def test_update_keeping_the_binary_does_not_recheck_it(
            self, auth_client, registered_binaries, workflow):
        """A saved node must stay editable after its plugin vanished — only
        SETTING or CHANGING the name re-runs the allowlist."""
        slug = workflow.slug
        assert _post_node(auth_client, slug, "bin_1", binary="gone-bin").status_code == 201
        _unregister(registered_binaries, "gone-bin")
        response = auth_client.patch(f"/api/v1/workflows/{slug}/nodes/bin_1/", json={
            "config": {"extra_config": {"binary": "gone-bin",
                                        "operation": "things.doThing"}},
        })
        assert response.status_code == 200

    def test_reads_stay_unvalidated(self, auth_client, registered_binaries, workflow):
        """A node stays readable regardless of catalog presence."""
        slug = workflow.slug
        assert _post_node(auth_client, slug, "bin_1", binary="gone-bin").status_code == 201
        _unregister(registered_binaries, "gone-bin")
        response = auth_client.get(f"/api/v1/workflows/{slug}/nodes/")
        assert response.status_code == 200
        assert any(n["node_id"] == "bin_1" for n in response.json())
