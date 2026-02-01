"""WorkflowExecutor — RQ entry point for executing workflows."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """Executes a workflow via the per-node orchestrator."""

    def execute(self, execution_id: str, db: Session | None = None) -> None:
        from services.orchestrator import start_execution
        start_execution(execution_id, db)

    def resume(self, execution_id: str, user_input: str, db: Session | None = None) -> None:
        from services.orchestrator import resume_node_job
        resume_node_job(execution_id, user_input)


# RQ job entry points
def execute_workflow_job(execution_id: str) -> None:
    from services.orchestrator import start_execution_job
    start_execution_job(execution_id)


def resume_workflow_job(execution_id: str, user_input: str) -> None:
    from services.orchestrator import resume_node_job
    resume_node_job(execution_id, user_input)
