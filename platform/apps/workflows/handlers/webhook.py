"""WebhookTriggerHandler — Django view for incoming webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.workflows.handlers import dispatch_event

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def webhook_view(request, webhook_path: str):
    """Receive an incoming webhook and dispatch to matching workflow.

    URL: POST /api/webhooks/<webhook_path>/

    Optionally validates a shared secret via X-Webhook-Secret header
    (compared against trigger config's "secret" field).

    Returns:
        JSON with execution_id or error message.
    """
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    event_data = {
        "path": webhook_path,
        "body": body,
        "headers": {k: v for k, v in request.headers.items()},
    }

    # Resolve user profile from authenticated request or None
    user_profile = _resolve_user_profile(request)
    if user_profile is None:
        return JsonResponse({"error": "Authentication required"}, status=401)

    # Validate webhook secret if provided in header
    secret_header = request.headers.get("X-Webhook-Secret", "")
    if secret_header:
        event_data["provided_secret"] = secret_header

    execution = dispatch_event("webhook", event_data, user_profile)

    if execution is None:
        return JsonResponse(
            {"error": "No workflow matched this webhook path"}, status=404
        )

    return JsonResponse(
        {
            "execution_id": str(execution.execution_id),
            "status": execution.status,
        },
        status=202,
    )


def _resolve_user_profile(request):
    """Resolve UserProfile from Django auth or return None."""
    from apps.users.models import UserProfile

    if request.user and request.user.is_authenticated:
        try:
            return request.user.profile
        except UserProfile.DoesNotExist:
            return None
    return None
