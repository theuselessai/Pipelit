"""Tests for TriggerResolver — event-to-workflow matching."""

from __future__ import annotations

import pytest

from triggers.resolver import TriggerResolver, EVENT_TYPE_TO_COMPONENT


@pytest.fixture
def resolver():
    return TriggerResolver()


class TestEventTypeMapping:
    def test_manual_maps_correctly(self):
        assert EVENT_TYPE_TO_COMPONENT["manual"] == "trigger_manual"

    def test_webhook_maps_correctly(self):
        assert EVENT_TYPE_TO_COMPONENT["webhook"] == "trigger_webhook"

    def test_schedule_maps_correctly(self):
        assert EVENT_TYPE_TO_COMPONENT["schedule"] == "trigger_schedule"

    def test_workflow_maps_correctly(self):
        assert EVENT_TYPE_TO_COMPONENT["workflow"] == "trigger_workflow"

    def test_error_maps_correctly(self):
        assert EVENT_TYPE_TO_COMPONENT["error"] == "trigger_error"

    def test_unknown_event_not_mapped(self):
        assert EVENT_TYPE_TO_COMPONENT.get("unknown") is None


class TestResolve:
    def test_unknown_event_type_returns_none(self, resolver, db):
        result = resolver.resolve("nonexistent_event", {}, db)
        assert result is None

    def test_manual_trigger_matches(self, resolver, db, workflow, manual_trigger):
        result = resolver.resolve("manual", {}, db)
        assert result is not None
        wf, node = result
        assert wf.id == workflow.id
        assert node.component_type == "trigger_manual"

    def test_webhook_trigger_matches_path(self, resolver, db, workflow, webhook_trigger):
        result = resolver.resolve("webhook", {"path": "test-hook"}, db)
        assert result is not None
        wf, node = result
        assert wf.id == workflow.id

    def test_webhook_trigger_no_path_match(self, resolver, db, workflow, webhook_trigger):
        result = resolver.resolve("webhook", {"path": "wrong-path"}, db)
        assert result is None

    def test_no_triggers_returns_none(self, resolver, db, workflow):
        result = resolver.resolve("manual", {}, db)
        assert result is None

    def test_inactive_trigger_skipped(self, resolver, db, workflow):
        from models.node import BaseComponentConfig, WorkflowNode

        cc = BaseComponentConfig(
            component_type="trigger_manual",
            trigger_config={},
            is_active=False,
            priority=10,
        )
        db.add(cc)
        db.flush()
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="inactive_manual",
            component_type="trigger_manual",
            component_config_id=cc.id,
        )
        db.add(node)
        db.commit()

        result = resolver.resolve("manual", {}, db)
        assert result is None

    def test_priority_ordering(self, resolver, db, user_profile):
        from models.node import BaseComponentConfig, WorkflowNode
        from models.workflow import Workflow

        wf1 = Workflow(name="WF1", slug="wf1", owner_id=user_profile.id, is_active=True)
        wf2 = Workflow(name="WF2", slug="wf2", owner_id=user_profile.id, is_active=True)
        db.add_all([wf1, wf2])
        db.commit()

        cc_low = BaseComponentConfig(component_type="trigger_manual", trigger_config={}, is_active=True, priority=1)
        cc_high = BaseComponentConfig(component_type="trigger_manual", trigger_config={}, is_active=True, priority=10)
        db.add_all([cc_low, cc_high])
        db.flush()

        node_low = WorkflowNode(workflow_id=wf1.id, node_id="low_pri", component_type="trigger_manual", component_config_id=cc_low.id)
        node_high = WorkflowNode(workflow_id=wf2.id, node_id="high_pri", component_type="trigger_manual", component_config_id=cc_high.id)
        db.add_all([node_low, node_high])
        db.commit()

        result = resolver.resolve("manual", {}, db)
        assert result is not None
        wf, node = result
        assert wf.id == wf2.id  # Higher priority wins

    def test_default_workflow_fallback(self, resolver, db, user_profile):
        from models.node import BaseComponentConfig, WorkflowNode
        from models.workflow import Workflow

        # Create a default workflow with a manual trigger that has path-specific webhook matching
        default_wf = Workflow(
            name="Default", slug="default", owner_id=user_profile.id,
            is_active=True, is_default=True,
        )
        db.add(default_wf)
        db.commit()

        cc = BaseComponentConfig(
            component_type="trigger_webhook",
            trigger_config={"path": "specific-path"},
            is_active=True,
            priority=0,
        )
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(
            workflow_id=default_wf.id, node_id="webhook_default",
            component_type="trigger_webhook", component_config_id=cc.id,
        ))
        db.commit()

        # Query for webhook with non-matching path — primary trigger won't match,
        # but default workflow fallback should return it
        result = resolver.resolve("webhook", {"path": "other-path"}, db)
        assert result is not None
        wf, node = result
        assert wf.id == default_wf.id


class TestWebhookMatching:
    def test_matches_exact_path(self, resolver):
        config = {"path": "my-hook"}
        assert resolver._match_webhook(config, {"path": "my-hook"})

    def test_no_match_wrong_path(self, resolver):
        config = {"path": "my-hook"}
        assert not resolver._match_webhook(config, {"path": "other"})

    def test_no_path_config_matches_any(self, resolver):
        config = {}
        assert resolver._match_webhook(config, {"path": "anything"})


class TestTelegramMatching:
    def test_matches_allowed_user(self, resolver):
        config = {"allowed_user_ids": [123, 456]}
        assert resolver._match_telegram(config, {"user_id": 123, "text": ""})

    def test_rejects_disallowed_user(self, resolver):
        config = {"allowed_user_ids": [123]}
        assert not resolver._match_telegram(config, {"user_id": 999, "text": ""})

    def test_no_user_restriction_matches_all(self, resolver):
        config = {}
        assert resolver._match_telegram(config, {"user_id": 999, "text": ""})

    def test_pattern_match(self, resolver):
        config = {"pattern": r"hello\s+world"}
        assert resolver._match_telegram(config, {"text": "hello   world"})

    def test_pattern_no_match(self, resolver):
        config = {"pattern": r"^/start"}
        assert not resolver._match_telegram(config, {"text": "hello"})

    def test_command_match(self, resolver):
        config = {"command": "start"}
        assert resolver._match_telegram(config, {"text": "/start"})

    def test_command_no_match(self, resolver):
        config = {"command": "start"}
        assert not resolver._match_telegram(config, {"text": "/help"})

    def test_combined_filters(self, resolver):
        config = {"allowed_user_ids": [123], "pattern": "hello"}
        # Must pass both filters
        assert resolver._match_telegram(config, {"user_id": 123, "text": "hello"})
        assert not resolver._match_telegram(config, {"user_id": 999, "text": "hello"})
        assert not resolver._match_telegram(config, {"user_id": 123, "text": "goodbye"})
