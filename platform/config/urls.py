from django.contrib import admin
from django.urls import path, re_path
from django.views.generic import TemplateView

from apps.workflows.api import api
from apps.workflows.handlers.manual import execution_status_view, manual_execute_view
from apps.workflows.handlers.webhook import webhook_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    # Webhook endpoint
    path("api/webhooks/<str:webhook_path>/", webhook_view, name="webhook"),
    # Manual workflow execution
    path(
        "api/workflows/<slug:workflow_slug>/execute/",
        manual_execute_view,
        name="manual-execute",
    ),
    # Execution status
    path(
        "api/executions/<str:execution_id>/",
        execution_status_view,
        name="execution-status",
    ),
    # SPA catch-all — serves index.html for all non-API routes
    re_path(r"^(?!api/|admin/).*$", TemplateView.as_view(template_name="index.html"), name="spa"),
]
