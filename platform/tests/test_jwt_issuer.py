"""Tests for services.jwt_issuer — ES256 JWT minting for agentgateway."""

from __future__ import annotations

import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

from services.jwt_issuer import JWTIssuerError, mint_llm_token

# ---------------------------------------------------------------------------
# Fixtures: generate a fresh EC P-256 key pair per test session
# ---------------------------------------------------------------------------

_ec_private_key = ec.generate_private_key(ec.SECP256R1())
_PRIVATE_PEM = _ec_private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_PUBLIC_KEY = _ec_private_key.public_key()


@pytest.fixture(autouse=True)
def _configure_private_key():
    """Inject a test EC private key into settings for every test."""
    with patch("services.jwt_issuer.settings") as mock_settings:
        mock_settings.JWT_PRIVATE_KEY = _PRIVATE_PEM
        yield mock_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode(token: str) -> dict:
    """Decode and validate a token using the test public key."""
    return jwt.decode(
        token,
        _PUBLIC_KEY,
        algorithms=["ES256"],
        audience="agentgateway",
        issuer="pipelit",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMintLLMToken:
    """Valid token generation."""

    def test_produces_decodable_token(self):
        token = mint_llm_token(user_profile_id=42, role="admin", credential_id=7)
        claims = _decode(token)
        assert claims["sub"] == "42"

    def test_required_claims_present(self):
        token = mint_llm_token(
            user_profile_id=42, role="normal", credential_id=7,
            allowed_credentials=[3, 7, 12],
        )
        claims = _decode(token)

        assert claims["iss"] == "pipelit"
        assert claims["aud"] == "agentgateway"
        assert claims["sub"] == "42"
        assert claims["role"] == "normal"
        assert claims["credential_id"] == 7
        assert "iat" in claims
        assert "exp" in claims

    def test_token_expires_after_60_seconds(self):
        before = int(time.time())
        token = mint_llm_token(user_profile_id=1, role="admin", credential_id=1)
        after = int(time.time())

        claims = _decode(token)
        lifetime = claims["exp"] - claims["iat"]
        assert lifetime == 60

        # exp should be roughly now + 60
        assert before + 60 <= claims["exp"] <= after + 60

    def test_es256_algorithm_used(self):
        token = mint_llm_token(user_profile_id=1, role="admin", credential_id=1)
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "ES256"

    def test_kid_header_present(self):
        token = mint_llm_token(user_profile_id=1, role="admin", credential_id=1)
        header = jwt.get_unverified_header(token)
        assert header["kid"] == "pipelit-001"

    def test_jti_is_uuid(self):
        import uuid

        token = mint_llm_token(user_profile_id=1, role="admin", credential_id=1)
        claims = _decode(token)
        # Should not raise
        uuid.UUID(claims["jti"])

    def test_allowed_credentials_included_when_provided(self):
        token = mint_llm_token(
            user_profile_id=42, role="normal", credential_id=7,
            allowed_credentials=[3, 7, 12],
        )
        claims = _decode(token)
        assert claims["allowed_credentials"] == [3, 7, 12]

    def test_allowed_credentials_absent_when_not_provided(self):
        token = mint_llm_token(user_profile_id=42, role="admin", credential_id=7)
        claims = _decode(token)
        assert "allowed_credentials" not in claims

    def test_sub_is_string(self):
        """JWT sub claim should be a string per RFC 7519."""
        token = mint_llm_token(user_profile_id=999, role="admin", credential_id=1)
        claims = _decode(token)
        assert isinstance(claims["sub"], str)
        assert claims["sub"] == "999"


class TestMintLLMTokenErrors:
    """Error handling for missing or invalid configuration."""

    def test_empty_private_key_raises(self, _configure_private_key):
        _configure_private_key.JWT_PRIVATE_KEY = ""
        with pytest.raises(JWTIssuerError, match="JWT_PRIVATE_KEY is not configured"):
            mint_llm_token(user_profile_id=1, role="admin", credential_id=1)

    def test_invalid_private_key_raises(self, _configure_private_key):
        _configure_private_key.JWT_PRIVATE_KEY = "not-a-real-key"
        with pytest.raises(JWTIssuerError, match="Failed to sign JWT"):
            mint_llm_token(user_profile_id=1, role="admin", credential_id=1)

    def test_expired_token_rejected(self):
        """A token with exp in the past should fail validation."""
        with patch("services.jwt_issuer.time") as mock_time:
            mock_time.time.return_value = time.time() - 120  # 2 minutes ago
            token = mint_llm_token(user_profile_id=1, role="admin", credential_id=1)

        with pytest.raises(jwt.ExpiredSignatureError):
            _decode(token)
