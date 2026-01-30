from django.shortcuts import get_object_or_404
from ninja import Router

from apps.workflows.models import WorkflowExecution

from .schemas import ExecutionDetailOut, ExecutionOut

router = Router(tags=["executions"])


@router.get("/", response=list[ExecutionOut])
def list_executions(request, workflow_slug: str | None = None, status: str | None = None):
    profile = request.auth
    qs = WorkflowExecution.objects.filter(user_profile=profile)
    if workflow_slug:
        qs = qs.filter(workflow__slug=workflow_slug)
    if status:
        qs = qs.filter(status=status)
    return qs


@router.get("/{execution_id}/", response=ExecutionDetailOut)
def get_execution(request, execution_id: str):
    return get_object_or_404(
        WorkflowExecution.objects.filter(user_profile=request.auth),
        execution_id=execution_id,
    )


@router.post("/{execution_id}/cancel/", response=ExecutionOut)
def cancel_execution(request, execution_id: str):
    execution = get_object_or_404(
        WorkflowExecution.objects.filter(user_profile=request.auth),
        execution_id=execution_id,
    )
    if execution.status in ("pending", "running", "interrupted"):
        execution.status = "cancelled"
        execution.save(update_fields=["status"])
    return execution
