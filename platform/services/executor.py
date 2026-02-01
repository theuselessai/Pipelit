"""WorkflowExecutor — RQ entry point for executing workflows."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from services.cache import graph_cache

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """Executes a workflow by loading the compiled graph and invoking it."""

    def execute(self, execution_id: str, db: Session | None = None) -> None:
        from database import SessionLocal
        from models.execution import ExecutionLog, PendingTask, WorkflowExecution
        from models.system import SystemConfig

        own_session = db is None
        if own_session:
            db = SessionLocal()

        try:
            execution = (
                db.query(WorkflowExecution)
                .filter(WorkflowExecution.execution_id == execution_id)
                .first()
            )
            if not execution:
                logger.error("Execution %s not found", execution_id)
                return

            from models.workflow import Workflow
            workflow = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()

            execution.status = "running"
            execution.started_at = datetime.now(timezone.utc)
            db.commit()

            try:
                graph = graph_cache.get_or_build(workflow, db, trigger_node_id=execution.trigger_node_id)
                initial_state = self._build_initial_state(execution)
                config = {"configurable": {"thread_id": execution.thread_id}}

                result = graph.invoke(initial_state, config)

                snapshot = graph.get_state(config)
                if snapshot.next:
                    self._handle_interruption(execution, snapshot, db)
                    return

                execution.status = "completed"
                execution.final_output = self._extract_output(result)
                execution.completed_at = datetime.now(timezone.utc)
                db.commit()

                logger.info("Workflow execution %s completed", execution_id)

                from services.delivery import output_delivery
                output_delivery.deliver(execution, db)

            except Exception as exc:
                logger.exception("Workflow execution %s failed", execution_id)
                execution.status = "failed"
                execution.error_message = str(exc)[:2000]
                execution.completed_at = datetime.now(timezone.utc)
                db.commit()

                if workflow and workflow.error_handler_workflow_id:
                    self._invoke_error_handler(execution, exc, db)
        finally:
            if own_session:
                db.close()

    def resume(self, execution_id: str, user_input: str, db: Session | None = None) -> None:
        from database import SessionLocal
        from models.execution import WorkflowExecution
        from models.workflow import Workflow

        own_session = db is None
        if own_session:
            db = SessionLocal()

        try:
            execution = (
                db.query(WorkflowExecution)
                .filter(WorkflowExecution.execution_id == execution_id)
                .first()
            )
            if not execution or execution.status != "interrupted":
                return

            workflow = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
            execution.status = "running"
            db.commit()

            try:
                graph = graph_cache.get_or_build(workflow, db, trigger_node_id=execution.trigger_node_id)
                config = {"configurable": {"thread_id": execution.thread_id}}

                from langgraph.types import Command
                result = graph.invoke(Command(resume=user_input), config)

                snapshot = graph.get_state(config)
                if snapshot.next:
                    self._handle_interruption(execution, snapshot, db)
                    return

                execution.status = "completed"
                execution.final_output = self._extract_output(result)
                execution.completed_at = datetime.now(timezone.utc)
                db.commit()

                from services.delivery import output_delivery
                output_delivery.deliver(execution, db)

            except Exception as exc:
                logger.exception("Workflow execution %s failed on resume", execution_id)
                execution.status = "failed"
                execution.error_message = str(exc)[:2000]
                execution.completed_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            if own_session:
                db.close()

    def _build_initial_state(self, execution) -> dict:
        payload = execution.trigger_payload or {}
        messages = []
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

    def _handle_interruption(self, execution, snapshot, db: Session) -> None:
        from models.execution import PendingTask
        from models.system import SystemConfig

        config = SystemConfig.load(db)
        timeout = config.confirmation_timeout_seconds

        interrupt_data = {}
        if snapshot.tasks:
            for task in snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_data = task.interrupts[0].value
                    break

        prompt = interrupt_data.get("prompt", "Confirmation required.")
        node_id = interrupt_data.get("node_id", "")
        payload = execution.trigger_payload or {}

        pending = PendingTask(
            task_id=uuid.uuid4().hex[:8],
            execution_id=execution.execution_id,
            user_profile_id=execution.user_profile_id,
            telegram_chat_id=payload.get("chat_id", 0),
            node_id=node_id,
            prompt=prompt,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=timeout),
        )
        db.add(pending)
        execution.status = "interrupted"
        db.commit()

    def _extract_output(self, result: dict) -> dict | None:
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

    def _invoke_error_handler(self, execution, exc: Exception, db: Session) -> None:
        from models.execution import WorkflowExecution
        from models.workflow import Workflow

        error_workflow = db.query(Workflow).filter(
            Workflow.id == execution.workflow_id
        ).first()
        if not error_workflow:
            return
        error_wf = db.query(Workflow).filter(
            Workflow.id == error_workflow.error_handler_workflow_id
        ).first()
        if not error_wf or not error_wf.is_active:
            return

        error_execution = WorkflowExecution(
            workflow_id=error_wf.id,
            parent_execution_id=execution.execution_id,
            parent_node_id="__error_handler__",
            user_profile_id=execution.user_profile_id,
            thread_id=uuid.uuid4().hex,
            trigger_payload={
                "error": str(exc)[:1000],
                "source_workflow": error_workflow.slug,
                "source_execution_id": str(execution.execution_id),
            },
        )
        db.add(error_execution)
        db.commit()

        import redis
        from rq import Queue
        from config import settings

        conn = redis.from_url(settings.REDIS_URL)
        queue = Queue("workflows", connection=conn)
        queue.enqueue(execute_workflow_job, str(error_execution.execution_id))


# RQ job entry points
def execute_workflow_job(execution_id: str) -> None:
    WorkflowExecutor().execute(execution_id)


def resume_workflow_job(execution_id: str, user_input: str) -> None:
    WorkflowExecutor().resume(execution_id, user_input)
