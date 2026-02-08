"""Root conftest — shared fixtures for all platform tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure platform/ is on sys.path
_platform_dir = str(Path(__file__).resolve().parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

# Set encryption key for tests
if not os.environ.get("FIELD_ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet
    os.environ["FIELD_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
import models  # noqa: F401 — register all models with Base

# Use in-memory SQLite for tests — StaticPool ensures all connections share the same DB
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _setup_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def db():
    """Yield a test database session."""
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user_profile(db):
    import bcrypt
    from models.user import UserProfile

    profile = UserProfile(
        username="testuser",
        password_hash=bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode(),
        telegram_user_id=111222333,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@pytest.fixture
def api_key(db, user_profile):
    from models.user import APIKey

    key = APIKey(user_id=user_profile.id)
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


@pytest.fixture
def workflow(db, user_profile):
    from models.workflow import Workflow

    wf = Workflow(
        name="Test Workflow",
        slug="test-workflow",
        owner_id=user_profile.id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture
def telegram_credential(db, user_profile):
    from models.credential import BaseCredential, TelegramCredential

    base = BaseCredential(
        user_profile_id=user_profile.id,
        name="Test Bot",
        credential_type="telegram",
    )
    db.add(base)
    db.flush()
    tg = TelegramCredential(
        base_credentials_id=base.id,
        bot_token="123456:ABC-DEF",
        allowed_user_ids="111222333,444555666",
    )
    db.add(tg)
    db.commit()
    db.refresh(base)
    return base


@pytest.fixture
def telegram_trigger(db, workflow, telegram_credential):
    from models.node import BaseComponentConfig, WorkflowNode

    cc = BaseComponentConfig(
        component_type="trigger_telegram",
        credential_id=telegram_credential.id,
        trigger_config={},
        is_active=True,
        priority=10,
    )
    db.add(cc)
    db.flush()
    node = WorkflowNode(
        workflow_id=workflow.id,
        node_id="telegram_trigger_1",
        component_type="trigger_telegram",
        component_config_id=cc.id,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@pytest.fixture
def webhook_trigger(db, workflow):
    from models.node import BaseComponentConfig, WorkflowNode

    cc = BaseComponentConfig(
        component_type="trigger_webhook",
        trigger_config={"path": "test-hook"},
        is_active=True,
        priority=10,
    )
    db.add(cc)
    db.flush()
    node = WorkflowNode(
        workflow_id=workflow.id,
        node_id="webhook_trigger_1",
        component_type="trigger_webhook",
        component_config_id=cc.id,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@pytest.fixture
def manual_trigger(db, workflow):
    from models.node import BaseComponentConfig, WorkflowNode

    cc = BaseComponentConfig(
        component_type="trigger_manual",
        trigger_config={},
        is_active=True,
        priority=10,
    )
    db.add(cc)
    db.flush()
    node = WorkflowNode(
        workflow_id=workflow.id,
        node_id="manual_trigger_1",
        component_type="trigger_manual",
        component_config_id=cc.id,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node
