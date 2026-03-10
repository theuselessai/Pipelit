"""OutputDelivery — send workflow results back to the user via msg-gateway."""

from __future__ import annotations

import logging

from services.gateway_client import GatewayAPIError, GatewayUnavailableError, get_gateway_client

logger = logging.getLogger(__name__)


class OutputDelivery:

    def deliver(self, execution) -> None:
        payload = execution.trigger_payload or {}
        credential_id = payload.get("credential_id")
        chat_id = payload.get("chat_id")

        if not credential_id or not chat_id:
            return

        text = self._format_output(execution.final_output)
        if not text:
            return

        try:
            get_gateway_client().send_message(credential_id, chat_id, text, file_ids=[])
        except (GatewayAPIError, GatewayUnavailableError) as exc:
            logger.warning(
                "Failed to deliver output via gateway for execution %s: %s",
                execution.execution_id,
                exc,
            )
        except Exception as exc:
            logger.warning(
                "Unexpected error delivering output for execution %s: %s",
                execution.execution_id,
                exc,
            )

    def send_typing_action(self, *args, **kwargs) -> None:
        """No-op stub — typing actions are handled by the gateway."""

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
