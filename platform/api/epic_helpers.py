"""Shared helpers for epic/task API routers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.epic import Epic, Task


def remove_from_depends_on(task_ids: list[str], db: Session) -> None:
    """Remove deleted task IDs from other tasks' depends_on lists."""
    id_set = set(task_ids)
    dependents = db.query(Task).filter(Task.depends_on.isnot(None)).all()
    for t in dependents:
        deps = t.depends_on or []
        cleaned = [d for d in deps if d not in id_set]
        if len(cleaned) != len(deps):
            t.depends_on = cleaned


def sync_epic_progress(epic: Epic, db: Session) -> None:
    """Recount total/completed/failed tasks from DB and update the epic."""
    epic.total_tasks = db.query(Task).filter(Task.epic_id == epic.id).count()
    epic.completed_tasks = (
        db.query(Task).filter(Task.epic_id == epic.id, Task.status == "completed").count()
    )
    epic.failed_tasks = (
        db.query(Task).filter(Task.epic_id == epic.id, Task.status == "failed").count()
    )


def serialize_epic(epic: Epic) -> dict:
    """Serialize an Epic to EpicOut shape."""
    return {
        "id": epic.id,
        "title": epic.title,
        "description": epic.description or "",
        "tags": epic.tags or [],
        "created_by_node_id": epic.created_by_node_id,
        "workflow_id": epic.workflow_id,
        "user_profile_id": epic.user_profile_id,
        "status": epic.status,
        "priority": epic.priority,
        "budget_tokens": epic.budget_tokens,
        "budget_usd": epic.budget_usd,
        "spent_tokens": epic.spent_tokens,
        "spent_usd": epic.spent_usd,
        "agent_overhead_tokens": epic.agent_overhead_tokens,
        "agent_overhead_usd": epic.agent_overhead_usd,
        "total_tasks": epic.total_tasks,
        "completed_tasks": epic.completed_tasks,
        "failed_tasks": epic.failed_tasks,
        "created_at": epic.created_at,
        "updated_at": epic.updated_at,
        "completed_at": epic.completed_at,
        "result_summary": epic.result_summary,
    }


def serialize_task(task: Task) -> dict:
    """Serialize a Task to TaskOut shape."""
    return {
        "id": task.id,
        "epic_id": task.epic_id,
        "title": task.title,
        "description": task.description or "",
        "tags": task.tags or [],
        "created_by_node_id": task.created_by_node_id,
        "status": task.status,
        "priority": task.priority,
        "workflow_id": task.workflow_id,
        "workflow_slug": task.workflow_slug,
        "execution_id": task.execution_id,
        "workflow_source": task.workflow_source,
        "depends_on": task.depends_on or [],
        "requirements": task.requirements,
        "estimated_tokens": task.estimated_tokens,
        "actual_tokens": task.actual_tokens,
        "actual_usd": task.actual_usd,
        "llm_calls": task.llm_calls,
        "tool_invocations": task.tool_invocations,
        "duration_ms": task.duration_ms,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "result_summary": task.result_summary,
        "error_message": task.error_message,
        "retry_count": task.retry_count,
        "max_retries": task.max_retries,
        "notes": task.notes or [],
    }
