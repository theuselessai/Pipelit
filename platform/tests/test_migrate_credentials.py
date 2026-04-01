"""Tests for the migrate-credentials CLI command (provider/model structure)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from cryptography.fernet import Fernet

from conftest import TestSession

_TEST_KEY = Fernet.generate_key().decode()


def _run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run CLI main() with the given args, capturing stdout/stderr and exit code."""
    from cli.__main__ import main

    captured_out = []
    captured_err = []
    exit_code = 0

    def mock_stdout_write(s):
        captured_out.append(s)
        return len(s)

    def mock_stderr_write(s):
        captured_err.append(s)
        return len(s)

    with patch.object(sys, "argv", ["cli"] + args), \
         patch.object(sys.stdout, "write", mock_stdout_write), \
         patch.object(sys.stderr, "write", mock_stderr_write):
        try:
            main()
        except SystemExit as e:
            try:
                exit_code = int(e.code) if e.code is not None else 0
            except (TypeError, ValueError):
                exit_code = 1

    return exit_code, "".join(captured_out), "".join(captured_err)


@pytest.fixture
def agw_dir(tmp_path):
    """Create a temporary agentgateway directory structure."""
    (tmp_path / "config.d" / "backends").mkdir(parents=True)
    (tmp_path / "keys").mkdir()
    # Create a dummy assemble-config.sh that succeeds
    script = tmp_path / "assemble-config.sh"
    script.write_text("#!/bin/bash\nexit 0\n")
    script.chmod(0o755)
    return tmp_path


@pytest.fixture
def cli_db():
    """Patch SessionLocal so CLI commands use the test database."""
    session = TestSession()
    try:
        with patch("database.SessionLocal", return_value=session):
            yield session
    finally:
        session.close()


@pytest.fixture
def _patch_agw_settings(agw_dir):
    """Patch settings for agentgateway config writer."""
    with patch("services.agentgateway_config.settings") as mock_settings:
        mock_settings.AGENTGATEWAY_DIR = str(agw_dir)
        mock_settings.FIELD_ENCRYPTION_KEY = _TEST_KEY
        yield mock_settings


@pytest.fixture
def _patch_config_settings(agw_dir):
    """Patch config.settings for the CLI command that reads AGENTGATEWAY_DIR."""
    with patch("config.settings") as mock_settings:
        mock_settings.AGENTGATEWAY_DIR = str(agw_dir)
        mock_settings.FIELD_ENCRYPTION_KEY = _TEST_KEY
        yield mock_settings


def _create_llm_credential(db, user_profile, *, name, provider_type, api_key, base_url=""):
    """Helper to create an LLM credential in the test DB."""
    from models.credential import BaseCredential, LLMProviderCredential

    base = BaseCredential(
        user_profile_id=user_profile.id,
        name=name,
        credential_type="llm",
    )
    db.add(base)
    db.flush()

    llm = LLMProviderCredential(
        base_credentials_id=base.id,
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url,
    )
    db.add(llm)
    db.commit()
    return llm


# ---------------------------------------------------------------------------
# TestResolveProviderName
# ---------------------------------------------------------------------------


class TestResolveProviderName:
    def test_openai(self):
        from cli.__main__ import _resolve_provider_name

        cred = MagicMock(provider_type="openai")
        assert _resolve_provider_name(cred) == "openai"

    def test_anthropic(self):
        from cli.__main__ import _resolve_provider_name

        cred = MagicMock(provider_type="anthropic")
        assert _resolve_provider_name(cred) == "anthropic"

    def test_glm(self):
        from cli.__main__ import _resolve_provider_name

        cred = MagicMock(provider_type="glm")
        assert _resolve_provider_name(cred) == "glm"

    def test_openai_compatible_spaces_to_underscores(self):
        from cli.__main__ import _resolve_provider_name

        cred = MagicMock(provider_type="openai_compatible")
        cred.base_credentials.name = "Venice AI"
        assert _resolve_provider_name(cred) == "venice_ai"

    def test_openai_compatible_hyphens_sanitized(self):
        from cli.__main__ import _resolve_provider_name

        cred = MagicMock(provider_type="openai_compatible")
        cred.base_credentials.name = "my-custom-llm"
        assert _resolve_provider_name(cred) == "my_custom_llm"

    def test_openai_compatible_special_chars_removed(self):
        from cli.__main__ import _resolve_provider_name

        cred = MagicMock(provider_type="openai_compatible")
        cred.base_credentials.name = "LLM Provider (v2)!"
        assert _resolve_provider_name(cred) == "llm_provider_v2"

    def test_openai_compatible_fallback_to_custom_id(self):
        from cli.__main__ import _resolve_provider_name

        cred = MagicMock(provider_type="openai_compatible")
        cred.base_credentials.name = ""
        cred.base_credentials_id = 42
        assert _resolve_provider_name(cred) == "custom42"


