"""HTTP client for the msg-gateway admin and send APIs."""

from __future__ import annotations

import logging

import requests

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GatewayUnavailableError(Exception):
    """Raised when the gateway is unreachable (connection refused, DNS failure, etc.)."""


class GatewayAPIError(Exception):
    """Raised when the gateway returns an HTTP 4xx/5xx error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Gateway API error {status_code}: {message}")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_TIMEOUT = 30


class GatewayClient:
    """Thin HTTP client wrapping msg-gateway admin + send endpoints."""

    def __init__(self, gateway_url: str, admin_token: str, send_token: str) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.admin_token = admin_token
        self.send_token = send_token

    # -- helpers ------------------------------------------------------------

    def _admin_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.admin_token}"}

    def _send_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.send_token}"}

    def _handle_response(self, resp: requests.Response) -> dict:
        """Raise GatewayAPIError on 4xx/5xx, otherwise return parsed JSON."""
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            try:
                body = resp.json()
                msg = body.get("error", str(body))
            except Exception:
                msg = f"HTTP {resp.status_code}"
            raise GatewayAPIError(resp.status_code, msg)
        return resp.json()

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict | None = None,
        files: dict | None = None,
    ) -> dict:
        """Execute an HTTP request, translating connection errors."""
        try:
            fn = getattr(requests, method)
            kwargs: dict = {"headers": headers, "timeout": _TIMEOUT}
            if json is not None:
                kwargs["json"] = json
            if files is not None:
                kwargs["files"] = files
            resp = fn(url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            raise GatewayUnavailableError(str(exc)) from exc
        return self._handle_response(resp)

    # -- send API (Bearer SEND_TOKEN) ----------------------------------------

    def send_message(
        self,
        credential_id: str,
        chat_id: str,
        text: str,
        reply_to_message_id: str | None = None,
        file_ids: list | None = None,
        extra_data: dict | None = None,
    ) -> dict:
        """POST /api/v1/send — send a message via the gateway."""
        body: dict = {
            "credential_id": credential_id,
            "chat_id": chat_id,
            "text": text,
        }
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = reply_to_message_id
        if file_ids is not None:
            body["file_ids"] = file_ids
        if extra_data is not None:
            body["extra_data"] = extra_data

        return self._request(
            "post",
            f"{self.gateway_url}/api/v1/send",
            headers=self._send_headers(),
            json=body,
        )

    def upload_file(self, data: bytes, filename: str, mime_type: str) -> str:
        """POST /api/v1/files (multipart) — upload a file, return file_id."""
        result = self._request(
            "post",
            f"{self.gateway_url}/api/v1/files",
            headers=self._send_headers(),
            files={"file": (filename, data, mime_type)},
        )
        return result["file_id"]

    # -- admin API (Bearer ADMIN_TOKEN) --------------------------------------

    def create_credential(
        self,
        id: str,
        adapter: str,
        token: str,
        config: dict | None = None,
        route: str | None = None,
        active: bool = False,
    ) -> dict:
        """POST /admin/credentials — register a new credential on the gateway."""
        body: dict = {
            "id": id,
            "adapter": adapter,
            "token": token,
            "active": active,
        }
        if config is not None:
            body["config"] = config
        if route is not None:
            body["route"] = route

        return self._request(
            "post",
            f"{self.gateway_url}/admin/credentials",
            headers=self._admin_headers(),
            json=body,
        )

    def update_credential(self, id: str, **kwargs) -> dict:
        """PUT /admin/credentials/{id} — update credential fields."""
        return self._request(
            "put",
            f"{self.gateway_url}/admin/credentials/{id}",
            headers=self._admin_headers(),
            json=kwargs,
        )

    def delete_credential(self, id: str) -> dict:
        """DELETE /admin/credentials/{id} — remove a credential."""
        return self._request(
            "delete",
            f"{self.gateway_url}/admin/credentials/{id}",
            headers=self._admin_headers(),
        )

    def activate_credential(self, id: str) -> dict:
        """PATCH /admin/credentials/{id}/activate — start polling/webhook."""
        return self._request(
            "patch",
            f"{self.gateway_url}/admin/credentials/{id}/activate",
            headers=self._admin_headers(),
        )

    def deactivate_credential(self, id: str) -> dict:
        """PATCH /admin/credentials/{id}/deactivate — stop polling/webhook."""
        return self._request(
            "patch",
            f"{self.gateway_url}/admin/credentials/{id}/deactivate",
            headers=self._admin_headers(),
        )

    def check_credential_health(self, credential_id: str | None = None) -> dict | None:
        """GET /admin/health — check adapter health status.

        If credential_id is given, return the matching adapter entry (or None).
        If no credential_id, return the full response.
        """
        result = self._request(
            "get",
            f"{self.gateway_url}/admin/health",
            headers=self._admin_headers(),
        )

        if credential_id is None:
            return result

        for adapter in result.get("adapters", []):
            if adapter.get("credential_id") == credential_id:
                return adapter
        return None


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_gateway_client: GatewayClient | None = None


def get_gateway_client() -> GatewayClient:
    """Return the module-level GatewayClient singleton, creating it on first call."""
    global _gateway_client
    if _gateway_client is None:
        _gateway_client = GatewayClient(
            gateway_url=settings.GATEWAY_URL,
            admin_token=settings.GATEWAY_ADMIN_TOKEN,
            send_token=settings.GATEWAY_SEND_TOKEN,
        )
    return _gateway_client
