# Plan: Configurable Sandbox Mode for Container Environments

> **Created:** 2026-02-25
> **Status:** Draft
> **Motivation:** bwrap requires user namespaces which are unavailable in Docker containers, GitHub Codespaces, Gitpod, and most container-based deployment platforms. In these environments the container itself already provides filesystem/network/PID isolation — bwrap is redundant and its absence triggers a misleading warning.

## Problem

`SandboxedShellBackend` in `platform/components/sandboxed_backend.py` currently:
1. Checks if `bwrap` binary exists
2. If yes → full sandbox via Linux namespaces
3. If no → falls back to unsandboxed `LocalShellBackend.execute()` with a `logger.warning()`

This means every deep agent execution in a container environment logs a scary "no sandbox tool found" warning, even though the container IS the sandbox.

## Design

Add a `SANDBOX_MODE` environment variable with three values:

| Value | Behavior | Use case |
|---|---|---|
| `auto` (default) | Use bwrap if available, else detect container environment, else warn + fallback | Smart default for all environments |
| `container` | Skip bwrap entirely, no warning — trust the container boundary | Explicit opt-in for Docker/Codespaces/Gitpod |
| `bwrap` | Require bwrap, **raise an error** if missing instead of falling back | Bare metal deployments that require enforcement |

### Container Auto-Detection (`auto` mode)

When bwrap is not found and mode is `auto`, check for container signals before warning:

```python
def _detect_container() -> str | None:
    """Detect if running inside a known container environment."""
    # Docker
    if os.path.exists("/.dockerenv"):
        return "docker"
    # GitHub Codespaces
    if os.environ.get("CODESPACES") == "true":
        return "codespaces"
    # Gitpod
    if os.environ.get("GITPOD_WORKSPACE_ID"):
        return "gitpod"
    # Generic container: check cgroup
    try:
        cgroup = Path("/proc/1/cgroup").read_text()
        if "docker" in cgroup or "kubepods" in cgroup or "containerd" in cgroup:
            return "container"
    except (FileNotFoundError, PermissionError):
        pass
    # cgroup v2: check if containerenv exists (Podman)
    if os.path.exists("/run/.containerenv"):
        return "podman"
    return None
```

### Behavior Matrix

```
SANDBOX_MODE=auto (default):
  bwrap found        → use bwrap sandbox
  bwrap missing + container detected → unsandboxed, INFO log: "Running inside {env}, container provides isolation"
  bwrap missing + no container       → unsandboxed, WARNING log: "No sandbox tool found" (current behavior)

SANDBOX_MODE=container:
  always              → unsandboxed, INFO log: "SANDBOX_MODE=container, trusting container boundary"

SANDBOX_MODE=bwrap:
  bwrap found         → use bwrap sandbox
  bwrap missing       → raise RuntimeError("SANDBOX_MODE=bwrap but bwrap not found. Install with: apt install bubblewrap")
```

---

## Files to Change

### 1. `platform/components/sandboxed_backend.py`

**Add `_detect_container()` function** (after `_detect_sandbox()`):
- Check `/.dockerenv`, env vars (`CODESPACES`, `GITPOD_WORKSPACE_ID`), `/proc/1/cgroup`, `/run/.containerenv`
- Return a string label or `None`

**Modify `_detect_sandbox()`** to return a richer result:
```python
@dataclass
class SandboxInfo:
    tool: str | None        # "bwrap" or None
    container: str | None   # "docker", "codespaces", "gitpod", "container", "podman", or None
    mode: str               # "auto", "container", "bwrap"
```

Or simpler: keep `_detect_sandbox()` returning `str | None` and add a separate `_resolve_sandbox_mode()` that combines config + detection:

```python
def _resolve_sandbox_mode() -> tuple[str | None, bool]:
    """Returns (sandbox_tool, is_container).

    sandbox_tool: "bwrap" if should use bwrap, None if unsandboxed
    is_container: True if running in a detected/declared container (suppresses warning)
    """
    mode = os.environ.get("SANDBOX_MODE", "auto").lower()

    if mode == "container":
        return None, True

    tool = _detect_sandbox()  # checks for bwrap binary

    if mode == "bwrap":
        if tool is None:
            raise RuntimeError(
                "SANDBOX_MODE=bwrap but bwrap is not available. "
                "Install with: apt install bubblewrap"
            )
        return tool, False

    # mode == "auto"
    if tool:
        return tool, False

    container = _detect_container()
    if container:
        return None, True  # container provides isolation

    return None, False  # genuine fallback, will warn
```

**Modify `SandboxedShellBackend.__init__()`**:
- Call `_resolve_sandbox_mode()` instead of `_detect_sandbox()`
- Store `self._is_container` alongside `self._sandbox_tool`
- Adjust log messages:

```python
if self._sandbox_tool:
    logger.info("SandboxedShellBackend: using %s for workspace %s", self._sandbox_tool, root_dir)
elif self._is_container:
    logger.info(
        "SandboxedShellBackend: container environment detected, "
        "trusting container isolation for workspace %s", root_dir,
    )
else:
    logger.warning(
        "SandboxedShellBackend: no sandbox tool found (install bwrap or use Docker). "
        "Falling back to unsandboxed execution for workspace %s", root_dir,
    )
```

**No changes to `execute()`** — it already checks `self._sandbox_tool is None` and falls back. The fallback path is identical for container and no-sandbox modes; only the log level differs.

### 2. `platform/config.py`

Add `SANDBOX_MODE` to the Pydantic Settings class:

```python
SANDBOX_MODE: str = "auto"  # "auto", "container", "bwrap"
```

