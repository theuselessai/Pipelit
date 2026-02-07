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


class TestValidateEdge:
    """Test EdgeValidator.validate_edge()."""

    def test_compatible_direct_edge(self):
        errors = EdgeValidator.validate_edge("trigger_manual", "switch")
        assert errors == []

    def test_incompatible_types(self):
        # filter outputs ARRAY, agent expects MESSAGES
        errors = EdgeValidator.validate_edge("filter", "agent")
        assert len(errors) == 1
        assert "Type mismatch" in errors[0]

    def test_unknown_source_type_allows(self):
        errors = EdgeValidator.validate_edge("unknown_type", "agent")
        assert errors == []

    def test_unknown_target_type_allows(self):
        errors = EdgeValidator.validate_edge("trigger_manual", "unknown_type")
        assert errors == []

    def test_sub_component_model_handle_valid(self):
        errors = EdgeValidator.validate_edge("ai_model", "agent", target_handle="model")
        assert errors == []

    def test_sub_component_tools_handle_valid(self):
        errors = EdgeValidator.validate_edge("run_command", "agent", target_handle="tools")
        assert errors == []

    def test_sub_component_memory_handle_valid(self):
        errors = EdgeValidator.validate_edge("memory_read", "agent", target_handle="memory")
        assert errors == []

    def test_sub_component_output_parser_valid(self):
        errors = EdgeValidator.validate_edge("output_parser", "categorizer", target_handle="output_parser")
        assert errors == []

    def test_sub_component_handle_on_wrong_target(self):
        # switch does not accept model connections
        errors = EdgeValidator.validate_edge("ai_model", "switch", target_handle="model")
        assert len(errors) == 1
        assert "does not accept" in errors[0]

    def test_sub_component_tools_on_non_tool_target(self):
        # switch does not accept tool connections
        errors = EdgeValidator.validate_edge("run_command", "switch", target_handle="tools")
        assert len(errors) == 1
        assert "does not accept" in errors[0]


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
