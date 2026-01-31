"""Root conftest — shared fixtures for all tests."""

import pytest
from django.contrib.auth.models import User

from apps.credentials.models import BaseCredentials, TelegramCredential
from apps.users.models import UserProfile
from apps.workflows.models import Workflow, WorkflowNode
from apps.workflows.models.node import TriggerComponentConfig


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", password="testpass")


@pytest.fixture
def user_profile(user):
    return UserProfile.objects.create(user=user, telegram_user_id=111222333)


@pytest.fixture
def workflow(user_profile):
    return Workflow.objects.create(
        name="Test Workflow",
        slug="test-workflow",
        owner=user_profile,
        is_active=True,
    )


@pytest.fixture
def telegram_credential(user_profile):
    base = BaseCredentials.objects.create(
        user_profile=user_profile,
        name="Test Bot",
        credential_type="telegram",
    )
    TelegramCredential.objects.create(
        base_credentials=base,
        bot_token="123456:ABC-DEF",
        allowed_user_ids="111222333,444555666",
    )
    return base


@pytest.fixture
def telegram_trigger(workflow, telegram_credential):
    cc = TriggerComponentConfig.objects.create(
        component_type="trigger_telegram",
        credential=telegram_credential,
        trigger_config={},
        is_active=True,
        priority=10,
    )
    return WorkflowNode.objects.create(
        workflow=workflow,
        node_id="telegram_trigger_1",
        component_type="trigger_telegram",
        component_config=cc,
    )


@pytest.fixture
def webhook_trigger(workflow):
    cc = TriggerComponentConfig.objects.create(
        component_type="trigger_webhook",
        trigger_config={"path": "test-hook"},
        is_active=True,
        priority=10,
    )
    return WorkflowNode.objects.create(
        workflow=workflow,
        node_id="webhook_trigger_1",
        component_type="trigger_webhook",
        component_config=cc,
    )


@pytest.fixture
def manual_trigger(workflow):
    cc = TriggerComponentConfig.objects.create(
        component_type="trigger_manual",
        trigger_config={},
        is_active=True,
        priority=10,
    )
    return WorkflowNode.objects.create(
        workflow=workflow,
        node_id="manual_trigger_1",
        component_type="trigger_manual",
        component_config=cc,
    )
