"""OutputDelivery — send workflow results back to the user."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MESSAGE_LENGTH = 4096


class OutputDelivery:
    """Delivers workflow execution results to the appropriate channel."""

    def deliver(self, execution) -> None:
        """Deliver execution results based on trigger type.

        Args:
            execution: WorkflowExecution instance (must have final_output populated).
        """
        payload = execution.trigger_payload or {}
        chat_id = payload.get("chat_id")

        if not chat_id:
            logger.debug("No chat_id in trigger payload, skipping delivery")
            return

        bot_token = self._resolve_bot_token(execution)
        if not bot_token:
            logger.warning(
                "No bot token for execution %s, cannot deliver",
                execution.execution_id,
            )
            return

        text = self._format_output(execution.final_output)
        if not text:
            logger.debug("No output text for execution %s", execution.execution_id)
            return

        reply_to = payload.get("message_id")
        self._send_long_message(bot_token, chat_id, text, reply_to=reply_to)

    def send_telegram_message(
        self,
        bot_token: str,
        chat_id: int,
        text: str,
        reply_to: int | None = None,
    ) -> dict | None:
        """Send a single Telegram message via Bot API.

        Returns:
            Response JSON or None on failure.
        """
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if reply_to:
            data["reply_to_message_id"] = reply_to

        try:
            resp = requests.post(url, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            # Retry without parse_mode in case of markdown issues
            data.pop("parse_mode", None)
            try:
                resp = requests.post(url, json=data, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                logger.exception("Failed to send Telegram message to chat %s", chat_id)
                return None

    def send_typing_action(self, bot_token: str, chat_id: int) -> None:
        """Send typing indicator to Telegram chat."""
        url = f"https://api.telegram.org/bot{bot_token}/sendChatAction"
        try:
            requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=10)
        except requests.RequestException:
            pass

    def _send_long_message(
        self,
        bot_token: str,
        chat_id: int,
        text: str,
        reply_to: int | None = None,
    ) -> None:
        """Split and send messages exceeding Telegram's limit."""
        if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            self.send_telegram_message(bot_token, chat_id, text, reply_to=reply_to)
            return

        chunks = []
        while text:
            if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
                chunks.append(text)
                break
            # Try to split at newline
            split_at = text.rfind("\n", 0, MAX_TELEGRAM_MESSAGE_LENGTH)
            if split_at == -1:
                split_at = MAX_TELEGRAM_MESSAGE_LENGTH
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")

        for i, chunk in enumerate(chunks):
            self.send_telegram_message(
                bot_token, chat_id, chunk, reply_to=reply_to if i == 0 else None
            )

    def _resolve_bot_token(self, execution) -> str | None:
        """Get bot token from the execution's trigger node credential."""
        trigger_node = execution.trigger_node
        if not trigger_node:
            return None
        try:
            concrete = trigger_node.component_config.concrete
            if not concrete or not getattr(concrete, "credential_id", None):
                return None
            return concrete.credential.telegram_credential.bot_token
        except Exception:
            logger.exception(
                "Failed to resolve bot token for execution %s",
                execution.execution_id,
            )
            return None

    def _format_output(self, final_output: dict | None) -> str:
        """Convert final_output dict to a sendable text string."""
        if not final_output:
            return ""
        if "message" in final_output:
            return str(final_output["message"])
        if "output" in final_output:
            output = final_output["output"]
            return str(output) if not isinstance(output, str) else output
        if "node_outputs" in final_output:
            parts = []
            for node_id, value in final_output["node_outputs"].items():
                parts.append(f"**{node_id}**: {value}")
            return "\n\n".join(parts)
        return str(final_output)


# Module-level singleton
output_delivery = OutputDelivery()
