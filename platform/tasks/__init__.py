"""RQ task definitions.

All RQ enqueue calls MUST import from this module (not services.*)
so that the worker resolves functions as `tasks.<name>`.

We define thin wrappers here so that __module__ is 'tasks',
which is what RQ serializes for job lookup.
"""


def execute_workflow_job(execution_id: str) -> None:
    from services.orchestrator import start_execution_job
    start_execution_job(execution_id)


def resume_workflow_job(execution_id: str, user_input: str) -> None:
    from services.orchestrator import resume_node_job
    resume_node_job(execution_id, user_input)


def execute_node_job(execution_id: str, node_id: str, retry_count: int = 0) -> None:
    from services.orchestrator import execute_node_job as _run
    _run(execution_id, node_id, retry_count)


def start_execution_job(execution_id: str) -> None:
    from services.orchestrator import start_execution
    start_execution(execution_id)


def cleanup_stuck_child_waits_job() -> int:
    from services.cleanup import cleanup_stuck_child_waits
    return cleanup_stuck_child_waits()


def execute_scheduled_job_task(job_id: str, current_repeat: int = 0, current_retry: int = 0) -> None:
    from services.scheduler import execute_scheduled_job
    execute_scheduled_job(job_id, current_repeat, current_retry)
