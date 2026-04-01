"""JWT issuer service — mints short-lived ES256 tokens for agentgateway."""

from __future__ import annotations

import time
import uuid

import jwt

from config import settings

_TOKEN_LIFETIME_SECONDS = 60
_KID = "pipelit-001"


class JWTIssuerError(Exception):
    """Raised when token minting fails (e.g. missing or invalid private key)."""


def mint_llm_token(
    user_profile_id: int,
    role: str,
    credential_id: int,
    allowed_credentials: list[int] | None = None,
) -> str:
    """Mint a short-lived ES256 JWT for a single LLM request through agentgateway.

    Parameters
    ----------
    user_profile_id:
        ``UserProfile.id`` — becomes the ``sub`` claim (as string per JWT convention).
    role:
        User role, e.g. ``"admin"`` or ``"normal"``.
    credential_id:
        ``BaseCredential.id`` of the credential used for this request.
    allowed_credentials:
        All credential IDs accessible to this user.  Omitted from the token when *None*.

    Returns
    -------
    str
        Encoded JWT string.

    Raises
    ------
    JWTIssuerError
        If ``JWT_PRIVATE_KEY`` is empty or the key cannot be loaded.
    """
    private_key_pem = settings.JWT_PRIVATE_KEY
    if not private_key_pem:
        raise JWTIssuerError(
            "JWT_PRIVATE_KEY is not configured. "
            "Run 'plit init' to generate the ES256 key pair."
        )

    now = int(time.time())
    payload: dict = {
        "iss": "pipelit",
        "aud": "agentgateway",
        "sub": str(user_profile_id),
        "iat": now,
        "exp": now + _TOKEN_LIFETIME_SECONDS,
        "jti": str(uuid.uuid4()),
        "role": role,
        "credential_id": credential_id,
    }
    if allowed_credentials is not None:
        payload["allowed_credentials"] = allowed_credentials

    headers = {"kid": _KID}

    try:
        return jwt.encode(payload, private_key_pem, algorithm="ES256", headers=headers)
    except Exception as exc:
        raise JWTIssuerError(f"Failed to sign JWT: {exc}") from exc
