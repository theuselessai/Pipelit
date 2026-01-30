"""Tests for OutputDelivery."""

from unittest.mock import MagicMock, patch

import pytest

from apps.workflows.delivery import OutputDelivery


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


class TestSendTelegramMessage:
    def test_sends_with_markdown(self):
        delivery = OutputDelivery()
        with patch("apps.workflows.delivery.requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"ok": True}
            mock_req.post.return_value = mock_resp

            result = delivery.send_telegram_message("TOKEN", 123, "Hello")

        assert result == {"ok": True}
        call_args = mock_req.post.call_args
        assert "TOKEN" in call_args[0][0]
        assert call_args[1]["json"]["parse_mode"] == "Markdown"

    def test_retries_without_markdown_on_failure(self):
        delivery = OutputDelivery()
        import requests as real_requests

        with patch("apps.workflows.delivery.requests") as mock_req:
            # First call fails, second succeeds
            fail_resp = MagicMock()
            fail_resp.raise_for_status.side_effect = real_requests.RequestException("bad markdown")
            ok_resp = MagicMock()
            ok_resp.raise_for_status.return_value = None
            ok_resp.json.return_value = {"ok": True}
            mock_req.post.side_effect = [fail_resp, ok_resp]
            mock_req.RequestException = real_requests.RequestException

            result = delivery.send_telegram_message("TOKEN", 123, "**bold**")

        assert result == {"ok": True}
        assert mock_req.post.call_count == 2
        # Second call should not have parse_mode
        second_call_data = mock_req.post.call_args_list[1][1]["json"]
        assert "parse_mode" not in second_call_data

    def test_reply_to(self):
        delivery = OutputDelivery()
        with patch("apps.workflows.delivery.requests") as mock_req:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"ok": True}
            mock_req.post.return_value = mock_resp

            delivery.send_telegram_message("TOKEN", 123, "Hi", reply_to=42)

        data = mock_req.post.call_args[1]["json"]
        assert data["reply_to_message_id"] == 42


class TestSendLongMessage:
    def test_splits_long_messages(self):
        delivery = OutputDelivery()
        long_text = "A" * 5000  # Exceeds 4096 limit

        with patch.object(delivery, "send_telegram_message") as mock_send:
            delivery._send_long_message("TOKEN", 123, long_text)

        assert mock_send.call_count == 2
        # First chunk gets reply_to
        assert mock_send.call_args_list[0][1].get("reply_to") is None

    def test_short_message_not_split(self):
        delivery = OutputDelivery()

        with patch.object(delivery, "send_telegram_message") as mock_send:
            delivery._send_long_message("TOKEN", 123, "short")

        mock_send.assert_called_once()


@pytest.mark.django_db
class TestDeliver:
    def test_deliver_sends_to_chat(self, workflow_with_telegram):
        from apps.workflows.models import WorkflowExecution
        from apps.users.models import UserProfile

        profile = workflow_with_telegram.owner
        execution = WorkflowExecution.objects.create(
            workflow=workflow_with_telegram,
            user_profile=profile,
            thread_id="t1",
            status="completed",
            trigger_payload={"chat_id": 999, "message_id": 5},
            final_output={"message": "Result here"},
        )

        delivery = OutputDelivery()
        with patch.object(delivery, "send_telegram_message") as mock_send:
            delivery.deliver(execution)

        mock_send.assert_called()
        args = mock_send.call_args[0]
        assert args[1] == 999  # chat_id
        assert "Result here" in args[2]

    def test_deliver_skips_without_chat_id(self, workflow_with_telegram):
        from apps.workflows.models import WorkflowExecution

        execution = WorkflowExecution.objects.create(
            workflow=workflow_with_telegram,
            user_profile=workflow_with_telegram.owner,
            thread_id="t2",
            status="completed",
            trigger_payload={},
            final_output={"message": "Result"},
        )

        delivery = OutputDelivery()
        with patch.object(delivery, "send_telegram_message") as mock_send:
            delivery.deliver(execution)

        mock_send.assert_not_called()
