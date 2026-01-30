"""TriggerResolver — matches events to workflow triggers."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class TriggerResolver:
    """Resolves incoming events to the appropriate Workflow + WorkflowTrigger."""

    def resolve(
        self, event_type: str, event_data: dict
    ) -> tuple | None:
        """Find the best matching (Workflow, WorkflowTrigger) for an event.

        Args:
            event_type: Trigger type string (e.g., "telegram_message", "webhook").
            event_data: Event payload dict.

        Returns:
            Tuple of (Workflow, WorkflowTrigger) or None if no match.
        """
        from apps.workflows.models import Workflow, WorkflowTrigger

        # Query active triggers of this type, ordered by priority (desc)
        triggers = (
            WorkflowTrigger.objects.filter(
                trigger_type=event_type,
                is_active=True,
                workflow__is_active=True,
                workflow__deleted_at__isnull=True,
            )
            .select_related("workflow")
            .order_by("-priority", "id")
        )

        for trigger in triggers:
            if self._matches(trigger, event_type, event_data):
                logger.info(
                    "Resolved event '%s' to workflow '%s' (trigger %d)",
                    event_type,
                    trigger.workflow.slug,
                    trigger.id,
                )
                return (trigger.workflow, trigger)

        # Fall back to default workflow
        default_workflow = (
            Workflow.objects.filter(is_active=True, is_default=True, deleted_at__isnull=True)
            .first()
        )
        if default_workflow:
            default_trigger = default_workflow.triggers.filter(is_active=True).first()
            if default_trigger:
                logger.info("Fell back to default workflow '%s'", default_workflow.slug)
                return (default_workflow, default_trigger)

        logger.debug("No workflow matched event '%s'", event_type)
        return None

    def _matches(self, trigger, event_type: str, event_data: dict) -> bool:
        """Check if a trigger matches the event data."""
        config = trigger.config or {}

        if event_type in ("telegram_message", "telegram_chat"):
            return self._match_telegram(config, event_data)

        if event_type == "webhook":
            return self._match_webhook(config, event_data)

        if event_type == "manual":
            return True

        if event_type == "workflow":
            source = config.get("source_workflow")
            return source is None or source == event_data.get("source_workflow")

        if event_type == "error":
            return True

        return True

    def _match_telegram(self, config: dict, event_data: dict) -> bool:
        """Match telegram triggers by pattern, command, or user filtering."""
        # Check allowed users
        allowed_users = config.get("allowed_user_ids", [])
        if allowed_users:
            user_id = event_data.get("user_id")
            if user_id and user_id not in allowed_users:
                return False

        # Check message pattern
        pattern = config.get("pattern")
        if pattern:
            text = event_data.get("text", "")
            if not re.search(pattern, text, re.IGNORECASE):
                return False

        # Check command prefix
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
