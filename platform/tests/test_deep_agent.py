"""Tests for deep_agent component — _resolve_credential_field and _build_backend."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from components._agent_shared import _resolve_credential_field
from models.credential import (
    BaseCredential,
    GitCredential,
    LLMProviderCredential,
    TelegramCredential,
)
from models.workspace import Workspace


# ---------------------------------------------------------------------------
# _resolve_credential_field
# ---------------------------------------------------------------------------


class TestResolveCredentialField:
    def test_llm_api_key(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id, api_key="sk-test-123"
        )
        db.add(llm)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "api_key") == "sk-test-123"

    def test_llm_base_url(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id,
            api_key="sk-x",
            base_url="https://api.example.com",
        )
        db.add(llm)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "base_url") == "https://api.example.com"

    def test_llm_organization_id(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id,
            api_key="sk-x",
            organization_id="org-abc",
        )
        db.add(llm)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "organization_id") == "org-abc"

    def test_telegram_bot_token(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="tg", credential_type="telegram"
        )
        db.add(cred)
        db.flush()
        tg = TelegramCredential(
            base_credentials_id=cred.id, bot_token="123456:ABC-DEF"
        )
        db.add(tg)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "bot_token") == "123456:ABC-DEF"

    def test_git_access_token(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="git", credential_type="git"
        )
        db.add(cred)
        db.flush()
        git = GitCredential(
            base_credentials_id=cred.id,
            provider="github",
            credential_type="token",
            access_token="ghp_abc123",
        )
        db.add(git)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "access_token") == "ghp_abc123"

    def test_git_ssh_private_key(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="git", credential_type="git"
        )
        db.add(cred)
        db.flush()
        git = GitCredential(
            base_credentials_id=cred.id,
            provider="github",
            credential_type="ssh_key",
            ssh_private_key="-----BEGIN OPENSSH PRIVATE KEY-----\nfake",
        )
        db.add(git)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "ssh_private_key") == "-----BEGIN OPENSSH PRIVATE KEY-----\nfake"

    def test_git_webhook_secret(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="git", credential_type="git"
        )
        db.add(cred)
        db.flush()
        git = GitCredential(
            base_credentials_id=cred.id,
            provider="github",
            credential_type="token",
            webhook_secret="whsec_123",
        )
        db.add(git)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "webhook_secret") == "whsec_123"

    def test_unknown_field_returns_none(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id, api_key="sk-x"
        )
        db.add(llm)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "nonexistent_field") is None

    def test_missing_child_returns_none(self, db, user_profile):
        """Credential without matching child record returns None."""
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="bare", credential_type="llm"
        )
        db.add(cred)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "api_key") is None
        assert _resolve_credential_field(cred, "bot_token") is None
        assert _resolve_credential_field(cred, "access_token") is None


# ---------------------------------------------------------------------------
# _build_backend
# ---------------------------------------------------------------------------


class TestBuildBackend:
    def test_with_workspace_id(self, db, user_profile, tmp_path):
        """workspace_id in extra_config loads workspace from DB."""
        ws_path = str(tmp_path / "workspace")
        ws = Workspace(
            name="test-ws",
            path=ws_path,
            user_profile_id=user_profile.id,
            allow_network=True,
            env_vars=[{"key": "FOO", "value": "bar", "source": "raw"}],
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)

        with patch("database.SessionLocal", return_value=db), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="none", can_execute=False, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": ws.id})

        assert str(backend.cwd) == ws_path
        assert backend._allow_network is True
        assert backend._custom_env == {"FOO": "bar"}

    def test_with_workspace_credential_env(self, db, user_profile, tmp_path):
        """workspace with credential-sourced env vars resolves the credential field."""
        ws_path = str(tmp_path / "workspace")
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm-cred", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id, api_key="sk-secret-key"
        )
        db.add(llm)
        db.flush()

        ws = Workspace(
            name="cred-ws",
            path=ws_path,
            user_profile_id=user_profile.id,
            env_vars=[
                {
                    "key": "OPENAI_API_KEY",
                    "source": "credential",
                    "credential_id": cred.id,
                    "credential_field": "api_key",
                },
                {"key": "RAW_VAR", "value": "raw_value", "source": "raw"},
            ],
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)
        db.refresh(cred)

        with patch("database.SessionLocal", return_value=db), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="none", can_execute=False, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": ws.id})

        assert backend._custom_env["OPENAI_API_KEY"] == "sk-secret-key"
        assert backend._custom_env["RAW_VAR"] == "raw_value"

    def test_without_workspace_id(self, tmp_path):
        """No workspace_id falls back to filesystem_root_dir."""
        root = str(tmp_path / "fallback")

        with patch("components.sandboxed_backend.resolve_sandbox_mode",
                    return_value=MagicMock(mode="none", can_execute=False, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"filesystem_root_dir": root})

        assert str(backend.cwd) == root
        assert backend._custom_env == {}

    def test_without_workspace_id_default(self, tmp_path):
        """No workspace_id and no filesystem_root_dir falls back to _get_workspace_dir()."""
        default_dir = str(tmp_path / "default-ws")

        with patch("components._agent_shared._get_workspace_dir", return_value=default_dir), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="none", can_execute=False, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({})

        assert str(backend.cwd) == default_dir

    def test_workspace_not_found_falls_back(self, db, user_profile, tmp_path):
        """Invalid workspace_id falls back to default path."""
        fallback_dir = str(tmp_path / "fallback")

        with patch("database.SessionLocal", return_value=db), \
             patch("components._agent_shared._get_workspace_dir", return_value=fallback_dir), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="none", can_execute=False, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": 99999})

        assert str(backend.cwd) == fallback_dir

    def test_workspace_env_var_empty_key_skipped(self, db, user_profile, tmp_path):
        """Env vars with empty key are skipped."""
        ws_path = str(tmp_path / "workspace")
        ws = Workspace(
            name="skip-ws",
            path=ws_path,
            user_profile_id=user_profile.id,
            env_vars=[
                {"key": "", "value": "should-skip", "source": "raw"},
                {"key": "VALID", "value": "ok", "source": "raw"},
            ],
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)

        with patch("database.SessionLocal", return_value=db), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="none", can_execute=False, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": ws.id})

        assert "" not in backend._custom_env
        assert backend._custom_env == {"VALID": "ok"}

    def test_workspace_credential_env_not_found(self, db, user_profile, tmp_path):
        """Credential-sourced env var with non-existent credential_id is skipped."""
        ws_path = str(tmp_path / "workspace")
        ws = Workspace(
            name="nocred-ws",
            path=ws_path,
            user_profile_id=user_profile.id,
            env_vars=[
                {
                    "key": "MISSING_KEY",
                    "source": "credential",
                    "credential_id": 99999,
                    "credential_field": "api_key",
                },
            ],
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)

        with patch("database.SessionLocal", return_value=db), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="none", can_execute=False, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": ws.id})

        assert "MISSING_KEY" not in backend._custom_env
