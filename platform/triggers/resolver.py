"""TriggerResolver — matches events to workflow trigger nodes."""

from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EVENT_TYPE_TO_COMPONENT = {
    "telegram_message": "trigger_telegram",
    "telegram_chat": "trigger_telegram",
    "webhook": "trigger_webhook",
    "schedule": "trigger_schedule",
    "manual": "trigger_manual",
    "workflow": "trigger_workflow",
    "error": "trigger_error",
}


class TriggerResolver:

    def resolve(self, event_type: str, event_data: dict, db: Session) -> tuple | None:
        from models.node import WorkflowNode
        from models.workflow import Workflow

        component_type = EVENT_TYPE_TO_COMPONENT.get(event_type)
        if not component_type:
            return None

        trigger_nodes = (
            db.query(WorkflowNode)
            .join(Workflow, WorkflowNode.workflow_id == Workflow.id)
            .filter(
                WorkflowNode.component_type == component_type,
                Workflow.is_active == True,
                Workflow.deleted_at.is_(None),
            )
            .order_by(WorkflowNode.id)
            .all()
        )

        candidates = []
        for node in trigger_nodes:
            cc = node.component_config
            if cc.component_type.startswith("trigger_") and (cc.is_active is None or cc.is_active):
                candidates.append((cc.priority or 0, node))

        candidates.sort(key=lambda x: (-x[0], x[1].id))

        for _priority, node in candidates:
            cc = node.component_config
            if self._matches(cc, event_type, event_data):
                workflow = db.query(Workflow).filter(Workflow.id == node.workflow_id).first()
                return (workflow, node)

        # Fall back to default workflow
        default_workflow = (
            db.query(Workflow)
            .filter(Workflow.is_active == True, Workflow.is_default == True, Workflow.deleted_at.is_(None))
            .first()
        )
        if default_workflow:
            default_trigger = (
                db.query(WorkflowNode)
                .filter(WorkflowNode.workflow_id == default_workflow.id, WorkflowNode.component_type == component_type)
                .first()
            )
            if default_trigger:
                return (default_workflow, default_trigger)

        return None

    def _matches(self, config, event_type: str, event_data: dict) -> bool:
        trigger_config = config.trigger_config or {}

        if event_type in ("telegram_message", "telegram_chat"):
            return self._match_telegram(trigger_config, event_data)
        if event_type == "webhook":
            return self._match_webhook(trigger_config, event_data)
        if event_type == "manual":
            return True
        if event_type == "workflow":
            source = trigger_config.get("source_workflow")
            return source is None or source == event_data.get("source_workflow")
        if event_type == "error":
            return True
        return True

    def _match_telegram(self, config: dict, event_data: dict) -> bool:
        allowed_users = config.get("allowed_user_ids", [])
        if allowed_users:
            user_id = event_data.get("user_id")
            if user_id and user_id not in allowed_users:
                return False
        pattern = config.get("pattern")
        if pattern:
            text = event_data.get("text", "")
            if not re.search(pattern, text, re.IGNORECASE):
                return False
        command = config.get("command")
        if command:
            text = event_data.get("text", "")
            if not text.startswith(f"/{command}"):
                return False
        return True

    def _match_webhook(self, config: dict, event_data: dict) -> bool:
        expected_path = config.get("path")
        if expected_path:
            return event_data.get("path") == expected_path
        return True


trigger_resolver = TriggerResolver()
