import uuid

from django.shortcuts import get_object_or_404
from ninja import Router

from apps.workflows.models import WorkflowExecution

from .schemas import ChatMessageIn, ChatMessageOut, ExecutionDetailOut, ExecutionOut

router = Router(tags=["executions"])
chat_router = Router(tags=["chat"])


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


@chat_router.post("/{slug}/chat/", response=ChatMessageOut)
def send_chat_message(request, slug: str, payload: ChatMessageIn):
    from apps.workflows.models import Workflow, WorkflowNode
    from apps.workflows.models.node import ComponentType
    from apps.workflows.executor import WorkflowExecutor

    workflow = get_object_or_404(Workflow, slug=slug)
    trigger_node = get_object_or_404(
        WorkflowNode, workflow=workflow, component_type=ComponentType.TRIGGER_CHAT,
    )

    execution = WorkflowExecution.objects.create(
        workflow=workflow,
        trigger_node=trigger_node,
        user_profile=request.auth,
        thread_id=uuid.uuid4().hex,
        trigger_payload={"text": payload.text},
    )

    WorkflowExecutor().execute(str(execution.execution_id))

    execution.refresh_from_db()
    response_text = ""
    if execution.final_output:
        response_text = (
            execution.final_output.get("message")
            or execution.final_output.get("output")
            or str(execution.final_output)
        )

    return ChatMessageOut(
        execution_id=execution.execution_id,
        status=execution.status,
        response=response_text,
    )
