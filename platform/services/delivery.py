"""OutputDelivery — send workflow results back to the user."""

from __future__ import annotations

import logging

import requests
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MESSAGE_LENGTH = 4096


class OutputDelivery:

    def deliver(self, execution, db: Session) -> None:
        payload = execution.trigger_payload or {}
        chat_id = payload.get("chat_id")
        if not chat_id:
            return

        bot_token = self._resolve_bot_token(execution, db)
        if not bot_token:
            return

        text = self._format_output(execution.final_output)
        if not text:
            return

        reply_to = payload.get("message_id")
        self._send_long_message(bot_token, chat_id, text, reply_to=reply_to)

    def send_telegram_message(self, bot_token: str, chat_id: int, text: str, reply_to: int | None = None) -> dict | None:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_to:
            data["reply_to_message_id"] = reply_to
        try:
            resp = requests.post(url, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            data.pop("parse_mode", None)
            try:
                resp = requests.post(url, json=data, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                logger.exception("Failed to send Telegram message to chat %s", chat_id)
                return None

    def send_typing_action(self, bot_token: str, chat_id: int) -> None:
        url = f"https://api.telegram.org/bot{bot_token}/sendChatAction"
        try:
            requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=10)
        except requests.RequestException:
            pass

    def _send_long_message(self, bot_token: str, chat_id: int, text: str, reply_to: int | None = None) -> None:
        if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            self.send_telegram_message(bot_token, chat_id, text, reply_to=reply_to)
            return
        chunks = []
        while text:
            if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, MAX_TELEGRAM_MESSAGE_LENGTH)
            if split_at == -1:
                split_at = MAX_TELEGRAM_MESSAGE_LENGTH
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        for i, chunk in enumerate(chunks):
            self.send_telegram_message(bot_token, chat_id, chunk, reply_to=reply_to if i == 0 else None)

    def _resolve_bot_token(self, execution, db: Session) -> str | None:
        if not execution.trigger_node_id:
            return None
        try:
            from models.node import WorkflowNode
            trigger_node = db.query(WorkflowNode).filter(WorkflowNode.id == execution.trigger_node_id).first()
            if not trigger_node:
                return None
            cc = trigger_node.component_config
            if not cc.credential_id:
                return None
            from models.credential import BaseCredential
            cred = db.query(BaseCredential).filter(BaseCredential.id == cc.credential_id).first()
            if cred and cred.telegram_credential:
                return cred.telegram_credential.bot_token
        except Exception:
            logger.exception("Failed to resolve bot token for execution %s", execution.execution_id)
        return None

    def _format_output(self, final_output: dict | None) -> str:
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


output_delivery = OutputDelivery()