Then in `sandboxed_backend.py`, read from `os.environ.get("SANDBOX_MODE", "auto")` directly (the backend is instantiated in component code, not via dependency injection, so reading the env var directly is simpler than threading the config through).

### 3. `platform/tests/test_sandboxed_backend.py`

**Add new test class `TestSandboxModeConfig`:**

```python
class TestSandboxModeConfig:
    def test_auto_mode_with_bwrap(self, tmp_path):
        """auto mode uses bwrap when available."""
        with patch("components.sandboxed_backend.shutil.which", return_value="/usr/bin/bwrap"), \
             patch.dict(os.environ, {"SANDBOX_MODE": "auto"}):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))
            assert backend._sandbox_tool == "bwrap"

    def test_auto_mode_detects_docker(self, tmp_path):
        """auto mode detects Docker and suppresses warning."""
        with patch("components.sandboxed_backend._detect_sandbox", return_value=None), \
             patch("os.path.exists", side_effect=lambda p: p == "/.dockerenv"), \
             patch.dict(os.environ, {"SANDBOX_MODE": "auto"}):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))
            assert backend._sandbox_tool is None
            assert backend._is_container is True

    def test_auto_mode_detects_codespaces(self, tmp_path):
        """auto mode detects GitHub Codespaces."""
        with patch("components.sandboxed_backend._detect_sandbox", return_value=None), \
             patch("components.sandboxed_backend._detect_container", return_value="codespaces"), \
             patch.dict(os.environ, {"SANDBOX_MODE": "auto"}):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))
            assert backend._is_container is True

    def test_container_mode_skips_bwrap(self, tmp_path):
        """container mode skips bwrap even if available."""
        with patch.dict(os.environ, {"SANDBOX_MODE": "container"}):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))
            assert backend._sandbox_tool is None
            assert backend._is_container is True

    def test_bwrap_mode_raises_when_missing(self, tmp_path):
        """bwrap mode raises RuntimeError if bwrap not found."""
        with patch("components.sandboxed_backend._detect_sandbox", return_value=None), \
             patch.dict(os.environ, {"SANDBOX_MODE": "bwrap"}):
            with pytest.raises(RuntimeError, match="bwrap is not available"):
                SandboxedShellBackend(root_dir=str(tmp_path))

    def test_bwrap_mode_works_when_present(self, tmp_path):
        """bwrap mode succeeds when bwrap is available."""
        with patch("components.sandboxed_backend.shutil.which", return_value="/usr/bin/bwrap"), \
             patch.dict(os.environ, {"SANDBOX_MODE": "bwrap"}):
            backend = SandboxedShellBackend(root_dir=str(tmp_path))
            assert backend._sandbox_tool == "bwrap"
```

**Add new test class `TestContainerDetection`:**

```python
class TestContainerDetection:
    def test_detect_dockerenv(self):
        with patch("os.path.exists", side_effect=lambda p: p == "/.dockerenv"):
            assert _detect_container() == "docker"

    def test_detect_codespaces_env(self):
        with patch("os.path.exists", return_value=False), \
             patch.dict(os.environ, {"CODESPACES": "true"}):
            assert _detect_container() == "codespaces"

    def test_detect_gitpod_env(self):
        with patch("os.path.exists", return_value=False), \
             patch.dict(os.environ, {"GITPOD_WORKSPACE_ID": "abc123"}):
            assert _detect_container() == "gitpod"

    def test_detect_cgroup_docker(self, tmp_path):
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text("0::/docker/abc123\n")
        with patch("os.path.exists", return_value=False), \
             patch("pathlib.Path.read_text", return_value=cgroup_file.read_text()):
            assert _detect_container() == "container"

    def test_detect_podman(self):
        def exists_check(p):
            return p == "/run/.containerenv"
        with patch("os.path.exists", side_effect=exists_check), \
             patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert _detect_container() == "podman"

    def test_detect_none_on_bare_metal(self):
        with patch("os.path.exists", return_value=False), \
             patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            # Clear container-related env vars
            env = {k: v for k, v in os.environ.items()
                   if k not in ("CODESPACES", "GITPOD_WORKSPACE_ID")}
            with patch.dict(os.environ, env, clear=True):
                assert _detect_container() is None
```

**Update existing tests:**
- `TestSandboxDetection` — existing tests still pass (they mock `_detect_sandbox` directly)
- `TestFallback` — add `_is_container` assertion (should be `False` when using `_detect_sandbox=None` mock without container signals)

---

## Implementation Order

1. **Add `_detect_container()` function** — pure function, easy to test in isolation
2. **Add `_resolve_sandbox_mode()` function** — combines env var + bwrap detection + container detection
3. **Update `SandboxedShellBackend.__init__()`** — use `_resolve_sandbox_mode()`, store `_is_container`, adjust logs
4. **Add `SANDBOX_MODE` to `platform/config.py`** — documentation only, the backend reads env var directly
5. **Write tests** — `TestContainerDetection`, `TestSandboxModeConfig`
6. **Update existing tests** — ensure mocks still work, add `_is_container` assertions where relevant

## What Does NOT Change

- `_build_bwrap_command()` — untouched
- `_prepare_sandbox_root()` — untouched
- `execute()` method — untouched (the `if self._sandbox_tool is None` fallback already does the right thing)
- `deep_agent.py` — untouched (it instantiates `SandboxedShellBackend` which handles mode internally)
- Frontend — no changes
- No new dependencies
- No migration

## Estimated Scope

~60 lines of new code in `sandboxed_backend.py`, ~80 lines of new tests, ~5 lines in `config.py`. One file to edit, one file to add tests to, one config line. No architectural changes.
