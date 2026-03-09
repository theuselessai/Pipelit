"""Tests for GatewayClient — HTTP client for msg-gateway admin/send APIs."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests


# ---------------------------------------------------------------------------
# Import targets (will fail until implementation exists)
# ---------------------------------------------------------------------------

from services.gateway_client import (
    GatewayAPIError,
    GatewayClient,
    GatewayUnavailableError,
    get_gateway_client,
)

GATEWAY_URL = "http://gateway.test:9000"
ADMIN_TOKEN = "admin-secret"
SEND_TOKEN = "send-secret"


@pytest.fixture()
def client() -> GatewayClient:
    return GatewayClient(
        gateway_url=GATEWAY_URL,
        admin_token=ADMIN_TOKEN,
        send_token=SEND_TOKEN,
    )


def _ok_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def _error_response(status_code: int, error_msg: str) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = {"error": error_msg}
    resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


# ===================================================================
# send_message
# ===================================================================


class TestSendMessage:
    @patch("services.gateway_client.requests.post")
    def test_happy_path(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.return_value = _ok_response({"status": "sent", "message_id": "m1"})

        result = client.send_message(
            credential_id="cred-1",
            chat_id="chat-42",
            text="Hello!",
        )

        mock_post.assert_called_once_with(
            f"{GATEWAY_URL}/api/v1/send",
            json={"credential_id": "cred-1", "chat_id": "chat-42", "text": "Hello!"},
            headers={"Authorization": f"Bearer {SEND_TOKEN}"},
            timeout=30,
        )
        assert result == {"status": "sent", "message_id": "m1"}

    @patch("services.gateway_client.requests.post")
    def test_with_optional_fields(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.return_value = _ok_response({"status": "sent"})

        client.send_message(
            credential_id="cred-1",
            chat_id="chat-42",
            text="Reply",
            reply_to_message_id="msg-99",
            file_ids=["f1", "f2"],
            extra_data={"parse_mode": "markdown"},
        )

        body = mock_post.call_args[1]["json"]
        assert body["reply_to_message_id"] == "msg-99"
        assert body["file_ids"] == ["f1", "f2"]
        assert body["extra_data"] == {"parse_mode": "markdown"}

    @patch("services.gateway_client.requests.post")
    def test_connection_error(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")

        with pytest.raises(GatewayUnavailableError):
            client.send_message(credential_id="c", chat_id="x", text="hi")

    @patch("services.gateway_client.requests.post")
    def test_http_4xx(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.return_value = _error_response(422, "invalid credential_id")

        with pytest.raises(GatewayAPIError) as exc_info:
            client.send_message(credential_id="bad", chat_id="x", text="hi")

        assert exc_info.value.status_code == 422
        assert "invalid credential_id" in exc_info.value.message

    @patch("services.gateway_client.requests.post")
    def test_http_5xx(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.return_value = _error_response(500, "internal error")

        with pytest.raises(GatewayAPIError) as exc_info:
            client.send_message(credential_id="c", chat_id="x", text="hi")

        assert exc_info.value.status_code == 500


# ===================================================================
# upload_file
# ===================================================================


class TestUploadFile:
    @patch("services.gateway_client.requests.post")
    def test_happy_path(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.return_value = _ok_response({"file_id": "file-abc", "filename": "pic.png"})

        result = client.upload_file(data=b"\x89PNG", filename="pic.png", mime_type="image/png")

        assert result == "file-abc"
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["headers"] == {"Authorization": f"Bearer {SEND_TOKEN}"}
        assert "files" in call_kwargs
        assert mock_post.call_args[0][0] == f"{GATEWAY_URL}/api/v1/files"

    @patch("services.gateway_client.requests.post")
    def test_connection_error(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(GatewayUnavailableError):
            client.upload_file(data=b"data", filename="f.txt", mime_type="text/plain")

    @patch("services.gateway_client.requests.post")
    def test_http_error(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.return_value = _error_response(413, "file too large")

        with pytest.raises(GatewayAPIError) as exc_info:
            client.upload_file(data=b"x" * 999, filename="big.bin", mime_type="application/octet-stream")

        assert exc_info.value.status_code == 413


# ===================================================================
# create_credential
# ===================================================================


class TestCreateCredential:
    @patch("services.gateway_client.requests.post")
    def test_happy_path(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.return_value = _ok_response({"id": "cred-1", "status": "created"})

        result = client.create_credential(id="cred-1", adapter="telegram", token="bot123")

        mock_post.assert_called_once_with(
            f"{GATEWAY_URL}/admin/credentials",
            json={"id": "cred-1", "adapter": "telegram", "token": "bot123", "active": False},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=30,
        )
        assert result == {"id": "cred-1", "status": "created"}

    @patch("services.gateway_client.requests.post")
    def test_with_optional_fields(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.return_value = _ok_response({"id": "c2", "status": "created"})

        client.create_credential(
            id="c2",
            adapter="discord",
            token="tok",
            config={"guild_id": "123"},
            route="/inbound",
            active=True,
        )

        body = mock_post.call_args[1]["json"]
        assert body["config"] == {"guild_id": "123"}
        assert body["route"] == "/inbound"
        assert body["active"] is True

    @patch("services.gateway_client.requests.post")
    def test_connection_error(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(GatewayUnavailableError):
            client.create_credential(id="x", adapter="telegram", token="t")

    @patch("services.gateway_client.requests.post")
    def test_http_409_conflict(self, mock_post: MagicMock, client: GatewayClient) -> None:
        mock_post.return_value = _error_response(409, "credential already exists")

        with pytest.raises(GatewayAPIError) as exc_info:
            client.create_credential(id="dup", adapter="telegram", token="t")

        assert exc_info.value.status_code == 409


# ===================================================================
# update_credential
# ===================================================================


class TestUpdateCredential:
    @patch("services.gateway_client.requests.put")
    def test_happy_path(self, mock_put: MagicMock, client: GatewayClient) -> None:
        mock_put.return_value = _ok_response({"id": "cred-1", "status": "updated"})

        result = client.update_credential(id="cred-1", token="new-token")

        mock_put.assert_called_once_with(
            f"{GATEWAY_URL}/admin/credentials/cred-1",
            json={"token": "new-token"},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=30,
        )
        assert result == {"id": "cred-1", "status": "updated"}

    @patch("services.gateway_client.requests.put")
    def test_connection_error(self, mock_put: MagicMock, client: GatewayClient) -> None:
        mock_put.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(GatewayUnavailableError):
            client.update_credential(id="x", adapter="telegram")

    @patch("services.gateway_client.requests.put")
    def test_http_404(self, mock_put: MagicMock, client: GatewayClient) -> None:
        mock_put.return_value = _error_response(404, "credential not found")

        with pytest.raises(GatewayAPIError) as exc_info:
            client.update_credential(id="missing")

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.message


# ===================================================================
# delete_credential
# ===================================================================


class TestDeleteCredential:
    @patch("services.gateway_client.requests.delete")
    def test_happy_path(self, mock_delete: MagicMock, client: GatewayClient) -> None:
        mock_delete.return_value = _ok_response({"id": "cred-1", "status": "deleted"})

        result = client.delete_credential(id="cred-1")

        mock_delete.assert_called_once_with(
            f"{GATEWAY_URL}/admin/credentials/cred-1",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=30,
        )
        assert result == {"id": "cred-1", "status": "deleted"}

    @patch("services.gateway_client.requests.delete")
    def test_connection_error(self, mock_delete: MagicMock, client: GatewayClient) -> None:
        mock_delete.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(GatewayUnavailableError):
            client.delete_credential(id="x")

    @patch("services.gateway_client.requests.delete")
    def test_http_404(self, mock_delete: MagicMock, client: GatewayClient) -> None:
        mock_delete.return_value = _error_response(404, "not found")

        with pytest.raises(GatewayAPIError) as exc_info:
            client.delete_credential(id="gone")

        assert exc_info.value.status_code == 404


# ===================================================================
# activate_credential
# ===================================================================


class TestActivateCredential:
    @patch("services.gateway_client.requests.patch")
    def test_happy_path(self, mock_patch: MagicMock, client: GatewayClient) -> None:
        mock_patch.return_value = _ok_response({"id": "cred-1", "status": "activated"})

        result = client.activate_credential(id="cred-1")

        mock_patch.assert_called_once_with(
            f"{GATEWAY_URL}/admin/credentials/cred-1/activate",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=30,
        )
        assert result == {"id": "cred-1", "status": "activated"}

    @patch("services.gateway_client.requests.patch")
    def test_connection_error(self, mock_patch: MagicMock, client: GatewayClient) -> None:
        mock_patch.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(GatewayUnavailableError):
            client.activate_credential(id="x")

    @patch("services.gateway_client.requests.patch")
    def test_http_error(self, mock_patch: MagicMock, client: GatewayClient) -> None:
        mock_patch.return_value = _error_response(500, "adapter crash")

        with pytest.raises(GatewayAPIError) as exc_info:
            client.activate_credential(id="bad")

        assert exc_info.value.status_code == 500


# ===================================================================
# deactivate_credential
# ===================================================================


class TestDeactivateCredential:
    @patch("services.gateway_client.requests.patch")
    def test_happy_path(self, mock_patch: MagicMock, client: GatewayClient) -> None:
        mock_patch.return_value = _ok_response({"id": "cred-1", "status": "deactivated"})

        result = client.deactivate_credential(id="cred-1")

        mock_patch.assert_called_once_with(
            f"{GATEWAY_URL}/admin/credentials/cred-1/deactivate",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=30,
        )
        assert result == {"id": "cred-1", "status": "deactivated"}

    @patch("services.gateway_client.requests.patch")
    def test_connection_error(self, mock_patch: MagicMock, client: GatewayClient) -> None:
        mock_patch.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(GatewayUnavailableError):
            client.deactivate_credential(id="x")

    @patch("services.gateway_client.requests.patch")
    def test_http_error(self, mock_patch: MagicMock, client: GatewayClient) -> None:
        mock_patch.return_value = _error_response(400, "already inactive")

        with pytest.raises(GatewayAPIError) as exc_info:
            client.deactivate_credential(id="x")

        assert exc_info.value.status_code == 400


# ===================================================================
# check_credential_health
# ===================================================================


class TestCheckCredentialHealth:
    @patch("services.gateway_client.requests.get")
    def test_full_response(self, mock_get: MagicMock, client: GatewayClient) -> None:
        health_data = {
            "adapters": [
                {"credential_id": "c1", "adapter": "telegram", "health": "ok", "failures": 0},
                {"credential_id": "c2", "adapter": "discord", "health": "degraded", "failures": 3},
            ]
        }
        mock_get.return_value = _ok_response(health_data)

        result = client.check_credential_health()

        mock_get.assert_called_once_with(
            f"{GATEWAY_URL}/admin/health",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=30,
        )
        assert result == health_data

    @patch("services.gateway_client.requests.get")
    def test_specific_credential_found(self, mock_get: MagicMock, client: GatewayClient) -> None:
        health_data = {
            "adapters": [
                {"credential_id": "c1", "adapter": "telegram", "health": "ok", "failures": 0},
                {"credential_id": "c2", "adapter": "discord", "health": "degraded", "failures": 3},
            ]
        }
        mock_get.return_value = _ok_response(health_data)

        result = client.check_credential_health(credential_id="c2")

        assert result == {"credential_id": "c2", "adapter": "discord", "health": "degraded", "failures": 3}

    @patch("services.gateway_client.requests.get")
    def test_specific_credential_not_found(self, mock_get: MagicMock, client: GatewayClient) -> None:
        health_data = {
            "adapters": [
                {"credential_id": "c1", "adapter": "telegram", "health": "ok", "failures": 0},
            ]
        }
        mock_get.return_value = _ok_response(health_data)

        result = client.check_credential_health(credential_id="nonexistent")

        assert result is None

    @patch("services.gateway_client.requests.get")
    def test_connection_error(self, mock_get: MagicMock, client: GatewayClient) -> None:
        mock_get.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(GatewayUnavailableError):
            client.check_credential_health()

    @patch("services.gateway_client.requests.get")
    def test_http_error(self, mock_get: MagicMock, client: GatewayClient) -> None:
        mock_get.return_value = _error_response(503, "service unavailable")

        with pytest.raises(GatewayAPIError) as exc_info:
            client.check_credential_health()

        assert exc_info.value.status_code == 503


# ===================================================================
# get_gateway_client (lazy singleton)
# ===================================================================


class TestGetGatewayClient:
    def test_lazy_singleton(self) -> None:
        """get_gateway_client() returns the same instance on repeated calls."""
        import services.gateway_client as mod

        # Reset singleton
        mod._gateway_client = None

        with patch.object(mod, "settings") as mock_settings:
            mock_settings.GATEWAY_URL = GATEWAY_URL
            mock_settings.GATEWAY_ADMIN_TOKEN = ADMIN_TOKEN
            mock_settings.GATEWAY_SEND_TOKEN = SEND_TOKEN

            c1 = get_gateway_client()
            c2 = get_gateway_client()

            assert c1 is c2
            assert isinstance(c1, GatewayClient)

        # Cleanup
        mod._gateway_client = None

    def test_creates_from_settings(self) -> None:
        """get_gateway_client() reads from settings on first call."""
        import services.gateway_client as mod

        mod._gateway_client = None

        with patch.object(mod, "settings") as mock_settings:
            mock_settings.GATEWAY_URL = "http://gw:1234"
            mock_settings.GATEWAY_ADMIN_TOKEN = "adm"
            mock_settings.GATEWAY_SEND_TOKEN = "snd"

            c = get_gateway_client()

            assert c.gateway_url == "http://gw:1234"
            assert c.admin_token == "adm"
            assert c.send_token == "snd"

        mod._gateway_client = None


# ===================================================================
# Exception classes
# ===================================================================


class TestExceptions:
    def test_gateway_unavailable_error(self) -> None:
        err = GatewayUnavailableError("connection refused")
        assert "connection refused" in str(err)
        assert isinstance(err, Exception)

    def test_gateway_api_error(self) -> None:
        err = GatewayAPIError(422, "bad request body")
        assert err.status_code == 422
        assert err.message == "bad request body"
        assert "422" in str(err)
        assert "bad request body" in str(err)
