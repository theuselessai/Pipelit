"""Tests for the workflow_discover tool factory and registration."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from models.node import (
    COMPONENT_TYPE_TO_CONFIG,
    BaseComponentConfig,
    WorkflowNode,
)
from models.workflow import Workflow


# ── Tool factory tests ───────────────────────────────────────────────────────


class TestToolFactory:
    def test_factory_returns_tool_list(self):
        from components.workflow_discover import workflow_discover_factory

        node = SimpleNamespace(workflow_id=1, node_id="wd_1")
        tools = workflow_discover_factory(node)
        assert isinstance(tools, list)
        assert len(tools) == 1
        assert tools[0].name == "workflow_discover"

    def test_tool_has_correct_args(self):
        from components.workflow_discover import workflow_discover_factory

        node = SimpleNamespace(workflow_id=1, node_id="wd_1")
        tool = workflow_discover_factory(node)[0]
        schema = tool.args_schema.model_json_schema()
        assert "requirements" in schema["properties"]
        assert "limit" in schema["properties"]


# ── Registration tests ───────────────────────────────────────────────────────


class TestRegistration:
    def test_in_component_registry(self):
        from components import COMPONENT_REGISTRY
        assert "workflow_discover" in COMPONENT_REGISTRY

    def test_in_node_type_registry(self):
        import schemas.node_type_defs  # noqa: F401 — triggers registration
        from schemas.node_types import NODE_TYPE_REGISTRY
        assert "workflow_discover" in NODE_TYPE_REGISTRY
        spec = NODE_TYPE_REGISTRY["workflow_discover"]
        assert spec.category == "sub_component"

    def test_in_component_type_to_config(self):
        assert "workflow_discover" in COMPONENT_TYPE_TO_CONFIG

    def test_in_builder_sub_component_types(self):
        from services.builder import SUB_COMPONENT_TYPES
        assert "workflow_discover" in SUB_COMPONENT_TYPES

    def test_in_topology_sub_component_types(self):
        from services.topology import SUB_COMPONENT_TYPES
        assert "workflow_discover" in SUB_COMPONENT_TYPES

    def test_in_component_type_str(self):
        import typing
        from schemas.node import ComponentTypeStr
        args = typing.get_args(ComponentTypeStr)
        assert "workflow_discover" in args


# ── End-to-end tool invocation ───────────────────────────────────────────────


class TestToolEndToEnd:
    def test_discover_returns_matches(self, db, user_profile, workflow):
        """Create workflows, invoke tool, verify JSON result structure."""
        # Create a target workflow with telegram trigger and agent
        target = Workflow(
            name="Target Bot",
            slug="target-bot",
            owner_id=user_profile.id,
            is_active=True,
            tags=["bot"],
        )
        db.add(target)
        db.flush()

        cfg = BaseComponentConfig(component_type="trigger_telegram", is_active=True, trigger_config={})
        db.add(cfg)
        db.flush()
        db.add(WorkflowNode(workflow_id=target.id, node_id="tg_1", component_type="trigger_telegram", component_config_id=cfg.id))

        cfg2 = BaseComponentConfig(component_type="agent", system_prompt="Hello")
        db.add(cfg2)
        db.flush()
        db.add(WorkflowNode(workflow_id=target.id, node_id="agent_1", component_type="agent", component_config_id=cfg2.id))
        db.commit()

        # Create discover tool node on the caller workflow
        tool_cfg = BaseComponentConfig(component_type="workflow_discover", extra_config={})
        db.add(tool_cfg)
        db.flush()
        db.add(WorkflowNode(
            workflow_id=workflow.id,
            node_id="wd_1",
            component_type="workflow_discover",
            component_config_id=tool_cfg.id,
        ))
        db.commit()

        from components.workflow_discover import workflow_discover_factory

        node = SimpleNamespace(workflow_id=workflow.id, node_id="wd_1")
        tool = workflow_discover_factory(node)[0]

        requirements = json.dumps({"triggers": ["telegram"], "node_types": ["agent"]})

        with patch("database.SessionLocal", return_value=db):
            with patch.object(db, "close"):
                result_str = tool.invoke({"requirements": requirements})

        result = json.loads(result_str)
        assert result["success"] is True
        assert len(result["matches"]) >= 1

        match = result["matches"][0]
        assert match["slug"] == "target-bot"
        assert "match_score" in match
        assert "has_capabilities" in match
        assert "missing_capabilities" in match
        assert "recommendation" in match

    def test_excludes_caller_workflow(self, db, user_profile, workflow):
        """The calling workflow should be excluded from results."""
        # Add a trigger to the calling workflow so it has some capabilities
        cfg = BaseComponentConfig(component_type="trigger_telegram", is_active=True, trigger_config={})
        db.add(cfg)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="tg_1", component_type="trigger_telegram", component_config_id=cfg.id))
        db.commit()

        from components.workflow_discover import workflow_discover_factory

        node = SimpleNamespace(workflow_id=workflow.id, node_id="wd_1")
        tool = workflow_discover_factory(node)[0]

        with patch("database.SessionLocal", return_value=db):
            with patch.object(db, "close"):
                result_str = tool.invoke({"requirements": json.dumps({"triggers": ["telegram"]})})

        result = json.loads(result_str)
        assert result["success"] is True
        slugs = [m["slug"] for m in result["matches"]]
        assert workflow.slug not in slugs

    def test_invalid_json_returns_error(self):
        from components.workflow_discover import workflow_discover_factory

        node = SimpleNamespace(workflow_id=1, node_id="wd_err")
        tool = workflow_discover_factory(node)[0]

        from unittest.mock import MagicMock
        mock_db = MagicMock()

        with patch("database.SessionLocal", return_value=mock_db):
            result_str = tool.invoke({"requirements": "not-valid-json"})

        result = json.loads(result_str)
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]
