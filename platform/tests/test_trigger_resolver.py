"""Tests for TriggerResolver — event-to-workflow matching."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from triggers.resolver import TriggerResolver, EVENT_TYPE_TO_COMPONENT


@pytest.fixture
def resolver():
    return TriggerResolver()


class TestEventTypeMapping:
    def test_manual_maps_correctly(self):
        assert EVENT_TYPE_TO_COMPONENT["manual"] == "trigger_manual"

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

        # Create a default workflow with a manual trigger
        default_wf = Workflow(
            name="Default", slug="default", owner_id=user_profile.id,
            is_active=True, is_default=True,
        )
        db.add(default_wf)
        db.commit()

        cc = BaseComponentConfig(
            component_type="trigger_manual",
            trigger_config={},
            is_active=True,
            priority=0,
        )
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(
            workflow_id=default_wf.id, node_id="manual_default",
            component_type="trigger_manual", component_config_id=cc.id,
        ))
        db.commit()

        # No non-default workflows have manual triggers, so default should be used
        result = resolver.resolve("manual", {}, db)
        assert result is not None
        wf, node = result
        assert wf.id == default_wf.id


class TestTelegramMatching:
    @pytest.fixture
    def cc(self):
        from unittest.mock import MagicMock
        return MagicMock(credential_id=None)

    def test_matches_allowed_user(self, resolver, cc):
        config = {"allowed_user_ids": [123, 456]}
        assert resolver._match_telegram(cc, config, {"user_id": 123, "text": ""})

    def test_rejects_disallowed_user(self, resolver, cc):
        config = {"allowed_user_ids": [123]}
        assert not resolver._match_telegram(cc, config, {"user_id": 999, "text": ""})

    def test_no_user_restriction_matches_all(self, resolver, cc):
        config = {}
        assert resolver._match_telegram(cc, config, {"user_id": 999, "text": ""})

    def test_pattern_match(self, resolver, cc):
        config = {"pattern": r"hello\s+world"}
        assert resolver._match_telegram(cc, config, {"text": "hello   world"})

    def test_pattern_no_match(self, resolver, cc):
        config = {"pattern": r"^/start"}
        assert not resolver._match_telegram(cc, config, {"text": "hello"})

    def test_command_match(self, resolver, cc):
        config = {"command": "start"}
        assert resolver._match_telegram(cc, config, {"text": "/start"})

    def test_command_no_match(self, resolver, cc):
        config = {"command": "start"}
        assert not resolver._match_telegram(cc, config, {"text": "/help"})

    def test_combined_filters(self, resolver, cc):
        config = {"allowed_user_ids": [123], "pattern": "hello"}
        # Must pass both filters
        assert resolver._match_telegram(cc, config, {"user_id": 123, "text": "hello"})
        assert not resolver._match_telegram(cc, config, {"user_id": 999, "text": "hello"})
        assert not resolver._match_telegram(cc, config, {"user_id": 123, "text": "goodbye"})


class TestScheduleMatching:
    def test_schedule_no_filter(self, resolver):
        """No scheduled_job_id filter → always matches."""
        assert resolver._match_schedule({}, {"scheduled_job_id": "any"})

    def test_schedule_filter_match(self, resolver):
        config = {"scheduled_job_id": "job-42"}
        assert resolver._match_schedule(config, {"scheduled_job_id": "job-42"})

    def test_schedule_filter_mismatch(self, resolver):
        config = {"scheduled_job_id": "job-42"}
        assert not resolver._match_schedule(config, {"scheduled_job_id": "job-99"})

    def test_schedule_none_config(self, resolver):
        assert resolver._match_schedule(None, {"scheduled_job_id": "any"})


class TestWorkflowMatching:
    def test_workflow_event_no_source_filter(self, resolver):
        """No source_workflow in config → always matches."""
        config_obj = MagicMock()
        config_obj.trigger_config = {}
        assert resolver._matches(config_obj, "workflow", {"source_workflow": "wf1"})

    def test_workflow_event_source_match(self, resolver):
        config_obj = MagicMock()
        config_obj.trigger_config = {"source_workflow": "wf1"}
        assert resolver._matches(config_obj, "workflow", {"source_workflow": "wf1"})

    def test_workflow_event_source_mismatch(self, resolver):
        config_obj = MagicMock()
        config_obj.trigger_config = {"source_workflow": "wf1"}
        assert not resolver._matches(config_obj, "workflow", {"source_workflow": "wf2"})


class TestDefaultWorkflowFallback:
    def test_no_default_workflow_returns_none(self, resolver, db, user_profile):
        """No default workflow → returns None."""
        result = resolver.resolve("manual", {}, db)
        assert result is None

    def test_default_workflow_without_matching_trigger_returns_none(self, resolver, db, user_profile):
        """Default workflow exists but has no matching trigger type → None."""
        from models.workflow import Workflow

        default_wf = Workflow(
            name="Default", slug="default-no-trigger",
            owner_id=user_profile.id, is_active=True, is_default=True,
        )
        db.add(default_wf)
        db.commit()

        # No trigger_manual node on this workflow
        result = resolver.resolve("manual", {}, db)
        assert result is None


class TestBotTokenMatching:
    """Tests for bot_token credential matching in _match_telegram."""

    @pytest.fixture
    def cc(self):
        return MagicMock(credential_id=1)

    def test_match_telegram_filters_by_bot_token(self, resolver, cc):
        """Trigger with credential_id=1 should reject event with mismatched bot_token."""
        cred_cache = {1: "abc"}
        assert not resolver._match_telegram(cc, {}, {"bot_token": "xyz"}, cred_cache)

    def test_match_telegram_accepts_matching_bot_token(self, resolver, cc):
        """Event with matching bot_token should pass."""
        cred_cache = {1: "abc"}
        assert resolver._match_telegram(cc, {}, {"bot_token": "abc"}, cred_cache)

    def test_match_telegram_no_credential_matches_any(self, resolver):
        """Trigger without credential_id matches any bot_token."""
        cc = MagicMock(credential_id=None)
        cred_cache = {1: "abc"}
        assert resolver._match_telegram(cc, {}, {"bot_token": "xyz"}, cred_cache)

    def test_match_telegram_no_bot_token_in_event_matches(self, resolver, cc):
        """Event without bot_token matches any trigger."""
        cred_cache = {1: "abc"}
        assert resolver._match_telegram(cc, {}, {"text": "hello"}, cred_cache)

    def test_resolve_builds_cred_cache_for_telegram(self, resolver, db, user_profile):
        """Integration: two telegram triggers with different credentials route by bot_token."""
        from models.credential import BaseCredential, TelegramCredential
        from models.node import BaseComponentConfig, WorkflowNode
        from models.workflow import Workflow

        # Create two credentials with different bot tokens
        base1 = BaseCredential(user_profile_id=user_profile.id, name="Bot A", credential_type="telegram")
        db.add(base1)
        db.flush()
        db.add(TelegramCredential(base_credentials_id=base1.id, bot_token="token_a", allowed_user_ids=""))
        db.commit()

        base2 = BaseCredential(user_profile_id=user_profile.id, name="Bot B", credential_type="telegram")
        db.add(base2)
        db.flush()
        db.add(TelegramCredential(base_credentials_id=base2.id, bot_token="token_b", allowed_user_ids=""))
        db.commit()

        # Create two workflows, each with a telegram trigger bound to a different credential
        wf1 = Workflow(name="WF-A", slug="wf-a", owner_id=user_profile.id, is_active=True)
        wf2 = Workflow(name="WF-B", slug="wf-b", owner_id=user_profile.id, is_active=True)
        db.add_all([wf1, wf2])
        db.commit()

        cc1 = BaseComponentConfig(component_type="trigger_telegram", credential_id=base1.id, trigger_config={}, is_active=True, priority=0)
        cc2 = BaseComponentConfig(component_type="trigger_telegram", credential_id=base2.id, trigger_config={}, is_active=True, priority=0)
        db.add_all([cc1, cc2])
        db.flush()

        db.add(WorkflowNode(workflow_id=wf1.id, node_id="tg_a", component_type="trigger_telegram", component_config_id=cc1.id))
        db.add(WorkflowNode(workflow_id=wf2.id, node_id="tg_b", component_type="trigger_telegram", component_config_id=cc2.id))
        db.commit()

        # Event from bot B should match wf2
        result = resolver.resolve("telegram_message", {"bot_token": "token_b", "text": "hi"}, db)
        assert result is not None
        wf, node = result
        assert wf.id == wf2.id

        # Event from bot A should match wf1
        result = resolver.resolve("telegram_message", {"bot_token": "token_a", "text": "hi"}, db)
        assert result is not None
        wf, node = result
        assert wf.id == wf1.id


class TestErrorMatching:
    def test_error_event_always_matches(self, resolver):
        config_obj = MagicMock()
        config_obj.trigger_config = {}
        assert resolver._matches(config_obj, "error", {})
