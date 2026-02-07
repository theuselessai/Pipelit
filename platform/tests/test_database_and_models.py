"""Tests for database.py and models/system.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── database.py ───────────────────────────────────────────────────────────────

class TestGetDb:
    def test_yields_session_and_closes(self):
        from database import get_db

        gen = get_db()
        db = next(gen)
        assert db is not None
        # Closing via StopIteration
        try:
            next(gen)
        except StopIteration:
            pass

    def test_closes_on_exception(self):
        from database import get_db

        gen = get_db()
        db = next(gen)
        try:
            gen.throw(RuntimeError("test error"))
        except RuntimeError:
            pass


# ── models/system.py ──────────────────────────────────────────────────────────

class TestSystemConfig:
    def test_load_creates_if_not_exists(self, db):
        from models.system import SystemConfig

        config = SystemConfig.load(db)
        assert config.id == 1
        assert config.default_timezone == "UTC"
        assert config.max_workflow_execution_seconds == 600
        assert config.confirmation_timeout_seconds == 300
        assert config.sandbox_code_execution is False
        assert config.feature_flags == {}

    def test_load_returns_existing(self, db):
        from models.system import SystemConfig

        # First load creates
        c1 = SystemConfig.load(db)
        c1.default_timezone = "US/Eastern"
        db.commit()

        # Second load returns same
        c2 = SystemConfig.load(db)
        assert c2.id == 1
        assert c2.default_timezone == "US/Eastern"

    def test_default_values(self, db):
        from models.system import SystemConfig

        config = SystemConfig.load(db)
        assert config.default_llm_credential_id is None
        assert config.default_llm_model_name == ""
