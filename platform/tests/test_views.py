"""Tests for webhook and manual execution views."""

import json
from unittest.mock import patch

import pytest
from django.test import RequestFactory

from apps.workflows.handlers.manual import execution_status_view, manual_execute_view
from apps.workflows.handlers.webhook import webhook_view
from apps.workflows.models import WorkflowExecution


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.mark.django_db
class TestWebhookView:
    def test_valid_webhook(self, rf, user, user_profile, webhook_trigger):
        request = rf.post(
            "/api/webhooks/test-hook/",
            data=json.dumps({"key": "val"}),
            content_type="application/json",
        )
        request.user = user

        with patch("apps.workflows.handlers.django_rq") as mock_rq:
            mock_rq.get_queue.return_value.enqueue.return_value = None
            response = webhook_view(request, "test-hook")

        assert response.status_code == 202
        data = json.loads(response.content)
        assert "execution_id" in data

    def test_no_matching_webhook(self, rf, user, user_profile):
        request = rf.post(
            "/api/webhooks/unknown/",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.user = user
        response = webhook_view(request, "unknown")
        assert response.status_code == 404

    def test_unauthenticated(self, rf):
        from django.contrib.auth.models import AnonymousUser

        request = rf.post(
            "/api/webhooks/test/",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.user = AnonymousUser()
        response = webhook_view(request, "test")
        assert response.status_code == 401

    def test_invalid_json(self, rf, user, user_profile):
        request = rf.post(
            "/api/webhooks/test/",
            data="not json",
            content_type="application/json",
        )
        request.user = user
        response = webhook_view(request, "test")
        assert response.status_code == 400


@pytest.mark.django_db
class TestManualExecuteView:
    def test_valid_manual_trigger(self, rf, user, user_profile, manual_trigger, workflow):
        request = rf.post(
            f"/api/workflows/{workflow.slug}/execute/",
            data=json.dumps({"text": "go"}),
            content_type="application/json",
        )
        request.user = user

        with patch("apps.workflows.handlers.django_rq") as mock_rq:
            mock_rq.get_queue.return_value.enqueue.return_value = None
            response = manual_execute_view(request, workflow.slug)

        assert response.status_code == 202

    def test_workflow_not_found(self, rf, user, user_profile):
        request = rf.post(
            "/api/workflows/nonexistent/execute/",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.user = user
        response = manual_execute_view(request, "nonexistent")
        assert response.status_code == 404

    def test_unauthenticated(self, rf):
        from django.contrib.auth.models import AnonymousUser

        request = rf.post(
            "/api/workflows/test/execute/",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.user = AnonymousUser()
        response = manual_execute_view(request, "test")
        assert response.status_code == 401


@pytest.mark.django_db
class TestExecutionStatusView:
    def test_returns_status(self, rf, user, user_profile, workflow):
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            user_profile=user_profile,
            thread_id="t1",
            status="completed",
            final_output={"message": "done"},
        )

        request = rf.get(f"/api/executions/{execution.execution_id}/")
        request.user = user
        response = execution_status_view(request, str(execution.execution_id))

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["status"] == "completed"
        assert data["final_output"] == {"message": "done"}

    def test_not_found(self, rf, user, user_profile):
        request = rf.get("/api/executions/00000000-0000-0000-0000-000000000000/")
        request.user = user
        response = execution_status_view(request, "00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
