"""TriggerResolver — matches events to workflow trigger nodes."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Maps event types to component types
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
    """Resolves incoming events to the appropriate Workflow + trigger WorkflowNode."""

    def resolve(
        self, event_type: str, event_data: dict
    ) -> tuple | None:
        """Find the best matching (Workflow, WorkflowNode) for an event.

        Args:
            event_type: Trigger type string (e.g., "telegram_chat", "webhook").
            event_data: Event payload dict.

        Returns:
            Tuple of (Workflow, WorkflowNode) or None if no match.
        """
        from apps.workflows.models import Workflow, WorkflowNode
        from apps.workflows.models.node import TriggerComponentConfig

        component_type = EVENT_TYPE_TO_COMPONENT.get(event_type)
        if not component_type:
            logger.debug("Unknown event type '%s'", event_type)
            return None

        # Query active trigger nodes of this component type
        trigger_nodes = (
            WorkflowNode.objects.filter(
                component_type=component_type,
                workflow__is_active=True,
                workflow__deleted_at__isnull=True,
            )
            .select_related("workflow", "component_config")
            .order_by("id")
        )

        # Filter by is_active on the concrete config and sort by priority
        candidates = []
        for node in trigger_nodes:
            concrete = node.component_config.concrete
            if isinstance(concrete, TriggerComponentConfig) and concrete.is_active:
                candidates.append((concrete.priority, node))

        # Sort by priority descending, then id ascending
        candidates.sort(key=lambda x: (-x[0], x[1].id))

        for _priority, node in candidates:
            concrete = node.component_config.concrete
            if self._matches(concrete, event_type, event_data):
                logger.info(
                    "Resolved event '%s' to workflow '%s' (node %s)",
                    event_type,
                    node.workflow.slug,
                    node.node_id,
                )
                return (node.workflow, node)

        # Fall back to default workflow
        default_workflow = (
            Workflow.objects.filter(is_active=True, is_default=True, deleted_at__isnull=True)
            .first()
        )
        if default_workflow:
            default_trigger = (
                default_workflow.nodes.filter(
                    component_type=component_type,
                )
                .first()
            )
            if default_trigger:
                logger.info("Fell back to default workflow '%s'", default_workflow.slug)
                return (default_workflow, default_trigger)

        logger.debug("No workflow matched event '%s'", event_type)
        return None

    def _matches(self, config, event_type: str, event_data: dict) -> bool:
        """Check if a trigger config matches the event data."""
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
        """Match telegram triggers by pattern, command, or user filtering."""
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
        """Match webhook triggers by path or secret."""
        expected_path = config.get("path")
        if expected_path:
            return event_data.get("path") == expected_path
        return True


# Module-level singleton
trigger_resolver = TriggerResolver()