# ---------------------------------------------------------------------------
# TestModelToSlug
# ---------------------------------------------------------------------------


class TestModelToSlug:
    def test_standard_model(self):
        from cli.__main__ import _model_to_slug

        assert _model_to_slug("gpt-4o") == "gpt-4o"

    def test_model_with_slashes(self):
        from cli.__main__ import _model_to_slug

        assert _model_to_slug("meta/llama-3.1-70b") == "meta-llama-3.1-70b"

    def test_model_with_colons(self):
        from cli.__main__ import _model_to_slug

        assert _model_to_slug("ollama:llama3") == "ollama-llama3"

    def test_model_with_spaces(self):
        from cli.__main__ import _model_to_slug

        assert _model_to_slug("Claude Sonnet 4") == "claude-sonnet-4"

    def test_model_special_chars(self):
        from cli.__main__ import _model_to_slug

        assert _model_to_slug("model@v2#beta") == "modelv2beta"

    def test_empty_model(self):
        from cli.__main__ import _model_to_slug

        assert _model_to_slug("") == "default"

    def test_dots_preserved(self):
        from cli.__main__ import _model_to_slug

        assert _model_to_slug("glm-4.7") == "glm-4.7"


# ---------------------------------------------------------------------------
# TestParseBaseUrl
# ---------------------------------------------------------------------------


