"""Root conftest — shared fixtures for all tests."""

import pytest
from django.contrib.auth.models import User

from apps.credentials.models import BaseCredentials, TelegramCredential
from apps.users.models import UserProfile
from apps.workflows.models import Workflow, WorkflowTrigger


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
    return WorkflowTrigger.objects.create(
        workflow=workflow,
        trigger_type="telegram_chat",
        credential=telegram_credential,
        config={},
        is_active=True,
        priority=10,
    )


@pytest.fixture
def webhook_trigger(workflow):
    return WorkflowTrigger.objects.create(
        workflow=workflow,
        trigger_type="webhook",
        config={"path": "test-hook"},
        is_active=True,
        priority=10,
    )


@pytest.fixture
def manual_trigger(workflow):
    return WorkflowTrigger.objects.create(
        workflow=workflow,
        trigger_type="manual",
        config={},
        is_active=True,
        priority=10,
    )
