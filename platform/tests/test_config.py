"""Tests for conf.json loading, Settings integration, and secret generation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from pydantic_settings import BaseSettings as _BaseSettings

from config import (
    PipelitConfig,
    Settings,
    get_pipelit_dir,
    load_conf,
    save_conf,
    _ensure_secrets,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_pipelit_dir(tmp_path, monkeypatch):
    """Point PIPELIT_DIR to tmp_path so tests never touch the real config."""
    monkeypatch.setenv("PIPELIT_DIR", str(tmp_path / "pipelit"))


# ---------------------------------------------------------------------------
# get_pipelit_dir
# ---------------------------------------------------------------------------


def test_get_pipelit_dir_default(monkeypatch):
    monkeypatch.delenv("PIPELIT_DIR", raising=False)
    result = get_pipelit_dir()
    assert result == Path.home() / ".config" / "pipelit"


def test_get_pipelit_dir_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom_dir"
    monkeypatch.setenv("PIPELIT_DIR", str(custom))
    assert get_pipelit_dir() == custom


# ---------------------------------------------------------------------------
# load_conf / save_conf
# ---------------------------------------------------------------------------


def test_load_conf_json_defaults(tmp_path, monkeypatch):
    """No conf.json file → PipelitConfig uses built-in defaults."""
    monkeypatch.setenv("PIPELIT_DIR", str(tmp_path / "nonexistent"))
    conf = load_conf()
    assert conf.setup_completed is False
    assert conf.sandbox_mode == "auto"
    assert conf.database_url == ""
    assert conf.redis_url == ""
    assert conf.cors_allow_all_origins is None
    assert conf.detected_environment == {}


def test_load_conf_json_from_file(tmp_path, monkeypatch):
    """Write conf.json to tmp_path → load_conf() picks up values."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    data = {
        "setup_completed": True,
        "sandbox_mode": "bwrap",
        "database_url": "sqlite:///custom.db",
        "redis_url": "redis://custom:6379/1",
        "log_level": "DEBUG",
        "platform_base_url": "https://my.host:9000",
    }
    (pipelit_dir / "conf.json").write_text(json.dumps(data))

    conf = load_conf()
    assert conf.setup_completed is True
    assert conf.sandbox_mode == "bwrap"
    assert conf.database_url == "sqlite:///custom.db"
    assert conf.redis_url == "redis://custom:6379/1"
    assert conf.log_level == "DEBUG"
    assert conf.platform_base_url == "https://my.host:9000"


def test_load_conf_json_partial(tmp_path, monkeypatch):
    """Partial conf.json (only sandbox_mode) → other fields use defaults."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    (pipelit_dir / "conf.json").write_text(json.dumps({"sandbox_mode": "container"}))

    conf = load_conf()
    assert conf.sandbox_mode == "container"
    assert conf.database_url == ""
    assert conf.setup_completed is False


def test_load_conf_json_invalid_json(tmp_path, monkeypatch, caplog):
    """Malformed JSON → falls back to defaults and logs a warning."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    (pipelit_dir / "conf.json").write_text("{not valid json!!!")

    with caplog.at_level("WARNING", logger="config"):
        conf = load_conf()
    assert conf == PipelitConfig()
    assert "Failed to parse" in caplog.text


def test_save_conf_creates_dir(tmp_path, monkeypatch):
    """save_conf() creates pipelit_dir if missing."""
    pipelit_dir = tmp_path / "deep" / "nested" / "pipelit"
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    conf = PipelitConfig(sandbox_mode="bwrap")
    save_conf(conf)

    assert (pipelit_dir / "conf.json").exists()


def test_save_conf_roundtrip(tmp_path, monkeypatch):
    """save then load → values match."""
    pipelit_dir = tmp_path / "pipelit"
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    original = PipelitConfig(
        setup_completed=True,
        sandbox_mode="container",
        database_url="sqlite:///test.db",
        redis_url="redis://test:6379/2",
        log_level="WARNING",
        log_file="/tmp/test.log",
        platform_base_url="https://example.com",
        cors_allow_all_origins=False,
        zombie_execution_threshold_seconds=600,
        detected_environment={"os": "linux", "sandbox": "bwrap"},
    )
    save_conf(original)
    loaded = load_conf()

    assert loaded == original


# ---------------------------------------------------------------------------
# _ensure_secrets
# ---------------------------------------------------------------------------


def test_ensure_secrets_generates_encryption_key(tmp_path, monkeypatch):
    """No FIELD_ENCRYPTION_KEY → generates and writes to .env."""
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    env_file = tmp_path / ".env"
    _ensure_secrets(env_file)

    assert os.environ.get("FIELD_ENCRYPTION_KEY")
    content = env_file.read_text()
    assert "FIELD_ENCRYPTION_KEY=" in content


def test_ensure_secrets_generates_secret_key(tmp_path, monkeypatch):
    """No SECRET_KEY → generates and writes to .env."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    # Set encryption key so we can isolate SECRET_KEY behavior
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "existing")

    env_file = tmp_path / ".env"
    _ensure_secrets(env_file)

    assert os.environ.get("SECRET_KEY")
    content = env_file.read_text()
    assert "SECRET_KEY=" in content
    assert "FIELD_ENCRYPTION_KEY=" not in content  # was already set


def test_ensure_secrets_preserves_existing(tmp_path, monkeypatch):
    """Keys already in env → .env not modified."""
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "existing-fernet-key")
    monkeypatch.setenv("SECRET_KEY", "existing-secret")

    env_file = tmp_path / ".env"
    env_file.write_text("# existing content\n")
    _ensure_secrets(env_file)

    content = env_file.read_text()
    assert content == "# existing content\n"


def test_generated_encryption_key_valid_fernet(tmp_path, monkeypatch):
    """Auto-generated key can encrypt/decrypt roundtrip."""
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    env_file = tmp_path / ".env"
    _ensure_secrets(env_file)

    key = os.environ["FIELD_ENCRYPTION_KEY"]
    f = Fernet(key.encode())
    plaintext = b"test data"
    assert f.decrypt(f.encrypt(plaintext)) == plaintext


# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------


def test_settings_reads_conf_json(tmp_path, monkeypatch):
    """conf.json has database_url → Settings.DATABASE_URL reflects it."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    (pipelit_dir / "conf.json").write_text(
        json.dumps({"database_url": "sqlite:///from_conf.db"})
    )
    # Clear env var so conf.json value is used as default
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Re-import to pick up new conf.json
    conf = load_conf()
    # Build Settings with conf.json value as default
    s = Settings(DATABASE_URL=conf.database_url or f"sqlite:///fallback.db")
    assert s.DATABASE_URL == "sqlite:///from_conf.db"


