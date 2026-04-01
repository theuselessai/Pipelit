"""Tests for agentgateway config writer service -- provider/model structure."""

from __future__ import annotations

import os
import stat
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from cryptography.fernet import Fernet

# Generate a stable test key
_TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture()
def agw_dir(tmp_path):
    """Create a temporary agentgateway directory structure."""
    (tmp_path / "config.d" / "backends").mkdir(parents=True)
    (tmp_path / "config.d" / "mcp_servers").mkdir(parents=True)
    (tmp_path / "config.d" / "rules").mkdir(parents=True)
    (tmp_path / "keys").mkdir()

    # Create a dummy assemble-config.sh that succeeds
    script = tmp_path / "assemble-config.sh"
    script.write_text("#!/bin/bash\nexit 0\n")
    script.chmod(0o755)

    return tmp_path


@pytest.fixture(autouse=True)
def _patch_settings(agw_dir):
    """Patch settings to use the temporary directory and test encryption key."""
    with patch("services.agentgateway_config.settings") as mock_settings:
        mock_settings.AGENTGATEWAY_DIR = str(agw_dir)
        mock_settings.FIELD_ENCRYPTION_KEY = _TEST_KEY
        yield mock_settings


# ---------------------------------------------------------------------------
# Provider key management
# ---------------------------------------------------------------------------


class TestWriteProviderKey:
    def test_writes_encrypted_file(self, agw_dir):
        from services.agentgateway_config import write_provider_key

        write_provider_key("venice", "sk-secret-key-12345")

        key_path = agw_dir / "keys" / "venice.key"
        assert key_path.exists()

        # File contents should be encrypted, not plaintext
        raw = key_path.read_bytes()
        assert b"sk-secret-key-12345" not in raw

        # Decrypt and verify
        fernet = Fernet(_TEST_KEY.encode())
        decrypted = fernet.decrypt(raw).decode()
        assert decrypted == "sk-secret-key-12345"

    def test_file_permissions_are_0600(self, agw_dir):
        from services.agentgateway_config import write_provider_key

        write_provider_key("openai", "sk-openai-key")

        key_path = agw_dir / "keys" / "openai.key"
        mode = stat.S_IMODE(key_path.stat().st_mode)
        assert mode == 0o600

    def test_atomic_write_no_tmp_left(self, agw_dir):
        from services.agentgateway_config import write_provider_key

        write_provider_key("test", "key-value")

        # .tmp file should not remain
        tmp_path = agw_dir / "keys" / "test.key.tmp"
        assert not tmp_path.exists()

    def test_creates_keys_dir_if_missing(self, tmp_path, _patch_settings):
        """keys/ directory is created automatically."""
        _patch_settings.AGENTGATEWAY_DIR = str(tmp_path)

        # Remove keys dir if it exists
        keys_dir = tmp_path / "keys"
        if keys_dir.exists():
            keys_dir.rmdir()
        assert not keys_dir.exists()

        from services.agentgateway_config import write_provider_key

        write_provider_key("new", "key-value")
        assert (tmp_path / "keys" / "new.key").exists()

    def test_overwrites_existing_key(self, agw_dir):
        from services.agentgateway_config import write_provider_key

        write_provider_key("venice", "old-key")
        write_provider_key("venice", "new-key")

        fernet = Fernet(_TEST_KEY.encode())
        decrypted = fernet.decrypt(
            (agw_dir / "keys" / "venice.key").read_bytes()
        ).decode()
        assert decrypted == "new-key"


class TestRemoveProviderKey:
    def test_removes_existing_key(self, agw_dir):
        from services.agentgateway_config import remove_provider_key, write_provider_key

        write_provider_key("test", "value")
        assert (agw_dir / "keys" / "test.key").exists()

        remove_provider_key("test")
        assert not (agw_dir / "keys" / "test.key").exists()

    def test_no_error_if_missing(self, agw_dir):
        from services.agentgateway_config import remove_provider_key

        # Should not raise
        remove_provider_key("nonexistent")


# ---------------------------------------------------------------------------
# Provider management
# ---------------------------------------------------------------------------


