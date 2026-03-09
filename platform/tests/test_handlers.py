"""Tests for handlers/ — dispatch_event, manual, webhook, telegram."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── dispatch_event ───────────────────────────────────────────────────────────

class TestDispatchEvent:
    @patch("handlers.Queue")
    @patch("handlers.redis.from_url")
    @patch("handlers.trigger_resolver")
    def test_dispatch_matches(self, mock_resolver, mock_redis, mock_queue_cls):
        from handlers import dispatch_event

        mock_wf = MagicMock(id=1, slug="test-wf")
        mock_trigger_node = MagicMock(id=10)
        mock_resolver.resolve.return_value = (mock_wf, mock_trigger_node)

        mock_db = MagicMock()
        mock_profile = MagicMock(id=5)

        result = dispatch_event("manual", {"text": "hi"}, mock_profile, mock_db)
        assert result is not None
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("handlers.trigger_resolver")
    def test_dispatch_no_match(self, mock_resolver):
        from handlers import dispatch_event

        mock_resolver.resolve.return_value = None
        mock_db = MagicMock()
        mock_profile = MagicMock(id=5)

        result = dispatch_event("manual", {"text": "hi"}, mock_profile, mock_db)
        assert result is None


# ── TriggerResolver ──────────────────────────────────────────────────────────

class TestTriggerResolver:
    def test_resolve_unknown_event_type(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        mock_db = MagicMock()
        result = resolver.resolve("nonexistent_event", {}, mock_db)
        assert result is None

    def test_resolve_manual_event(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        mock_db = MagicMock()

        # No trigger nodes found
        mock_db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = []
        # No default workflow either
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = resolver.resolve("manual", {}, mock_db)
        assert result is None

    def test_matches_manual_always_true(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        config = MagicMock(trigger_config={})
        assert resolver._matches(config, "manual", {}) is True

    def test_matches_error_always_true(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        config = MagicMock(trigger_config={})
        assert resolver._matches(config, "error", {}) is True

    def test_matches_workflow_source(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        config = MagicMock(trigger_config={"source_workflow": "wf-1"})
        assert resolver._matches(config, "workflow", {"source_workflow": "wf-1"}) is True
        assert resolver._matches(config, "workflow", {"source_workflow": "wf-2"}) is False

        config2 = MagicMock(trigger_config={})
        assert resolver._matches(config2, "workflow", {}) is True





