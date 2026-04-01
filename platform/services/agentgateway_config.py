"""Agentgateway config writer service -- provider/model structure.

Manages the config.d/backends/ directory tree where each provider gets a
subdirectory containing a shared ``_provider.yaml`` and one YAML file per
model.  Assembly (assemble-config.sh) merges these into routes automatically.

Directory layout::

    config.d/backends/
    +-- venice/
    |   +-- _provider.yaml     # shared: provider type, hostOverride, pathOverride, backendAuth, backendTLS
    |   +-- glm-4.7.yaml       # model: zai-org-glm-4.7
    |   +-- deepseek-r1.yaml   # model: deepseek-r1-0528
    keys/
    +-- venice.key             # one Fernet-encrypted key per provider

Encryption flow:
  Write path: Pipelit admin action -> write_provider_key() -> Fernet encrypt -> keys/<provider>.key
  Load path:  start.sh -> decrypt_keys.py -> Fernet decrypt -> export env var -> exec agentgateway

Key file naming convention (LOAD-BEARING):
  keys/venice.key   -> $VENICE_API_KEY   -> backendAuth.key: ${VENICE_API_KEY}
  keys/openai.key   -> $OPENAI_API_KEY   -> backendAuth.key: ${OPENAI_API_KEY}
"""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from pathlib import Path

import yaml
from cryptography.fernet import Fernet

from config import settings


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the platform's FIELD_ENCRYPTION_KEY."""
    key = settings.FIELD_ENCRYPTION_KEY
    if not key:
        raise RuntimeError("FIELD_ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def _agw_dir() -> Path:
    """Return the agentgateway installation directory."""
    d = settings.AGENTGATEWAY_DIR
    if not d:
        raise RuntimeError("AGENTGATEWAY_DIR is not set")
    return Path(d)


def _name_to_env_var(name: str) -> str:
    """Convert a provider name to the env var name used by start.sh.

    Examples:
        venice      -> VENICE_API_KEY
        openai      -> OPENAI_API_KEY
        my-backend  -> MY_BACKEND_API_KEY
    """
    return name.upper().replace("-", "_").replace(".", "_") + "_API_KEY"


def _build_provider_type(provider_type: str) -> dict:
    """Build the provider config dict for a _provider.yaml.

    Supported types: openai, anthropic, glm, openai_compatible.
    """
    if provider_type == "anthropic":
        return {"anthropic": {}}
    # openai, openai_compatible, glm all use the openAI provider key
    return {"openAI": {}}


# ---------------------------------------------------------------------------
# Provider key management
# ---------------------------------------------------------------------------


def write_provider_key(provider: str, api_key: str) -> None:
    """Write Fernet-encrypted API key to AGENTGATEWAY_DIR/keys/<provider>.key.

    Atomic write: write to .tmp, then os.rename().
    File permissions: 0o600.
    """
    keys_dir = _agw_dir() / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)

    encrypted = _get_fernet().encrypt(api_key.encode())
    tmp_path = keys_dir / f"{provider}.key.tmp"
    final_path = keys_dir / f"{provider}.key"

    tmp_path.write_bytes(encrypted)
    os.chmod(tmp_path, 0o600)
    os.rename(tmp_path, final_path)


def remove_provider_key(provider: str) -> None:
    """Remove key file for a provider."""
    key_path = _agw_dir() / "keys" / f"{provider}.key"
    key_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Provider management
# ---------------------------------------------------------------------------


def add_provider(
    provider: str,
    provider_type: str,
    host_override: str = "",
    path_override: str = "",
) -> None:
    """Write _provider.yaml to config.d/backends/<provider>/.

    Creates the provider directory if needed.
    Does NOT trigger reassembly (caller should add models first, then reassemble).
    """
    provider_dir = _agw_dir() / "config.d" / "backends" / provider
    provider_dir.mkdir(parents=True, exist_ok=True)

    env_var_ref = f"${{{_name_to_env_var(provider)}}}"

    fragment: dict = {
        "provider": _build_provider_type(provider_type),
        "backendAuth": {"key": env_var_ref},
        "backendTLS": {},
    }

    if host_override:
        fragment["hostOverride"] = host_override
    if path_override:
        fragment["pathOverride"] = path_override

    content = f"# {provider} provider config\n" + yaml.dump(
        fragment, default_flow_style=False, sort_keys=False
    )

    tmp_path = provider_dir / "_provider.yaml.tmp"
    final_path = provider_dir / "_provider.yaml"

    tmp_path.write_text(content)
    os.rename(tmp_path, final_path)