class TestParseBaseUrl:
    def test_https_default_port(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("https://api.openai.com/v1")
        assert host == "api.openai.com:443"
        assert path == "/v1"

    def test_http_default_port(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("http://localhost/api")
        assert host == "localhost:80"
        assert path == "/api"

    def test_explicit_port(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("http://localhost:11434/v1")
        assert host == "localhost:11434"
        assert path == "/v1"

    def test_trailing_slash_stripped(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("https://api.venice.ai/api/v1/")
        assert host == "api.venice.ai:443"
        assert path == "/api/v1"

    def test_empty_url(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("")
        assert host == ""
        assert path == ""

    def test_none_like_url(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("  ")
        assert host == ""
        assert path == ""

    def test_https_no_path(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("https://api.anthropic.com")
        assert host == "api.anthropic.com:443"
        assert path == ""

    def test_openai_appends_chat_completions(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("https://api.openai.com/v1", provider_type="openai")
        assert path == "/v1/chat/completions"

    def test_openai_compatible_appends_chat_completions(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("https://api.venice.ai/api/v1", provider_type="openai_compatible")
        assert path == "/api/v1/chat/completions"

    def test_anthropic_appends_messages(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("https://api.anthropic.com/v1", provider_type="anthropic")
        assert path == "/v1/messages"

    def test_glm_appends_chat_completions(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("https://api.example.com/v1", provider_type="glm")
        assert path == "/v1/chat/completions"

    def test_no_duplicate_suffix(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url(
            "https://api.openai.com/v1/chat/completions", provider_type="openai"
        )
        assert path == "/v1/chat/completions"

    def test_no_suffix_without_provider_type(self):
        from cli.__main__ import _parse_base_url

        host, path = _parse_base_url("https://api.openai.com/v1")
        assert path == "/v1"


# ---------------------------------------------------------------------------
# TestMigrateCredentials
# ---------------------------------------------------------------------------


class TestMigrateCredentials:
    def test_migrate_single_openai(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        _create_llm_credential(
            cli_db, user_profile,
            name="OpenAI (default)",
            provider_type="openai",
            api_key="sk-openai-test-key",
        )

        code, out, err = _run_cli(["migrate-credentials"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 1
        assert data["models"] == 1

        # Key file written and encrypted
        key_path = agw_dir / "keys" / "openai.key"
        assert key_path.exists()
        fernet = Fernet(_TEST_KEY.encode())
        decrypted = fernet.decrypt(key_path.read_bytes()).decode()
        assert decrypted == "sk-openai-test-key"

        # Provider dir created with _provider.yaml
        provider_yaml = agw_dir / "config.d" / "backends" / "openai" / "_provider.yaml"
        assert provider_yaml.exists()
        parsed = yaml.safe_load(provider_yaml.read_text())
        assert parsed["backendAuth"]["key"] == "${OPENAI_API_KEY}"
        assert "openAI" in parsed["provider"]

        # Model file created
        model_yaml = agw_dir / "config.d" / "backends" / "openai" / "openai-default.yaml"
        assert model_yaml.exists()
        model_data = yaml.safe_load(model_yaml.read_text())
        assert model_data["model"] == "OpenAI (default)"

    def test_migrate_single_anthropic(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        _create_llm_credential(
            cli_db, user_profile,
            name="Anthropic",
            provider_type="anthropic",
            api_key="sk-ant-test",
        )

        code, out, err = _run_cli(["migrate-credentials"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 1

        provider_yaml = agw_dir / "config.d" / "backends" / "anthropic" / "_provider.yaml"
        assert provider_yaml.exists()
        parsed = yaml.safe_load(provider_yaml.read_text())
        assert "anthropic" in parsed["provider"]

    def test_migrate_openai_compatible_with_base_url(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        _create_llm_credential(
            cli_db, user_profile,
            name="Venice AI",
            provider_type="openai_compatible",
            api_key="sk-venice-key",
            base_url="https://api.venice.ai/api/v1",
        )

        code, out, err = _run_cli(["migrate-credentials"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 1

        # Provider name sanitized: no hyphens
        provider_yaml = agw_dir / "config.d" / "backends" / "venice_ai" / "_provider.yaml"
        assert provider_yaml.exists()
        parsed = yaml.safe_load(provider_yaml.read_text())
        assert parsed["hostOverride"] == "api.venice.ai:443"
        assert parsed["pathOverride"] == "/api/v1/chat/completions"

    def test_multiple_credentials_same_provider_share_key(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        """Multiple credentials for the same provider should share one key and one _provider.yaml."""
        _create_llm_credential(
            cli_db, user_profile,
            name="OpenAI GPT-4o",
            provider_type="openai",
            api_key="sk-openai-key",
        )
        _create_llm_credential(
            cli_db, user_profile,
            name="OpenAI o1",
            provider_type="openai",
            api_key="sk-openai-key",
        )

        code, out, err = _run_cli(["migrate-credentials"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 1
        assert data["models"] == 2

        # One key file
        assert (agw_dir / "keys" / "openai.key").exists()

        # Two model files
        openai_dir = agw_dir / "config.d" / "backends" / "openai"
        model_files = sorted(f.name for f in openai_dir.glob("*.yaml") if f.name != "_provider.yaml")
        assert len(model_files) == 2

    def test_different_providers_get_separate_dirs(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        _create_llm_credential(
            cli_db, user_profile,
            name="OpenAI",
            provider_type="openai",
            api_key="sk-openai",
        )
        _create_llm_credential(
            cli_db, user_profile,
            name="Anthropic",
            provider_type="anthropic",
            api_key="sk-ant",
        )

        code, out, err = _run_cli(["migrate-credentials"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 2

        assert (agw_dir / "config.d" / "backends" / "openai" / "_provider.yaml").exists()
        assert (agw_dir / "config.d" / "backends" / "anthropic" / "_provider.yaml").exists()
        assert (agw_dir / "keys" / "openai.key").exists()
        assert (agw_dir / "keys" / "anthropic.key").exists()

    def test_skip_already_migrated_idempotent(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        _create_llm_credential(
            cli_db, user_profile,
            name="OpenAI",
            provider_type="openai",
            api_key="sk-openai-test",
        )

        # Pre-create provider dir to simulate previous migration
        provider_dir = agw_dir / "config.d" / "backends" / "openai"
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / "_provider.yaml").write_text("existing")

        code, out, err = _run_cli(["migrate-credentials"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 0
        assert data["skipped"] == 1

        # Files unchanged
        assert (provider_dir / "_provider.yaml").read_text() == "existing"

    def test_force_overwrites_existing(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        _create_llm_credential(
            cli_db, user_profile,
            name="OpenAI",
            provider_type="openai",
            api_key="sk-new-key",
        )

        # Pre-create files
        provider_dir = agw_dir / "config.d" / "backends" / "openai"
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / "_provider.yaml").write_text("old-config")
        (agw_dir / "keys" / "openai.key").write_text("old-data")

        code, out, err = _run_cli(["migrate-credentials", "--force"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 1
        assert data["skipped"] == 0

        # Key file overwritten with encrypted content
        fernet = Fernet(_TEST_KEY.encode())
        decrypted = fernet.decrypt((agw_dir / "keys" / "openai.key").read_bytes()).decode()
        assert decrypted == "sk-new-key"

    def test_dry_run_no_files_written(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        _create_llm_credential(
            cli_db, user_profile,
            name="OpenAI",
            provider_type="openai",
            api_key="sk-test",
        )

        code, out, err = _run_cli(["migrate-credentials", "--dry-run"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 1
        assert data["models"] == 1

        # No files created
        assert not (agw_dir / "keys" / "openai.key").exists()
        assert not (agw_dir / "config.d" / "backends" / "openai").exists()

        # Dry-run output visible in stderr
        assert "DRY-RUN" in err

    def test_single_reassemble_at_end(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        """Multiple providers should trigger reassemble_config exactly once at the end."""
        _create_llm_credential(
            cli_db, user_profile,
            name="OpenAI",
            provider_type="openai",
            api_key="sk-openai",
        )
        _create_llm_credential(
            cli_db, user_profile,
            name="Anthropic",
            provider_type="anthropic",
            api_key="sk-ant",
        )
        _create_llm_credential(
            cli_db, user_profile,
            name="Venice AI",
            provider_type="openai_compatible",
            api_key="sk-venice",
            base_url="https://api.venice.ai/api/v1",
        )

        # Track reassemble_config calls
        reassemble_calls = []

        import services.agentgateway_config as agw_mod
        original_reassemble = agw_mod.reassemble_config

        def counting_reassemble():
            reassemble_calls.append(1)
            return original_reassemble()

        with patch.object(agw_mod, "reassemble_config", counting_reassemble):
            code, out, err = _run_cli(["migrate-credentials"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 3

        # reassemble_config called exactly once
        assert len(reassemble_calls) == 1

    def test_populate_routes_sets_backend_route(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        """--populate-routes should set backend_route on component_configs."""
        from models.credential import BaseCredential
        from models.node import BaseComponentConfig

        cred = _create_llm_credential(
            cli_db, user_profile,
            name="OpenAI GPT-4o",
            provider_type="openai",
            api_key="sk-openai",
        )

        # Create a component config pointing to this credential
        base_cred = cli_db.query(BaseCredential).filter(BaseCredential.id == cred.base_credentials_id).one()
        cfg = BaseComponentConfig(
            component_type="ai_model",
            llm_credential_id=base_cred.id,
            model_name="gpt-4o",
        )
        cli_db.add(cfg)
        cli_db.commit()

        code, out, err = _run_cli(["migrate-credentials", "--populate-routes"])

        assert code == 0
        data = json.loads(out)
        assert data["routes_updated"] == 1

        # Re-query from the same session (CLI uses its own SessionLocal instance)
        cli_db.expire_all()
        updated_cfg = cli_db.query(BaseComponentConfig).filter(BaseComponentConfig.id == cfg.id).one()
        assert updated_cfg.backend_route == "openai-openai-gpt-4o"

    def test_no_credentials_found(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        code, out, err = _run_cli(["migrate-credentials"])

        assert code == 0
        data = json.loads(out)
        assert data["providers"] == 0
        assert data["message"] == "No LLM credentials found"


# ---------------------------------------------------------------------------
# TestRollback
# ---------------------------------------------------------------------------


class TestRollback:
    def test_rollback_deletes_dirs_keys_and_reassembles(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings, tmp_path
    ):
        # Create provider directories and keys to roll back
        openai_dir = agw_dir / "config.d" / "backends" / "openai"
        openai_dir.mkdir(parents=True)
        (openai_dir / "_provider.yaml").write_text("provider: openAI")
        (openai_dir / "gpt-4o.yaml").write_text("model: gpt-4o")
        (agw_dir / "keys" / "openai.key").write_text("encrypted-key")

        anthropic_dir = agw_dir / "config.d" / "backends" / "anthropic"
        anthropic_dir.mkdir(parents=True)
        (anthropic_dir / "_provider.yaml").write_text("provider: anthropic")
        (agw_dir / "keys" / "anthropic.key").write_text("encrypted-key")

        with patch("cli.__main__._set_env_var") as mock_set_env:
            code, out, err = _run_cli(["migrate-credentials", "--rollback"])

        assert code == 0
        data = json.loads(out)
        assert data["rolled_back"] == 2

        # Directories deleted
        assert not openai_dir.exists()
        assert not anthropic_dir.exists()
        assert not (agw_dir / "keys" / "openai.key").exists()
        assert not (agw_dir / "keys" / "anthropic.key").exists()

        # _set_env_var was called to disable agentgateway
        mock_set_env.assert_called_once()
        call_args = mock_set_env.call_args
        assert call_args[0][1] == "AGENTGATEWAY_ENABLED"
        assert call_args[0][2] == "false"

    def test_rollback_no_providers(
        self, cli_db, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        code, out, err = _run_cli(["migrate-credentials", "--rollback"])

        assert code == 0
        data = json.loads(out)
        assert data["rolled_back"] == 0

    def test_rollback_dry_run(
        self, cli_db, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        openai_dir = agw_dir / "config.d" / "backends" / "openai"
        openai_dir.mkdir(parents=True)
        (openai_dir / "_provider.yaml").write_text("provider: openAI")
        (agw_dir / "keys" / "openai.key").write_text("encrypted")

        code, out, err = _run_cli(["migrate-credentials", "--rollback", "--dry-run"])

        assert code == 0
        data = json.loads(out)
        assert data["rolled_back"] == 1

        # Files NOT deleted (dry run)
        assert openai_dir.exists()
        assert "DRY-RUN" in err

    def test_rollback_clears_backend_routes(
        self, cli_db, user_profile, agw_dir, _patch_agw_settings, _patch_config_settings
    ):
        """--populate-routes on rollback should null out backend_route values."""
        from models.node import BaseComponentConfig

        # Create a component config with a backend_route
        cfg = BaseComponentConfig(
            component_type="ai_model",
            backend_route="openai-gpt-4o",
        )
        cli_db.add(cfg)
        cli_db.commit()

        # Create a provider dir so rollback has something to remove
        openai_dir = agw_dir / "config.d" / "backends" / "openai"
        openai_dir.mkdir(parents=True)
        (openai_dir / "_provider.yaml").write_text("provider: openAI")

        with patch("cli.__main__._set_env_var"):
            code, out, err = _run_cli(["migrate-credentials", "--rollback", "--populate-routes"])

        assert code == 0
        data = json.loads(out)
        assert data["rolled_back"] == 1
        assert data["routes_cleared"] == 1

        # Re-query from the same session (CLI uses its own SessionLocal instance)
        cli_db.expire_all()
        updated_cfg = cli_db.query(BaseComponentConfig).filter(BaseComponentConfig.id == cfg.id).one()
        assert updated_cfg.backend_route is None


# ---------------------------------------------------------------------------
# TestSetEnvVar
# ---------------------------------------------------------------------------


class TestSetEnvVar:
    def test_updates_existing_var(self, tmp_path):
        from cli.__main__ import _set_env_var

        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nAGENTGATEWAY_ENABLED=true\nBAZ=qux\n")

        _set_env_var(env_file, "AGENTGATEWAY_ENABLED", "false")

        content = env_file.read_text()
        assert "AGENTGATEWAY_ENABLED=false" in content
        assert "AGENTGATEWAY_ENABLED=true" not in content
        assert "FOO=bar" in content
        assert "BAZ=qux" in content

    def test_appends_new_var(self, tmp_path):
        from cli.__main__ import _set_env_var

        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n")

        _set_env_var(env_file, "AGENTGATEWAY_ENABLED", "false")

        content = env_file.read_text()
        assert "AGENTGATEWAY_ENABLED=false" in content
        assert "FOO=bar" in content

    def test_creates_file_if_missing(self, tmp_path):
        from cli.__main__ import _set_env_var

        env_file = tmp_path / ".env"
        assert not env_file.exists()

        _set_env_var(env_file, "AGENTGATEWAY_ENABLED", "false")

        assert env_file.exists()
        assert env_file.read_text().strip() == "AGENTGATEWAY_ENABLED=false"
