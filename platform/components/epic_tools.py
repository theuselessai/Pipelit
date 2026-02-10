"""Epic tools component — LangChain tools for managing epics."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register

logger = logging.getLogger(__name__)


@register("epic_tools")
def epic_tools_factory(node):
    """Return a list of LangChain tools for epic management."""
    from database import SessionLocal
    from models.workflow import Workflow

    db = SessionLocal()
    try:
        workflow = db.query(Workflow).filter(Workflow.id == node.workflow_id).first()
        if not workflow:
            raise ValueError(f"epic_tools: workflow {node.workflow_id} not found - cannot resolve owner")
        user_profile_id = workflow.owner_id
        if not user_profile_id:
            raise ValueError(f"epic_tools: workflow {node.workflow_id} has no owner_id - cannot resolve owner")
    finally:
        db.close()

    tool_node_id = node.node_id

    @tool
    def create_epic(
        title: str,
        description: str = "",
        tags: str = "",
        priority: int = 2,
        budget_tokens: int | None = None,
        budget_usd: float | None = None,
    ) -> str:
        """Create a new epic for organizing tasks.

        Args:
            title: Epic title.
            description: Detailed description.
            tags: Comma-separated tags (e.g. "backend,urgent").
            priority: Priority level 1-5 (1=highest, default 2).
            budget_tokens: Optional token budget limit.
            budget_usd: Optional USD budget limit.

        Returns:
            JSON with success, epic_id, title, status.
        """
        from database import SessionLocal
        from models.epic import Epic

        if priority < 1 or priority > 5:
            return json.dumps({"success": False, "error": "Priority must be between 1 and 5"})

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        db = SessionLocal()
        try:
            try:
                epic = Epic(
                    title=title,
                    description=description,
                    tags=tag_list,
                    priority=priority,
                    budget_tokens=budget_tokens,
                    budget_usd=budget_usd,
                    user_profile_id=user_profile_id,
                    created_by_node_id=tool_node_id,
                )
                db.add(epic)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.exception("Error creating epic")
                return json.dumps({"success": False, "error": str(e)})

            try:
                db.refresh(epic)
            except Exception:
                logger.exception("Failed to refresh after commit")

            try:
                from api.epic_helpers import serialize_epic
                from ws.broadcast import broadcast
                broadcast(f"epic:{epic.id}", "epic_created", serialize_epic(epic))
            except Exception:
                logger.exception("Failed to broadcast epic_created")

            return json.dumps({"success": True, "epic_id": epic.id, "title": epic.title, "status": epic.status})
        finally:
            db.close()

    @tool
    def epic_status(epic_id: str) -> str:
        """Get detailed status of an epic including task breakdown.

        Args:
            epic_id: The epic ID (e.g. "ep-abc123").

        Returns:
            JSON with epic details and task list.
        """
        from database import SessionLocal
        from models.epic import Epic, Task

        db = SessionLocal()
        try:
            epic = (
                db.query(Epic)
                .filter(Epic.id == epic_id, Epic.user_profile_id == user_profile_id)
                .first()
            )
            if not epic:
                return json.dumps({"success": False, "error": "Epic not found"})

            tasks = db.query(Task).filter(Task.epic_id == epic_id).all()
            task_list = [
                {"id": t.id, "title": t.title, "status": t.status}
                for t in tasks
            ]
            return json.dumps({
                "success": True,
                "epic_id": epic.id,
                "title": epic.title,
                "status": epic.status,
                "priority": epic.priority,
                "total_tasks": epic.total_tasks,
                "completed_tasks": epic.completed_tasks,
                "failed_tasks": epic.failed_tasks,
                "spent_tokens": epic.spent_tokens,
                "spent_usd": float(epic.spent_usd) if epic.spent_usd is not None else 0.0,
                "tasks": task_list,
            })
        except Exception as e:
            logger.exception("Error getting epic status")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    @tool
    def update_epic(
        epic_id: str,
        status: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority: int | None = None,
        budget_tokens: int | None = None,
        budget_usd: float | None = None,
        result_summary: str | None = None,
    ) -> str:
        """Update an epic's fields. Only provided fields are changed.

        Args:
            epic_id: The epic ID.
            status: New status (planning, active, paused, completed, cancelled, failed).
            title: New title.
            description: New description.
            priority: New priority 1-5.
            budget_tokens: New token budget.
            budget_usd: New USD budget.
            result_summary: Summary of results when completing.

        Returns:
            JSON with success, epic_id, status.
        """
        from database import SessionLocal
        from models.epic import Epic, Task
        from api.epic_helpers import serialize_epic, sync_epic_progress

        db = SessionLocal()
        try:
            try:
                epic = (
                    db.query(Epic)
                    .filter(Epic.id == epic_id, Epic.user_profile_id == user_profile_id)
                    .first()
                )
                if not epic:
                    return json.dumps({"success": False, "error": "Epic not found"})

                if title is not None:
                    epic.title = title
                if description is not None:
                    epic.description = description
                if priority is not None:
                    if priority < 1 or priority > 5:
                        return json.dumps({"success": False, "error": "Priority must be between 1 and 5"})
                    epic.priority = priority
                if budget_tokens is not None:
                    epic.budget_tokens = budget_tokens
                if budget_usd is not None:
                    epic.budget_usd = budget_usd
                if result_summary is not None:
                    epic.result_summary = result_summary
                VALID_EPIC_STATUSES = {"planning", "active", "paused", "completed", "cancelled", "failed"}
                if status is not None:
                    if status not in VALID_EPIC_STATUSES:
                        return json.dumps({"success": False, "error": f"Invalid status. Must be one of: {', '.join(sorted(VALID_EPIC_STATUSES))}"})
                    epic.status = status
                    if status == "cancelled":
                        tasks = (
                            db.query(Task)
                            .filter(
                                Task.epic_id == epic.id,
                                Task.status.in_(["pending", "blocked", "running"]),
                            )
                            .all()
                        )
                        for task in tasks:
                            task.status = "cancelled"

                sync_epic_progress(epic, db)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.exception("Error updating epic")
                return json.dumps({"success": False, "error": str(e)})

            try:
                db.refresh(epic)
            except Exception:
                logger.exception("Failed to refresh after commit")

            try:
                from ws.broadcast import broadcast
                broadcast(f"epic:{epic.id}", "epic_updated", serialize_epic(epic))
            except Exception:
                logger.exception("Failed to broadcast epic_updated")

            return json.dumps({"success": True, "epic_id": epic.id, "status": epic.status})
        finally:
            db.close()

    @tool
    def search_epics(
        query: str = "",
        tags: str = "",
        status: str | None = None,
        limit: int = 10,
    ) -> str:
        """Search epics by text, tags, or status.

        Args:
            query: Search text (matches title and description, case-insensitive).
            tags: Comma-separated tags to filter by (OR semantics).
            status: Filter by status.
            limit: Max results (default 10).

        Returns:
            JSON with results list.
        """
        from database import SessionLocal
        from models.epic import Epic
        from sqlalchemy import or_

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        if len(tag_list) > 20:
            return json.dumps({"success": False, "error": "Too many tags specified. Maximum is 20."})
        limit = max(1, min(limit, 100))
        db = SessionLocal()
        try:
            q = db.query(Epic).filter(Epic.user_profile_id == user_profile_id)
            if status:
                q = q.filter(Epic.status == status)
            if tag_list:
                q = q.filter(or_(*[Epic.tags.contains(tag) for tag in tag_list]))
            if query:
                pattern = f"%{query}%"
                q = q.filter(
                    or_(Epic.title.ilike(pattern), Epic.description.ilike(pattern))
                )

            epics = q.order_by(Epic.created_at.desc()).limit(limit).all()

            completed_count = sum(1 for e in epics if e.status == "completed")
            failed_count = sum(1 for e in epics if e.status == "failed")
            finished = completed_count + failed_count
            success_rate = (completed_count / finished) if finished > 0 else None
            costs = [float(e.spent_usd) for e in epics if e.spent_usd is not None]
            avg_cost = (sum(costs) / len(costs)) if costs else 0.0

            results = [
                {
                    "epic_id": e.id,
                    "title": e.title,
                    "status": e.status,
                    "tags": e.tags or [],
                }
                for e in epics
            ]
            return json.dumps({
                "success": True,
                "results": results,
                "success_rate": success_rate,
                "avg_cost": avg_cost,
            })
        except Exception as e:
            logger.exception("Error searching epics")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    return [create_epic, epic_status, update_epic, search_epics]