class TestAddProvider:
    def test_creates_directory_and_provider_yaml(self, agw_dir):
        from services.agentgateway_config import add_provider

        add_provider(
            provider="venice",
            provider_type="openai_compatible",
            host_override="api.venice.ai:443",
            path_override="/api/v1/chat/completions",
        )

        provider_dir = agw_dir / "config.d" / "backends" / "venice"
        assert provider_dir.is_dir()

        provider_file = provider_dir / "_provider.yaml"
        assert provider_file.exists()

        content = provider_file.read_text()
        assert content.startswith("# venice provider config")

        parsed = yaml.safe_load(content)
        assert parsed["provider"] == {"openAI": {}}
        assert parsed["backendAuth"]["key"] == "${VENICE_API_KEY}"
        assert parsed["backendTLS"] == {}
        assert parsed["hostOverride"] == "api.venice.ai:443"
        assert parsed["pathOverride"] == "/api/v1/chat/completions"

    def test_anthropic_provider(self, agw_dir):
        from services.agentgateway_config import add_provider

        add_provider(provider="anthropic", provider_type="anthropic")

        parsed = yaml.safe_load(
            (agw_dir / "config.d" / "backends" / "anthropic" / "_provider.yaml").read_text()
        )
        assert parsed["provider"] == {"anthropic": {}}
        assert parsed["backendAuth"]["key"] == "${ANTHROPIC_API_KEY}"
        # No hostOverride/pathOverride when not provided
        assert "hostOverride" not in parsed
        assert "pathOverride" not in parsed

    def test_does_not_trigger_reassembly(self, agw_dir):
        """add_provider should NOT call reassemble_config."""
        from services.agentgateway_config import add_provider

        with patch("services.agentgateway_config.reassemble_config") as mock_reassemble:
            add_provider(provider="test", provider_type="openai")
            mock_reassemble.assert_not_called()

    def test_hyphenated_provider_name(self, agw_dir):
        from services.agentgateway_config import add_provider

        add_provider(provider="my-provider", provider_type="openai")

        parsed = yaml.safe_load(
            (agw_dir / "config.d" / "backends" / "my-provider" / "_provider.yaml").read_text()
        )
        assert parsed["backendAuth"]["key"] == "${MY_PROVIDER_API_KEY}"

    def test_atomic_write_no_tmp_left(self, agw_dir):
        from services.agentgateway_config import add_provider

        add_provider(provider="test", provider_type="openai")

        tmp_path = agw_dir / "config.d" / "backends" / "test" / "_provider.yaml.tmp"
        assert not tmp_path.exists()


