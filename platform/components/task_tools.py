"""Task tools component — LangChain tools for managing tasks within epics."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register

logger = logging.getLogger(__name__)


@register("task_tools")
def task_tools_factory(node):
    """Return a list of LangChain tools for task management."""
    from database import SessionLocal
    from models.workflow import Workflow

    db = SessionLocal()
    try:
        workflow = db.query(Workflow).filter(Workflow.id == node.workflow_id).first()
        if not workflow:
            raise ValueError(f"task_tools: workflow {node.workflow_id} not found — cannot resolve owner")
        user_profile_id = workflow.owner_id
        if not user_profile_id:
            raise ValueError(f"task_tools: workflow {node.workflow_id} has no owner_id — cannot resolve owner")
    finally:
        db.close()

    tool_node_id = node.node_id

    @tool
    def create_task(
        epic_id: str,
        title: str,
        description: str = "",
        tags: str = "",
        depends_on: str = "",
        priority: int = 2,
        estimated_tokens: int | None = None,
        max_retries: int = 2,
    ) -> str:
        """Create a new task within an epic.

        Args:
            epic_id: The parent epic ID.
            title: Task title.
            description: Detailed description.
            tags: Comma-separated tags.
            depends_on: Comma-separated task IDs this task depends on.
            priority: Priority 1-5 (default 2).
            estimated_tokens: Estimated token cost.
            max_retries: Max retry attempts (default 2).

        Returns:
            JSON with success, task_id, status.
        """
        from database import SessionLocal
        from models.epic import Epic, Task
        from api.epic_helpers import serialize_task, sync_epic_progress

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        dep_list = [d.strip() for d in depends_on.split(",") if d.strip()] if depends_on else []

        db = SessionLocal()
        try:
            epic = (
                db.query(Epic)
                .filter(Epic.id == epic_id, Epic.user_profile_id == user_profile_id)
                .first()
            )
            if not epic:
                return json.dumps({"success": False, "error": "Epic not found"})

            if priority < 1 or priority > 5:
                return json.dumps({"success": False, "error": "Priority must be between 1 and 5"})

            # Validate that dependencies exist within this epic
            if dep_list:
                existing_deps = (
                    db.query(Task)
                    .filter(Task.id.in_(dep_list), Task.epic_id == epic_id)
                    .count()
                )
                if existing_deps != len(dep_list):
                    return json.dumps({"success": False, "error": "One or more dependencies do not exist"})

            # Auto-resolve blocked status if deps not all completed
            initial_status = "pending"
            if dep_list:
                completed_deps = (
                    db.query(Task)
                    .filter(Task.id.in_(dep_list), Task.status == "completed")
                    .count()
                )
                if completed_deps < len(dep_list):
                    initial_status = "blocked"

            task = Task(
                epic_id=epic_id,
                title=title,
                description=description,
                tags=tag_list,
                depends_on=dep_list,
                priority=priority,
                estimated_tokens=estimated_tokens,
                max_retries=max_retries,
                status=initial_status,
                created_by_node_id=tool_node_id,
            )
            db.add(task)
            db.flush()
            sync_epic_progress(epic, db)
            db.commit()
            db.refresh(task)
            try:
                from ws.broadcast import broadcast
                broadcast(f"epic:{task.epic_id}", "task_created", serialize_task(task))
            except Exception:
                logger.exception("Failed to broadcast task_created")
            return json.dumps({"success": True, "task_id": task.id, "status": task.status})
        except Exception as e:
            db.rollback()
            logger.exception("Error creating task")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    @tool
    def list_tasks(
        epic_id: str,
        status: str | None = None,
        tags: str | None = None,
        limit: int = 20,
    ) -> str:
        """List tasks within an epic, optionally filtered.

        Args:
            epic_id: The epic ID.
            status: Filter by status (pending, blocked, running, completed, failed, cancelled).
            tags: Comma-separated tags to filter by.
            limit: Max results (default 20).

        Returns:
            JSON with tasks list and total count.
        """
        from database import SessionLocal
        from models.epic import Epic, Task
        from sqlalchemy import or_

        limit = max(1, min(limit, 100))
        db = SessionLocal()
        try:
            epic = (
                db.query(Epic)
                .filter(Epic.id == epic_id, Epic.user_profile_id == user_profile_id)
                .first()
            )
            if not epic:
                return json.dumps({"success": False, "error": "Epic not found"})

            q = db.query(Task).filter(Task.epic_id == epic_id)
            if status:
                q = q.filter(Task.status == status)
            if tags:
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                if tag_list:
                    q = q.filter(or_(*[Task.tags.contains(tag) for tag in tag_list]))

            total = q.count()
            tasks = q.order_by(Task.created_at.desc()).limit(limit).all()
            task_list = [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "priority": t.priority,
                    "depends_on": t.depends_on or [],
                    "execution_id": t.execution_id,
                }
                for t in tasks
            ]
            return json.dumps({"success": True, "tasks": task_list, "total": total})
        except Exception as e:
            logger.exception("Error listing tasks")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    @tool
    def update_task(
        task_id: str,
        status: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority: int | None = None,
        result_summary: str | None = None,
        error_message: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Update a task's fields. Only provided fields are changed.

        Args:
            task_id: The task ID.
            status: New status (pending, blocked, running, completed, failed, cancelled).
            title: New title.
            description: New description.
            priority: New priority 1-5.
            result_summary: Summary of results when completing.
            error_message: Error message if failed.
            notes: A note to append to the task's notes list.

        Returns:
            JSON with success, task_id, status.
        """
        from database import SessionLocal
        from models.epic import Epic, Task
        from api.epic_helpers import serialize_task, sync_epic_progress

        db = SessionLocal()
        try:
            task = (
                db.query(Task)
                .join(Epic)
                .filter(Task.id == task_id, Epic.user_profile_id == user_profile_id)
                .first()
            )
            if not task:
                return json.dumps({"success": False, "error": "Task not found"})

            if title is not None:
                task.title = title
            if description is not None:
                task.description = description
            if priority is not None:
                if priority < 1 or priority > 5:
                    return json.dumps({"success": False, "error": "Priority must be between 1 and 5"})
                task.priority = priority
            if result_summary is not None:
                task.result_summary = result_summary
            if error_message is not None:
                task.error_message = error_message
            if status is not None:
                task.status = status
            if notes is not None:
                existing_notes = task.notes or []
                task.notes = existing_notes + [notes]

            db.flush()
            epic = db.query(Epic).filter(Epic.id == task.epic_id).first()
            if epic:
                sync_epic_progress(epic, db)

            db.commit()
            db.refresh(task)
            try:
                from ws.broadcast import broadcast
                broadcast(f"epic:{task.epic_id}", "task_updated", serialize_task(task))
            except Exception:
                logger.exception("Failed to broadcast task_updated")
            return json.dumps({"success": True, "task_id": task.id, "status": task.status})
        except Exception as e:
            db.rollback()
            logger.exception("Error updating task")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    @tool
    def cancel_task(task_id: str, reason: str = "") -> str:
        """Cancel a task and optionally its linked execution.

        Args:
            task_id: The task ID to cancel.
            reason: Optional reason for cancellation.

        Returns:
            JSON with success, task_id, execution_cancelled.
        """
        from database import SessionLocal
        from models.epic import Epic, Task
        from models.execution import WorkflowExecution
        from api.epic_helpers import serialize_task, sync_epic_progress

        db = SessionLocal()
        try:
            task = (
                db.query(Task)
                .join(Epic)
                .filter(Task.id == task_id, Epic.user_profile_id == user_profile_id)
                .first()
            )
            if not task:
                return json.dumps({"success": False, "error": "Task not found"})

            task.status = "cancelled"
            if reason:
                existing_notes = task.notes or []
                task.notes = existing_notes + [f"Cancelled: {reason}"]

            execution_cancelled = False
            if task.execution_id:
                execution = (
                    db.query(WorkflowExecution)
                    .filter(WorkflowExecution.execution_id == task.execution_id)
                    .first()
                )
                if execution and execution.status in ("pending", "running"):
                    execution.status = "cancelled"
                    execution_cancelled = True

            db.flush()
            epic = db.query(Epic).filter(Epic.id == task.epic_id).first()
            if epic:
                sync_epic_progress(epic, db)

            db.commit()
            db.refresh(task)
            try:
                from ws.broadcast import broadcast
                broadcast(f"epic:{task.epic_id}", "task_updated", serialize_task(task))
            except Exception:
                logger.exception("Failed to broadcast task_updated")
            return json.dumps({"success": True, "task_id": task.id, "execution_cancelled": execution_cancelled})
        except Exception as e:
            db.rollback()
            logger.exception("Error cancelling task")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    return [create_task, list_tasks, update_task, cancel_task]
