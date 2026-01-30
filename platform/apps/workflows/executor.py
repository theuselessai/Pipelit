"""WorkflowExecutor — RQ entry point for executing workflows."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

import django_rq
from django.utils import timezone
from langchain_core.messages import HumanMessage

from apps.workflows.cache import graph_cache
from apps.workflows.state import WorkflowState

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """Executes a workflow by loading the compiled graph and invoking it."""

    def execute(self, execution_id: str) -> None:
        """Run a workflow execution end-to-end.

        Args:
            execution_id: UUID of the WorkflowExecution record.
        """
        from apps.workflows.models import WorkflowExecution, ExecutionLog, PendingTask

        execution = (
            WorkflowExecution.objects.select_related(
                "workflow", "trigger", "user_profile"
            )
            .get(execution_id=execution_id)
        )

        workflow = execution.workflow
        execution.status = "running"
        execution.started_at = timezone.now()
        execution.save(update_fields=["status", "started_at"])

        try:
            graph = graph_cache.get_or_build(workflow)

            # Build initial state from trigger payload
            initial_state = self._build_initial_state(execution)

            config = {
                "configurable": {
                    "thread_id": execution.thread_id,
                }
            }

            # Invoke graph
            result = graph.invoke(initial_state, config)

            # Check for interruption
            snapshot = graph.get_state(config)
            if snapshot.next:
                # Graph is interrupted — waiting for human input
                self._handle_interruption(execution, snapshot)
                return

            # Completed
            execution.status = "completed"
            execution.final_output = self._extract_output(result)
            execution.completed_at = timezone.now()
            execution.save(update_fields=["status", "final_output", "completed_at"])

            logger.info("Workflow execution %s completed", execution_id)

            # Deliver results back to the user
            from apps.workflows.delivery import output_delivery
            output_delivery.deliver(execution)

        except Exception as exc:
            logger.exception("Workflow execution %s failed", execution_id)
            execution.status = "failed"
            execution.error_message = str(exc)[:2000]
            execution.completed_at = timezone.now()
            execution.save(update_fields=["status", "error_message", "completed_at"])

            # Invoke error handler if configured
            if workflow.error_handler_workflow_id:
                self._invoke_error_handler(execution, exc)

    def resume(self, execution_id: str, user_input: str) -> None:
        """Resume an interrupted workflow execution.

        Args:
            execution_id: UUID of the WorkflowExecution record.
            user_input: User's response (e.g., "confirm" or "cancel").
        """
        from apps.workflows.models import WorkflowExecution

        execution = (
            WorkflowExecution.objects.select_related("workflow")
            .get(execution_id=execution_id)
        )

        if execution.status != "interrupted":
            logger.warning(
                "Cannot resume execution %s with status '%s'",
                execution_id,
                execution.status,
            )
            return

        workflow = execution.workflow
        execution.status = "running"
        execution.save(update_fields=["status"])

        try:
            graph = graph_cache.get_or_build(workflow)
            config = {"configurable": {"thread_id": execution.thread_id}}

            # Resume with user input via Command
            from langgraph.types import Command

            result = graph.invoke(Command(resume=user_input), config)

            # Check for another interruption
            snapshot = graph.get_state(config)
            if snapshot.next:
                self._handle_interruption(execution, snapshot)
                return

            execution.status = "completed"
            execution.final_output = self._extract_output(result)
            execution.completed_at = timezone.now()
            execution.save(update_fields=["status", "final_output", "completed_at"])

            logger.info("Workflow execution %s resumed and completed", execution_id)

            # Deliver results back to the user
            from apps.workflows.delivery import output_delivery
            output_delivery.deliver(execution)

        except Exception as exc:
            logger.exception("Workflow execution %s failed on resume", execution_id)
            execution.status = "failed"
            execution.error_message = str(exc)[:2000]
            execution.completed_at = timezone.now()
            execution.save(update_fields=["status", "error_message", "completed_at"])

    def _build_initial_state(self, execution) -> dict:
        """Build initial WorkflowState dict from execution data."""
        payload = execution.trigger_payload or {}
        messages = []

        # Extract message text from trigger payload
        text = payload.get("text", "")
        if text:
            messages.append(HumanMessage(content=text))

        return {
            "messages": messages,
            "trigger": payload,
            "user_context": {
                "user_profile_id": execution.user_profile_id,
                "telegram_chat_id": payload.get("chat_id"),
            },
            "current_node": "",
            "execution_id": str(execution.execution_id),
            "route": "",
            "branch_results": {},
            "plan": [],
            "node_outputs": {},
            "output": None,
            "loop_state": {},
            "error": "",
            "should_retry": False,
        }

    def _handle_interruption(self, execution, snapshot) -> None:
        """Handle graph interruption — create PendingTask."""
        from apps.workflows.models import PendingTask
        from apps.system.models import SystemConfig

        config = SystemConfig.load()
        timeout = config.confirmation_timeout_seconds

        # Extract interrupt data
        interrupt_data = {}
        if snapshot.tasks:
            for task in snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_data = task.interrupts[0].value
                    break

        prompt = interrupt_data.get("prompt", "Confirmation required.")
        node_id = interrupt_data.get("node_id", "")

        payload = execution.trigger_payload or {}

        PendingTask.objects.create(
            task_id=uuid.uuid4().hex[:8],
            execution=execution,
            user_profile=execution.user_profile,
            telegram_chat_id=payload.get("chat_id", 0),
            node_id=node_id,
            prompt=prompt,
            expires_at=timezone.now() + timedelta(seconds=timeout),
        )

        execution.status = "interrupted"
        execution.save(update_fields=["status"])
        logger.info("Workflow execution %s interrupted at node '%s'", execution.execution_id, node_id)

    def _extract_output(self, result: dict) -> dict | None:
        """Extract final output from graph result."""
        if not result:
            return None
        output = result.get("output")
        if output is not None:
            return {"output": output}
        node_outputs = result.get("node_outputs", {})
        if node_outputs:
            return {"node_outputs": node_outputs}
        messages = result.get("messages", [])
        if messages:
            last = messages[-1]
            return {"message": last.content if hasattr(last, "content") else str(last)}
        return None

    def _invoke_error_handler(self, execution, exc: Exception) -> None:
        """Enqueue the error handler workflow."""
        from apps.workflows.models import WorkflowExecution

        error_workflow = execution.workflow.error_handler_workflow
        if not error_workflow or not error_workflow.is_active:
            return

        error_execution = WorkflowExecution.objects.create(
            workflow=error_workflow,
            parent_execution=execution,
            parent_node_id="__error_handler__",
            user_profile=execution.user_profile,
            thread_id=uuid.uuid4().hex,
            trigger_payload={
                "error": str(exc)[:1000],
                "source_workflow": execution.workflow.slug,
                "source_execution_id": str(execution.execution_id),
            },
        )

        queue = django_rq.get_queue("workflows")
        queue.enqueue(execute_workflow_job, str(error_execution.execution_id))


# RQ job entry point
def execute_workflow_job(execution_id: str) -> None:
    """RQ job function to execute a workflow."""
    executor = WorkflowExecutor()
    executor.execute(execution_id)


def resume_workflow_job(execution_id: str, user_input: str) -> None:
    """RQ job function to resume an interrupted workflow."""
    executor = WorkflowExecutor()
    executor.resume(execution_id, user_input)
