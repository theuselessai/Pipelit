"""Tests for OutputDelivery."""

from unittest.mock import MagicMock, patch

import pytest

from services.delivery import OutputDelivery


class TestFormatOutput:
    def setup_method(self):
        self.delivery = OutputDelivery()

    def test_none_output(self):
        assert self.delivery._format_output(None) == ""

    def test_message_key(self):
        assert self.delivery._format_output({"message": "Hello"}) == "Hello"

    def test_output_key_string(self):
        assert self.delivery._format_output({"output": "done"}) == "done"

    def test_output_key_dict(self):
        result = self.delivery._format_output({"output": {"key": "val"}})
        assert "key" in result

    def test_node_outputs(self):
        result = self.delivery._format_output({"node_outputs": {"n1": "res1", "n2": "res2"}})
        assert "n1" in result
        assert "n2" in result

    def test_fallback(self):
        result = self.delivery._format_output({"unknown": 42})
        assert "42" in result


class TestDeliver:
    def _make_execution(self, trigger_payload=None, final_output="__default__"):
        execution = MagicMock()
        execution.trigger_payload = trigger_payload or {}
        execution.final_output = {"message": "Result here"} if final_output == "__default__" else final_output
        return execution

    def test_deliver_calls_send_message_with_correct_args(self):
        """Valid execution with credential_id + chat_id → send_message() called."""
        execution = self._make_execution(
            trigger_payload={"credential_id": "cred-123", "chat_id": "456"},
            final_output={"message": "Hello from workflow"},
        )
        delivery = OutputDelivery()
        mock_client = MagicMock()

        with patch("services.delivery.get_gateway_client", return_value=mock_client):
            delivery.deliver(execution)

        mock_client.send_message.assert_called_once_with(
            "cred-123", "456", "Hello from workflow", file_ids=[]
        )

    def test_deliver_skips_without_credential_id(self):
        """Missing credential_id → returns without sending."""
        execution = self._make_execution(
            trigger_payload={"chat_id": "456"},
            final_output={"message": "Result"},
        )
        delivery = OutputDelivery()
        mock_client = MagicMock()

        with patch("services.delivery.get_gateway_client", return_value=mock_client):
            delivery.deliver(execution)

        mock_client.send_message.assert_not_called()

    def test_deliver_skips_without_chat_id(self):
        """Missing chat_id → returns without sending."""
        execution = self._make_execution(
            trigger_payload={"credential_id": "cred-123"},
            final_output={"message": "Result"},
        )
        delivery = OutputDelivery()
        mock_client = MagicMock()

        with patch("services.delivery.get_gateway_client", return_value=mock_client):
            delivery.deliver(execution)

        mock_client.send_message.assert_not_called()

    def test_deliver_skips_empty_payload(self):
        """Empty trigger_payload → returns without sending."""
        execution = self._make_execution(trigger_payload={})
        delivery = OutputDelivery()
        mock_client = MagicMock()

        with patch("services.delivery.get_gateway_client", return_value=mock_client):
            delivery.deliver(execution)

        mock_client.send_message.assert_not_called()

    def test_deliver_gateway_failure_logs_warning_no_raise(self):
        """Gateway failure → warning logged, no exception raised."""
        from services.gateway_client import GatewayAPIError

        execution = self._make_execution(
            trigger_payload={"credential_id": "cred-123", "chat_id": "456"},
            final_output={"message": "Hello"},
        )
        delivery = OutputDelivery()
        mock_client = MagicMock()
        mock_client.send_message.side_effect = GatewayAPIError(500, "Internal error")

        with patch("services.delivery.get_gateway_client", return_value=mock_client):
            with patch("services.delivery.logger") as mock_logger:
                delivery.deliver(execution)

        mock_logger.warning.assert_called()

    def test_deliver_gateway_unavailable_logs_warning_no_raise(self):
        """GatewayUnavailableError → warning logged, no exception raised."""
        from services.gateway_client import GatewayUnavailableError

        execution = self._make_execution(
            trigger_payload={"credential_id": "cred-123", "chat_id": "456"},
            final_output={"message": "Hello"},
        )
        delivery = OutputDelivery()
        mock_client = MagicMock()
        mock_client.send_message.side_effect = GatewayUnavailableError("Connection refused")

        with patch("services.delivery.get_gateway_client", return_value=mock_client):
            with patch("services.delivery.logger") as mock_logger:
                delivery.deliver(execution)

        mock_logger.warning.assert_called()

    def test_deliver_skips_when_no_final_output_text(self):
        """Empty formatted output → returns without sending."""
        execution = self._make_execution(
            trigger_payload={"credential_id": "cred-123", "chat_id": "456"},
            final_output=None,
        )
        delivery = OutputDelivery()
        mock_client = MagicMock()

        with patch("services.delivery.get_gateway_client", return_value=mock_client):
            delivery.deliver(execution)

        mock_client.send_message.assert_not_called()
