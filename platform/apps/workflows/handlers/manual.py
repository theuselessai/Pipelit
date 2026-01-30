"""ManualTriggerHandler — Django views for manual workflow execution."""

from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.workflows.handlers import dispatch_event

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def manual_execute_view(request, workflow_slug: str):
    """Manually trigger a workflow execution.

    URL: POST /api/workflows/<workflow_slug>/execute/

    Requires Django session or basic auth.

    Returns:
        JSON with execution_id or error.
    """
    user_profile = _resolve_user_profile(request)
    if user_profile is None:
        return JsonResponse({"error": "Authentication required"}, status=401)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    # Verify workflow exists and user has access
    from apps.workflows.models import Workflow

    try:
        workflow = Workflow.objects.get(slug=workflow_slug, is_active=True)
    except Workflow.DoesNotExist:
        return JsonResponse({"error": "Workflow not found"}, status=404)

    event_data = {
        "text": body.get("text", ""),
        "workflow_slug": workflow_slug,
        **body,
    }

    execution = dispatch_event("manual", event_data, user_profile)

    if execution is None:
        return JsonResponse(
            {"error": "No trigger configured for manual execution"}, status=404
        )

    return JsonResponse(
        {
            "execution_id": str(execution.execution_id),
            "status": execution.status,
        },
        status=202,
    )


@require_GET
def execution_status_view(request, execution_id: str):
    """Check status of a workflow execution.

    URL: GET /api/executions/<execution_id>/
    """
    user_profile = _resolve_user_profile(request)
    if user_profile is None:
        return JsonResponse({"error": "Authentication required"}, status=401)

    from apps.workflows.models import WorkflowExecution

    try:
        execution = WorkflowExecution.objects.get(execution_id=execution_id)
    except WorkflowExecution.DoesNotExist:
        return JsonResponse({"error": "Execution not found"}, status=404)

    data = {
        "execution_id": str(execution.execution_id),
        "workflow": execution.workflow.slug,
        "status": execution.status,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "final_output": execution.final_output,
        "error_message": execution.error_message or None,
    }
    return JsonResponse(data)


def _resolve_user_profile(request):
    """Resolve UserProfile from Django auth or basic auth."""
    import base64

    from django.contrib.auth import authenticate

    from apps.users.models import UserProfile

    # Try session auth first
    if request.user and request.user.is_authenticated:
        try:
            return request.user.profile
        except UserProfile.DoesNotExist:
            return None

    # Try basic auth
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            user = authenticate(request, username=username, password=password)
            if user:
                try:
                    return user.profile
                except UserProfile.DoesNotExist:
                    return None
        except Exception:
            pass

    return None