def remove_provider(provider: str) -> None:
    """Remove entire config.d/backends/<provider>/ directory + keys/<provider>.key, then reassemble."""
    provider_dir = _agw_dir() / "config.d" / "backends" / provider
    if provider_dir.exists():
        shutil.rmtree(provider_dir)
    remove_provider_key(provider)
    reassemble_config()


def list_providers() -> list[str]:
    """List provider names from config.d/backends/*/ subdirectories."""
    backends_dir = _agw_dir() / "config.d" / "backends"
    if not backends_dir.exists():
        return []
    return sorted(d.name for d in backends_dir.iterdir() if d.is_dir())


def get_provider_config(provider: str) -> dict:
    """Read and return the _provider.yaml contents for a provider."""
    provider_file = _agw_dir() / "config.d" / "backends" / provider / "_provider.yaml"
    if not provider_file.exists():
        raise FileNotFoundError(f"Provider config not found: {provider}")
    return yaml.safe_load(provider_file.read_text())


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------


def add_model(
    provider: str,
    model_slug: str,
    model_name: str,
    reassemble: bool = True,
) -> None:
    """Write model file to config.d/backends/<provider>/<model_slug>.yaml.

    Content is just: model: <model_name>
    Optionally triggers reassembly (set reassemble=False for batch adds).
    """
    provider_dir = _agw_dir() / "config.d" / "backends" / provider
    provider_dir.mkdir(parents=True, exist_ok=True)

    content = yaml.dump({"model": model_name}, default_flow_style=False)

    tmp_path = provider_dir / f"{model_slug}.yaml.tmp"
    final_path = provider_dir / f"{model_slug}.yaml"

    tmp_path.write_text(content)
    os.rename(tmp_path, final_path)

    if reassemble:
        reassemble_config()


def remove_model(provider: str, model_slug: str) -> None:
    """Remove model file, then reassemble."""
    model_path = (
        _agw_dir() / "config.d" / "backends" / provider / f"{model_slug}.yaml"
    )
    model_path.unlink(missing_ok=True)
    reassemble_config()


def list_models(provider: str) -> list[dict]:
    """List models for a provider.

    Returns [{slug, model_name, route}] by scanning
    config.d/backends/<provider>/*.yaml (excluding _provider.yaml).
    """
    provider_dir = _agw_dir() / "config.d" / "backends" / provider
    if not provider_dir.exists():
        return []

    models = []
    for f in sorted(provider_dir.glob("*.yaml")):
        if f.name == "_provider.yaml":
            continue
        slug = f.stem
        data = yaml.safe_load(f.read_text())
        model_name = data.get("model", "") if data else ""
        models.append({
            "slug": slug,
            "model_name": model_name,
            "route": f"{provider}-{slug}",
        })
    return models


def list_all_available_models() -> list[dict]:
    """List ALL available models across ALL providers.

    Only includes providers that have a matching keys/<provider>.key file.
    Returns [{route, provider, model_slug, model_name}].
    """
    agw = _agw_dir()
    backends_dir = agw / "config.d" / "backends"
    keys_dir = agw / "keys"

    if not backends_dir.exists():
        return []

    result = []
    for provider_dir in sorted(backends_dir.iterdir()):
        if not provider_dir.is_dir():
            continue
        provider = provider_dir.name

        # Only include providers with a key file
        if not keys_dir.exists() or not (keys_dir / f"{provider}.key").exists():
            continue

        for f in sorted(provider_dir.glob("*.yaml")):
            if f.name == "_provider.yaml":
                continue
            slug = f.stem
            data = yaml.safe_load(f.read_text())
            model_name = data.get("model", "") if data else ""
            result.append({
                "route": f"{provider}-{slug}",
                "provider": provider,
                "model_slug": slug,
                "model_name": model_name,
            })

    return result