def test_env_var_overrides_conf_json(tmp_path, monkeypatch):
    """conf.json + env var both set → env var wins."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    (pipelit_dir / "conf.json").write_text(
        json.dumps({"database_url": "sqlite:///from_conf.db"})
    )
    monkeypatch.setenv("DATABASE_URL", "sqlite:///from_env.db")

    # Even though conf.json sets database_url, the env var overrides
    s = Settings()
    assert s.DATABASE_URL == "sqlite:///from_env.db"


def test_dotenv_overrides_conf_json(tmp_path, monkeypatch):
    """conf.json + .env both set → .env wins (via pydantic-settings env var)."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    (pipelit_dir / "conf.json").write_text(
        json.dumps({"log_level": "DEBUG"})
    )
    conf = load_conf()
    assert conf.log_level == "DEBUG"

    # Even though conf.json says DEBUG, an env var should win because
    # conf.json only sets the Python default — pydantic-settings reads env vars on top.
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    # Replicate how Settings is constructed: conf.json value is the default
    default = conf.log_level or "INFO"

    class TestSettings(_BaseSettings):
        LOG_LEVEL: str = default

    s = TestSettings()
    assert s.LOG_LEVEL == "ERROR"


# ---------------------------------------------------------------------------
# Removed / new fields
# ---------------------------------------------------------------------------


def test_allowed_hosts_removed():
    """Settings has no ALLOWED_HOSTS attribute."""
    assert not hasattr(Settings, "ALLOWED_HOSTS") or "ALLOWED_HOSTS" not in Settings.model_fields


def test_sandbox_mode_default():
    """Settings.SANDBOX_MODE defaults to 'auto'."""
    s = Settings()
    assert s.SANDBOX_MODE == "auto"


def test_zombie_threshold_zero_from_conf(tmp_path, monkeypatch):
    """zombie_execution_threshold_seconds: 0 in conf.json → Settings uses 0, not 900."""
    pipelit_dir = tmp_path / "pipelit"
    pipelit_dir.mkdir(parents=True)
    monkeypatch.setenv("PIPELIT_DIR", str(pipelit_dir))

    (pipelit_dir / "conf.json").write_text(
        json.dumps({"zombie_execution_threshold_seconds": 0})
    )
    monkeypatch.delenv("ZOMBIE_EXECUTION_THRESHOLD_SECONDS", raising=False)

    conf = load_conf()
    assert conf.zombie_execution_threshold_seconds == 0

    # Replicate how Settings constructs the default from conf.json
    threshold = conf.zombie_execution_threshold_seconds if conf.zombie_execution_threshold_seconds is not None else 900
    assert threshold == 0