class TestRemoveProvider:
    @patch("services.agentgateway_config.reassemble_config")
    def test_removes_directory_and_key(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import (
            add_provider,
            remove_provider,
            write_provider_key,
        )

        add_provider(provider="test", provider_type="openai")
        write_provider_key("test", "secret")

        assert (agw_dir / "config.d" / "backends" / "test").is_dir()
        assert (agw_dir / "keys" / "test.key").exists()

        remove_provider("test")

        assert not (agw_dir / "config.d" / "backends" / "test").exists()
        assert not (agw_dir / "keys" / "test.key").exists()
        mock_reassemble.assert_called_once()

    @patch("services.agentgateway_config.reassemble_config")
    def test_no_error_if_missing(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import remove_provider

        # Should not raise
        remove_provider("nonexistent")


class TestListProviders:
    def test_lists_provider_subdirectories(self, agw_dir):
        from services.agentgateway_config import add_provider, list_providers

        add_provider(provider="anthropic", provider_type="anthropic")
        add_provider(provider="openai", provider_type="openai")
        add_provider(provider="venice", provider_type="openai_compatible")

        result = list_providers()
        assert result == ["anthropic", "openai", "venice"]

    def test_empty_when_no_providers(self, agw_dir):
        from services.agentgateway_config import list_providers

        result = list_providers()
        assert result == []

    def test_empty_when_backends_dir_missing(self, tmp_path, _patch_settings):
        _patch_settings.AGENTGATEWAY_DIR = str(tmp_path)

        from services.agentgateway_config import list_providers

        result = list_providers()
        assert result == []


class TestGetProviderConfig:
    def test_reads_provider_yaml(self, agw_dir):
        from services.agentgateway_config import add_provider, get_provider_config

        add_provider(
            provider="venice",
            provider_type="openai_compatible",
            host_override="api.venice.ai:443",
            path_override="/api/v1/chat/completions",
        )

        config = get_provider_config("venice")
        assert config["provider"] == {"openAI": {}}
        assert config["hostOverride"] == "api.venice.ai:443"
        assert config["backendAuth"]["key"] == "${VENICE_API_KEY}"

    def test_raises_if_not_found(self, agw_dir):
        from services.agentgateway_config import get_provider_config

        with pytest.raises(FileNotFoundError, match="Provider config not found"):
            get_provider_config("nonexistent")


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------


class TestAddModel:
    @patch("services.agentgateway_config.reassemble_config")
    def test_creates_model_yaml(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import add_model, add_provider

        add_provider(provider="venice", provider_type="openai_compatible")
        add_model(provider="venice", model_slug="glm-4.7", model_name="zai-org-glm-4.7")

        model_file = agw_dir / "config.d" / "backends" / "venice" / "glm-4.7.yaml"
        assert model_file.exists()

        parsed = yaml.safe_load(model_file.read_text())
        assert parsed == {"model": "zai-org-glm-4.7"}
        mock_reassemble.assert_called_once()

    @patch("services.agentgateway_config.reassemble_config")
    def test_reassemble_false_suppresses_reassembly(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import add_model, add_provider

        add_provider(provider="venice", provider_type="openai_compatible")
        add_model(
            provider="venice",
            model_slug="glm-4.7",
            model_name="zai-org-glm-4.7",
            reassemble=False,
        )

        # Model file created but no reassembly
        assert (agw_dir / "config.d" / "backends" / "venice" / "glm-4.7.yaml").exists()
        mock_reassemble.assert_not_called()

    @patch("services.agentgateway_config.reassemble_config")
    def test_atomic_write_no_tmp_left(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import add_model, add_provider

        add_provider(provider="venice", provider_type="openai_compatible")
        add_model(provider="venice", model_slug="test", model_name="test-model")

        tmp_path = agw_dir / "config.d" / "backends" / "venice" / "test.yaml.tmp"
        assert not tmp_path.exists()

    @patch("services.agentgateway_config.reassemble_config")
    def test_creates_provider_dir_if_missing(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import add_model

        # Provider dir does not exist yet
        add_model(provider="newprovider", model_slug="test", model_name="test-model")

        assert (agw_dir / "config.d" / "backends" / "newprovider" / "test.yaml").exists()


class TestRemoveModel:
    @patch("services.agentgateway_config.reassemble_config")
    def test_removes_model_file(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import add_model, add_provider, remove_model

        add_provider(provider="venice", provider_type="openai_compatible")
        with patch("services.agentgateway_config.reassemble_config"):
            add_model(provider="venice", model_slug="glm-4.7", model_name="zai-org-glm-4.7")

        assert (agw_dir / "config.d" / "backends" / "venice" / "glm-4.7.yaml").exists()

        remove_model("venice", "glm-4.7")

        assert not (agw_dir / "config.d" / "backends" / "venice" / "glm-4.7.yaml").exists()
        # Provider directory still exists
        assert (agw_dir / "config.d" / "backends" / "venice" / "_provider.yaml").exists()
        mock_reassemble.assert_called_once()

    @patch("services.agentgateway_config.reassemble_config")
    def test_no_error_if_missing(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import remove_model

        # Should not raise
        remove_model("nonexistent", "no-model")


class TestListModels:
    def test_lists_models_excluding_provider_yaml(self, agw_dir):
        from services.agentgateway_config import add_model, add_provider, list_models

        add_provider(provider="venice", provider_type="openai_compatible")
        with patch("services.agentgateway_config.reassemble_config"):
            add_model(provider="venice", model_slug="glm-4.7", model_name="zai-org-glm-4.7")
            add_model(provider="venice", model_slug="deepseek-r1", model_name="deepseek-r1-0528")

        result = list_models("venice")
        assert len(result) == 2
        assert result[0] == {
            "slug": "deepseek-r1",
            "model_name": "deepseek-r1-0528",
            "route": "venice-deepseek-r1",
        }
        assert result[1] == {
            "slug": "glm-4.7",
            "model_name": "zai-org-glm-4.7",
            "route": "venice-glm-4.7",
        }

    def test_empty_when_no_models(self, agw_dir):
        from services.agentgateway_config import add_provider, list_models

        add_provider(provider="venice", provider_type="openai_compatible")
        result = list_models("venice")
        assert result == []

    def test_empty_when_provider_missing(self, agw_dir):
        from services.agentgateway_config import list_models

        result = list_models("nonexistent")
        assert result == []


class TestListAllAvailableModels:
    def test_returns_models_only_for_providers_with_keys(self, agw_dir):
        from services.agentgateway_config import (
            add_model,
            add_provider,
            list_all_available_models,
            write_provider_key,
        )

        # Provider with key
        add_provider(provider="venice", provider_type="openai_compatible")
        write_provider_key("venice", "sk-venice")
        with patch("services.agentgateway_config.reassemble_config"):
            add_model(provider="venice", model_slug="glm-4.7", model_name="zai-org-glm-4.7")

        # Provider WITHOUT key
        add_provider(provider="openai", provider_type="openai")
        with patch("services.agentgateway_config.reassemble_config"):
            add_model(provider="openai", model_slug="gpt-4o", model_name="gpt-4o")

        result = list_all_available_models()
        assert len(result) == 1
        assert result[0] == {
            "route": "venice-glm-4.7",
            "provider": "venice",
            "model_slug": "glm-4.7",
            "model_name": "zai-org-glm-4.7",
        }

    def test_multiple_providers_with_keys(self, agw_dir):
        from services.agentgateway_config import (
            add_model,
            add_provider,
            list_all_available_models,
            write_provider_key,
        )

        add_provider(provider="openai", provider_type="openai")
        write_provider_key("openai", "sk-openai")
        add_provider(provider="venice", provider_type="openai_compatible")
        write_provider_key("venice", "sk-venice")

        with patch("services.agentgateway_config.reassemble_config"):
            add_model(provider="openai", model_slug="gpt-4o", model_name="gpt-4o")
            add_model(provider="venice", model_slug="glm-4.7", model_name="zai-org-glm-4.7")
            add_model(provider="venice", model_slug="deepseek-r1", model_name="deepseek-r1-0528")

        result = list_all_available_models()
        assert len(result) == 3
        providers = [r["provider"] for r in result]
        assert providers == ["openai", "venice", "venice"]

    def test_empty_when_no_backends(self, agw_dir):
        from services.agentgateway_config import list_all_available_models

        result = list_all_available_models()
        assert result == []

    def test_empty_when_no_keys_dir(self, tmp_path, _patch_settings):
        """No keys/ directory at all."""
        _patch_settings.AGENTGATEWAY_DIR = str(tmp_path)
        (tmp_path / "config.d" / "backends" / "venice").mkdir(parents=True)
        (tmp_path / "config.d" / "backends" / "venice" / "_provider.yaml").write_text(
            "provider:\n  openAI: {}\n"
        )
        (tmp_path / "config.d" / "backends" / "venice" / "glm.yaml").write_text(
            "model: glm-4\n"
        )

        from services.agentgateway_config import list_all_available_models

        result = list_all_available_models()
        assert result == []


# ---------------------------------------------------------------------------
# Build provider type
# ---------------------------------------------------------------------------


class TestBuildProviderType:
    def test_anthropic(self):
        from services.agentgateway_config import _build_provider_type

        assert _build_provider_type("anthropic") == {"anthropic": {}}

    def test_openai(self):
        from services.agentgateway_config import _build_provider_type

        assert _build_provider_type("openai") == {"openAI": {}}

    def test_openai_compatible(self):
        from services.agentgateway_config import _build_provider_type

        assert _build_provider_type("openai_compatible") == {"openAI": {}}

    def test_glm(self):
        from services.agentgateway_config import _build_provider_type

        assert _build_provider_type("glm") == {"openAI": {}}

    def test_unknown_defaults_to_openai(self):
        from services.agentgateway_config import _build_provider_type

        assert _build_provider_type("unknown") == {"openAI": {}}


# ---------------------------------------------------------------------------
# MCP, Rules, Assembly (unchanged)
# ---------------------------------------------------------------------------


class TestAddMcpServer:
    @patch("services.agentgateway_config.reassemble_config")
    def test_writes_config(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import add_mcp_server

        config = {"mcp": {"name": "test-mcp", "command": "npx test-server"}}
        add_mcp_server("test-mcp", config)

        path = agw_dir / "config.d" / "mcp_servers" / "test-mcp.yaml"
        assert path.exists()

        content = path.read_text()
        assert content.startswith("# test-mcp MCP server")

        parsed = yaml.safe_load(content)
        assert parsed == config
        mock_reassemble.assert_called_once()


class TestRemoveMcpServer:
    @patch("services.agentgateway_config.reassemble_config")
    def test_removes_config(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import add_mcp_server, remove_mcp_server

        with patch("services.agentgateway_config.reassemble_config"):
            add_mcp_server("test", {"name": "test"})

        assert (agw_dir / "config.d" / "mcp_servers" / "test.yaml").exists()

        remove_mcp_server("test")
        assert not (agw_dir / "config.d" / "mcp_servers" / "test.yaml").exists()


class TestUpdateRules:
    @patch("services.agentgateway_config.reassemble_config")
    def test_writes_cel_rules(self, mock_reassemble, agw_dir):
        from services.agentgateway_config import update_rules

        rules = ['jwt.role == "admin"', 'jwt.role == "user"']
        update_rules("admin", rules)

        path = agw_dir / "config.d" / "rules" / "admin.yaml"
        assert path.exists()

        content = path.read_text()
        assert content.startswith("# admin role authorization rules")

        parsed = yaml.safe_load(content)
        assert parsed == rules
        mock_reassemble.assert_called_once()


class TestReassembleConfig:
    def test_calls_assemble_script(self, agw_dir):
        from services.agentgateway_config import reassemble_config

        reassemble_config()

        # Verify the lock file was created
        assert (agw_dir / ".config.lock").exists()

    def test_raises_on_script_failure(self, agw_dir):
        from services.agentgateway_config import reassemble_config

        # Replace script with one that fails
        script = agw_dir / "assemble-config.sh"
        script.write_text("#!/bin/bash\necho 'error' >&2\nexit 1\n")

        with pytest.raises(RuntimeError, match="Config assembly failed"):
            reassemble_config()

    def test_concurrent_calls_serialize(self, agw_dir):
        """File locking prevents concurrent reassembly."""
        from services.agentgateway_config import reassemble_config

        # Replace script with one that takes a moment
        script = agw_dir / "assemble-config.sh"
        counter_file = agw_dir / "counter"
        counter_file.write_text("0")
        script.write_text(
            f"#!/bin/bash\n"
            f"val=$(cat '{counter_file}')\n"
            f"echo $((val + 1)) > '{counter_file}'\n"
            f"exit 0\n"
        )

        errors = []

        def run():
            try:
                reassemble_config()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All 5 calls completed (counter should be 5)
        assert int(counter_file.read_text().strip()) == 5


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestNameToEnvVar:
    def test_simple(self):
        from services.agentgateway_config import _name_to_env_var

        assert _name_to_env_var("venice") == "VENICE_API_KEY"

    def test_hyphen(self):
        from services.agentgateway_config import _name_to_env_var

        assert _name_to_env_var("my-backend") == "MY_BACKEND_API_KEY"

    def test_dot(self):
        from services.agentgateway_config import _name_to_env_var

        assert _name_to_env_var("open.ai") == "OPEN_AI_API_KEY"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_no_encryption_key_raises(self, agw_dir, _patch_settings):
        _patch_settings.FIELD_ENCRYPTION_KEY = ""

        from services.agentgateway_config import write_provider_key

        with pytest.raises(RuntimeError, match="FIELD_ENCRYPTION_KEY is not set"):
            write_provider_key("test", "value")

    def test_no_agw_dir_raises(self, _patch_settings):
        _patch_settings.AGENTGATEWAY_DIR = ""

        from services.agentgateway_config import list_providers

        with pytest.raises(RuntimeError, match="AGENTGATEWAY_DIR is not set"):
            list_providers()