# ---------------------------------------------------------------------------
# MCP server management
# ---------------------------------------------------------------------------


def add_mcp_server(name: str, config: dict) -> None:
    """Write an MCP server target to config.d/mcp_servers/<name>.yaml."""
    mcp_dir = _agw_dir() / "config.d" / "mcp_servers"
    mcp_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = mcp_dir / f"{name}.yaml.tmp"
    final_path = mcp_dir / f"{name}.yaml"

    content = f"# {name} MCP server\n" + yaml.dump(
        config, default_flow_style=False, sort_keys=False
    )
    tmp_path.write_text(content)
    os.rename(tmp_path, final_path)

    reassemble_config()


def remove_mcp_server(name: str) -> None:
    """Remove an MCP server target, then reassemble."""
    path = _agw_dir() / "config.d" / "mcp_servers" / f"{name}.yaml"
    path.unlink(missing_ok=True)
    reassemble_config()


# ---------------------------------------------------------------------------
# Authorization rules
# ---------------------------------------------------------------------------


def update_rules(role: str, rules: list[str]) -> None:
    """Write CEL rules to config.d/rules/<role>.yaml."""
    rules_dir = _agw_dir() / "config.d" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = rules_dir / f"{role}.yaml.tmp"
    final_path = rules_dir / f"{role}.yaml"

    content = f"# {role} role authorization rules\n" + yaml.dump(
        rules, default_flow_style=False, sort_keys=False
    )
    tmp_path.write_text(content)
    os.rename(tmp_path, final_path)

    reassemble_config()


# ---------------------------------------------------------------------------
# Config assembly
# ---------------------------------------------------------------------------


def reassemble_config() -> None:
    """Call assemble-config.sh to regenerate config.yaml from fragments.

    Uses file locking to prevent concurrent reassembly.
    agentgateway hot-reloads within ~250ms.
    """
    agw_dir = _agw_dir()
    lock_path = agw_dir / ".config.lock"

    with open(lock_path, "w") as lockfile:
        fcntl.flock(lockfile, fcntl.LOCK_EX)
        try:
            result = subprocess.run(
                [str(agw_dir / "assemble-config.sh")],
                capture_output=True,
                text=True,
                cwd=str(agw_dir),
                env={**os.environ, "YQ": os.environ.get("YQ", "yq")},
            )
            if result.returncode != 0:
                raise RuntimeError(f"Config assembly failed: {result.stderr}")
        finally:
            fcntl.flock(lockfile, fcntl.LOCK_UN)


def restart_agentgateway() -> None:
    """Restart agentgateway by killing existing process and re-running start.sh.

    Required when new provider keys are added or existing keys are updated,
    because env vars (decrypted from key files) are only loaded at startup.

    Not needed for model add/remove — config hot-reload handles that.
    """
    import signal
    import time

    agw_dir = _agw_dir()
    start_script = agw_dir / "start.sh"

    if not start_script.exists():
        raise RuntimeError(f"start.sh not found at {start_script}")

    # Find and kill existing agentgateway process
    try:
        result = subprocess.run(
            ["pgrep", "-f", "agentgateway.*config.yaml"],
            capture_output=True, text=True,
        )
        for pid_str in result.stdout.strip().split("\n"):
            if pid_str.strip():
                try:
                    os.kill(int(pid_str.strip()), signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
    except Exception:
        pass  # No process found — that's OK

    time.sleep(2)  # Wait for graceful shutdown

    # Build env for start.sh
    env = {**os.environ}
    env["YQ"] = os.environ.get("YQ", "yq")

    # Find Python with cryptography for decrypt_keys.py
    from config import settings
    pipelit_dir = str(Path(settings.AGENTGATEWAY_DIR).parent / "pipelit")
    venv_python = Path(pipelit_dir) / ".venv" / "bin" / "python3"
    if venv_python.exists():
        env["PYTHON"] = str(venv_python)

    if settings.FIELD_ENCRYPTION_KEY:
        env["FIELD_ENCRYPTION_KEY"] = settings.FIELD_ENCRYPTION_KEY

    # Start in background (detached)
    subprocess.Popen(
        [str(start_script)],
        cwd=str(agw_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
