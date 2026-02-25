# Plan: Sandbox Mode, Setup Wizard & Platform Configuration

> **Created:** 2026-02-25
> **Updated:** 2026-02-26
> **Status:** Draft
> **Scope:** Environment detection, setup wizard, conf.json, workspace management, code node sandboxing, security architecture

---

## 1. Problem

Multiple related issues with the current platform setup and sandboxing:

1. **bwrap warnings in containers** — `SandboxedShellBackend` logs a scary "no sandbox tool found" warning in Docker/Codespaces/Gitpod even though the container IS the sandbox.
2. **No first-run setup wizard** — users must manually generate `FIELD_ENCRYPTION_KEY`, configure `.env`, and hit the setup API. No environment validation.
3. **Config scattered across `.env`** — platform config, secrets, and legacy bot settings all mixed in one file. No `conf.json`.
4. **macOS unsupported without guidance** — no bwrap on macOS, no `sandbox-exec` implementation, no docs pointing users to Docker.
5. **Workspace paths hardcoded** — `~/.config/pipelit/workspaces/default` doesn't work in Docker, and users can freeform type paths in node config.
6. **Code node has no sandboxing** — `code.py` runs `exec()` in the server process with zero isolation.
7. **`code_execute` is redundant** — duplicates `run_command` with a regex blocklist that provides no real security.
8. **No runtime capability detection** — `deep_agent` discovers missing tools (Node, Python, grep, etc.) only at execution time, leading to cryptic failures.
9. **No pre-flight validation** — `SandboxedShellBackend` doesn't verify the sandbox is still valid at startup if conditions change after setup (e.g., bwrap uninstalled).

---

## 2. Security Architecture

### 2.1 Trust Model

The system has two distinct trust zones:

**Trusted zone — the RQ worker process.** The worker is our code. It manages Redis communication (job pickup, heartbeats, result reporting), database access (workflow state, execution logs), and config file access. It is the security boundary enforcement point. The worker runs unsandboxed because it needs privileged access to orchestrate execution.

**Untrusted zone — the subprocess executing user code.** This is the code node output, `run_command` invocations, and `deep_agent` shell commands. This runs inside the bwrap sandbox (or relies on the container boundary in container mode). It has no access to Redis, the database, secrets, or other workspaces.

```
┌─────────────────────────────────────────────┐
│  Trusted Zone (RQ Worker)                   │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │  Redis    │  │ Database │  │  Config   │ │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘ │
│       │              │              │       │
│  ┌────▼──────────────▼──────────────▼─────┐ │
│  │          RQ Worker Process             │ │
│  │  - Picks up jobs from Redis            │ │
│  │  - Resolves workspace & sandbox mode   │ │
│  │  - Spawns sandboxed subprocess         │ │
│  │  - Reads stdout/stderr/exit code       │ │
│  │  - Reports results back to Redis       │ │
│  │  - Enforces timeouts                   │ │
│  └────────────────┬───────────────────────┘ │
│                   │ subprocess.run()        │
├───────────────────┼─────────────────────────┤
│                   ▼                         │
│  Untrusted Zone (bwrap sandbox)             │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │  Sandboxed Process                     │ │
│  │  - --unshare-all (full NS isolation)   │ │
│  │  - --clearenv    (no secrets leaked)   │ │
│  │  - Workspace as / (read-write)         │ │
│  │  - /usr ro-bind  (system binaries)     │ │
│  │  - No Redis, no DB, no config access   │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

### 2.2 Why not sandbox the worker?

Sandboxing the entire RQ worker creates a chicken-and-egg problem. The worker needs Redis access for job coordination, database access for workflow state, and config access for sandbox resolution. Poking all those holes through the sandbox would leave a weak boundary. The stronger model is: the worker is the gatekeeper, the sandbox wraps only what we don't trust.

### 2.3 Why not in-process sandboxing?

n8n's experience validates this architecture. Their Pyodide approach (Python in WebAssembly inside the main Node.js process) led to three critical CVEs (CVE-2025-68668, CVE-2026-1470, CVE-2026-0863) — all sandbox escapes via blocklist bypasses. Blocklist-based sandboxing is structurally fragile because it assumes the defender can enumerate every dangerous capability. Process-level isolation via bwrap/containers provides a real kernel-enforced boundary.

### 2.4 Sandbox isolation guarantees

| Concern | Mitigation |
|---|---|
| Filesystem access | Workspace mounted as `/` (rw). `/usr` ro-bind for system binaries. No access to `pipelit_dir`, database, other workspaces |
| Network access | `--unshare-all` isolates network by default. `--share-net` opt-in per workspace |
| Environment variables | `--clearenv` wipes all env vars. Only `PATH`, `HOME`, `TMPDIR` set explicitly |
| Process visibility | `--unshare-all` includes PID namespace — cannot see host processes |
| IPC | `--unshare-all` includes IPC namespace — isolated shared memory and semaphores |
| Secret leakage | Worker never passes `FIELD_ENCRYPTION_KEY`, `SECRET_KEY`, `DATABASE_URL`, or `REDIS_URL` to subprocess |
| Orphan processes | `--die-with-parent` kills sandbox if worker dies |

---

## 3. Environment Detection & Sandbox Modes

### 3.1 `SANDBOX_MODE` values

| Value | Behavior | Use case |
|---|---|---|
| `auto` (default) | Use bwrap if available, else detect container, else warn + fallback | Smart default |
| `container` | Skip bwrap, no warning — trust container boundary | Docker / Codespaces / Gitpod |
| `bwrap` | Require bwrap, **error** if missing | Bare metal Linux enforcement |

### 3.2 Container auto-detection (`auto` mode)

```python
def _detect_container() -> str | None:
    """Detect if running inside a known container environment."""
    if os.path.exists("/.dockerenv"):
        return "docker"
    if os.environ.get("CODESPACES") == "true":
        return "codespaces"
    if os.environ.get("GITPOD_WORKSPACE_ID"):
        return "gitpod"
    try:
        cgroup = Path("/proc/1/cgroup").read_text()
        if "docker" in cgroup or "kubepods" in cgroup or "containerd" in cgroup:
            return "container"
    except (FileNotFoundError, PermissionError):
        pass
    if os.path.exists("/run/.containerenv"):
        return "podman"
    return None
```

### 3.3 Behavior matrix

| Environment | bwrap | container | Result |
|---|---|---|---|
| Linux bare metal | yes | no | bwrap sandbox |
| Linux bare metal | no | no | **Blocked at setup wizard** — must install bwrap |
| Docker / k8s | no | yes | container-trusted, no warning |
| macOS bare metal | no | no | **Blocked at setup wizard** — must use Docker |

### 3.4 macOS policy

No `sandbox-exec` implementation. Documentation recommends macOS users run Pipelit in Docker. The setup wizard blocks bare-metal macOS with a clear message.

---

## 4. Runtime Capability Detection

### 4.1 Purpose

Both the setup wizard and the agent need to know what tools are available in the execution environment. A GitHub Codespace might have Python but not Node. A minimal Docker image might lack `jq` or `curl`. Rather than discovering failures mid-pipeline, we detect capabilities upfront.

### 4.2 Implementation

A single Python `detect_capabilities()` function runs at **server startup** and caches results in memory. Since `/usr` is ro-bind mounted into the sandbox, host-side detection accurately reflects what's available inside the sandbox.

```python
def detect_capabilities(workspace_path: str | None = None) -> dict:
    """Detect available runtimes, tools, network, and filesystem permissions.

    Run at: server startup (cached in memory), setup wizard, re-check from Settings.
    """
    return {
        "runtimes": _detect_runtimes(),       # python3, node, pip, etc. with versions
        "shell_tools": _detect_shell_tools(),  # ls, grep, curl, git, jq, etc.
        "network": _detect_network(),          # DNS + HTTP outbound
        "filesystem": _detect_filesystem(workspace_path),
        "system": _detect_system(),            # os, arch, user, pid1
    }
```

Checks ~30 binaries via `shutil.which()` + version subprocesses. Runs once at startup (~2-3s), not per-execute.

### 4.3 Where capabilities are used

| Consumer | When | Purpose |
|---|---|---|
| Setup wizard | First run | Gate: block if critical tools missing. Display available runtimes |
| `conf.json` | Setup + startup | Cache in `detected_environment.capabilities`. Re-validate on restart, warn if changed |
| Settings page | On load | Read-only display of current capabilities |
| Agent session | Session start | Inject into system context so agent knows what it can use |
| Node config UI | Editor load | Show warnings if selected language/runtime unavailable |

### 4.4 Agent context injection

At the start of a `deep_agent` session, the cached capability report is injected as a system message:

```
You are operating in a sandboxed environment with the following capabilities:

Runtimes: python3 (3.11.6), pip3 (23.2.1). Node.js is NOT available.
Shell tools: ls, grep, sed, awk, cat, head, tail, find, curl, git, tar, jq.
  Missing: wget, unzip.
Network: DNS available, HTTP outbound available.
Filesystem: Workspace is read-write. /tmp is writable.

Plan your approach using only available tools. Do not attempt to install
packages or runtimes that are not present.
```

---

## 5. Sandbox Resolution & Startup Validation

### 5.1 `SandboxResolution` dataclass

```python
@dataclass
class SandboxResolution:
    """Result of resolving the sandbox mode against current environment."""
    mode: str               # "bwrap", "container", "none"
    can_execute: bool        # Whether execution is safe to proceed
    reason: str | None       # Why execution is blocked (if can_execute is False)
    container_type: str | None  # "docker", "codespaces", "gitpod", etc.
```

### 5.2 Resolution function

```python
def _resolve_sandbox_mode(config_mode: str) -> SandboxResolution:
    """Resolve configured sandbox mode against actual environment.
    Called at server startup and SandboxedShellBackend.__init__().
    """
    container = _detect_container()
    bwrap_available = shutil.which("bwrap") is not None

    if config_mode == "bwrap":
        if not bwrap_available:
            return SandboxResolution(
                mode="none", can_execute=False,
                reason="sandbox_mode is 'bwrap' but bwrap is not installed",
                container_type=container,
            )
        return SandboxResolution(mode="bwrap", can_execute=True, reason=None, container_type=container)

    if config_mode == "container":
        if not container:
            return SandboxResolution(
                mode="none", can_execute=False,
                reason="sandbox_mode is 'container' but no container environment detected",
                container_type=None,
            )
        return SandboxResolution(mode="container", can_execute=True, reason=None, container_type=container)

    # auto mode
    if bwrap_available:
        return SandboxResolution(mode="bwrap", can_execute=True, reason=None, container_type=container)
    if container:
        return SandboxResolution(mode="container", can_execute=True, reason=None, container_type=container)

    return SandboxResolution(
        mode="none", can_execute=False,
        reason="No sandbox available: bwrap not found and not in a container",
        container_type=None,
    )
```

### 5.3 Startup re-validation

On server startup, the stored `detected_environment` in `conf.json` is compared against a fresh detection. If conditions have changed (e.g., bwrap was available at setup but is now missing), the server logs a warning and updates the cached state.

---

## 6. bwrap Command Hardening

### 6.1 Changes to existing `_build_bwrap_command()`

The current implementation already uses workspace-as-root (`--bind workspace /`) and `--unshare-all`. The key addition is `--clearenv` to prevent secret leakage:

```python
# Current (keep):
args = ["bwrap", "--unshare-all"]
args += ["--bind", workspace, "/"]       # workspace as root filesystem
args += ["--ro-bind", "/usr", "/usr"]    # system binaries read-only
# ... existing /etc, /proc, /dev mounts ...
args += ["--die-with-parent"]
args += ["--chdir", "/"]

# NEW — add --clearenv and explicit env vars:
args += ["--clearenv"]                   # wipe ALL inherited env vars
args += [
    "--setenv", "HOME", "/",
    "--setenv", "PATH", f"/.venv/bin:/usr/bin:/bin",
    "--setenv", "TMPDIR", "/tmp",
    "--setenv", "LANG", "C.UTF-8",
]
```

This replaces the current `--setenv` calls (which add to the inherited env) with `--clearenv` + explicit vars (which starts clean). The worker's `FIELD_ENCRYPTION_KEY`, `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL` etc. are never passed to the subprocess.

### 6.2 Network access toggle

Some legitimate pipelines need HTTP access (API calls, web scraping). Network access is configurable per-workspace via `allow_network` (default `False`). When enabled, `--share-net` is added to the bwrap command (already supported in current code).

### 6.3 Container mode environment scrubbing

In container mode, bwrap is not used but we still scrub the environment for subprocess calls:

```python
def _build_sandbox_env(self, workspace_path: str) -> dict:
    """Build a clean environment for container-mode subprocess execution."""
    return {
        "PATH": f"{workspace_path}/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        # Explicitly DO NOT include:
        # FIELD_ENCRYPTION_KEY, SECRET_KEY, DATABASE_URL, REDIS_URL
    }
```

---

## 7. Setup Wizard

### 7.1 Flow

**Step 1: Environment Check (gate)**
- Auto-detect: OS, bwrap availability, container environment, runtime capabilities
- **Linux + bwrap** → pass
- **Container detected** → pass (sandbox_mode = container)
- **Linux bare metal + no bwrap** → **blocked**: "bwrap is required. Install with `apt install bubblewrap`" + Re-check button
- **macOS bare metal** → **blocked**: "macOS requires Docker. See setup docs." + link
- Display detected runtimes and tools (informational, not blocking)
- Advanced expandable section for overriding: `redis_url`, `database_url`, `log_level`, `platform_base_url`, etc.

**Step 2: Create Admin Account**
- Username + password

**Step 3: Done**
- Auto-generate `FIELD_ENCRYPTION_KEY` + `SECRET_KEY` → append to `.env`
- Write `conf.json` to `{pipelit_dir}/conf.json` (including `detected_environment` with capabilities)
- Create admin user in database
- Create "default" workspace
- Mark `setup_completed: true`

### 7.2 Pre-flight (server startup)

Before the wizard UI loads, the server checks:
1. If `FIELD_ENCRYPTION_KEY` is empty → auto-generate Fernet key, append to `.env`, set in `os.environ`
2. This must happen before SQLAlchemy model import since `EncryptedString` reads the env var at module load time
3. Re-validate `detected_environment` against current state (see Section 5.3)

### 7.3 API changes

- `GET /auth/setup-status/` — extended to return `{ needs_setup: bool, environment: { os, container, bwrap_available, capabilities } }`
- `POST /auth/setup/` — expanded to accept `sandbox_mode`, `pipelit_dir`, and optional config overrides alongside `username`/`password`

---

## 8. Configuration Architecture

### 8.1 `conf.json` — platform runtime config

Location: `{pipelit_dir}/conf.json` (default `~/.config/pipelit/conf.json`)

Written by the setup wizard, editable via the Settings page.

```json
{
  "setup_completed": true,
  "pipelit_dir": "~/.config/pipelit",
  "sandbox_mode": "auto",
  "database_url": "sqlite:///~/.config/pipelit/db.sqlite3",
  "redis_url": "redis://localhost:6379/0",
  "log_level": "INFO",
  "log_file": "",
  "platform_base_url": "http://localhost:8000",
  "cors_allow_all_origins": true,
  "zombie_execution_threshold_seconds": 900,
  "detected_environment": {
    "os": "linux",
    "container": "docker",
    "bwrap_available": false,
    "capabilities": {
      "runtimes": {
        "python3": {"available": true, "version": "Python 3.11.6"},
        "node": {"available": false}
      },
      "shell_tools": {
        "ls": {"available": true, "busybox": false},
        "grep": {"available": true, "busybox": false},
        "jq": {"available": false}
      },
      "network": {"dns": true, "http": true},
      "filesystem": {"tmp_writable": true},
      "system": {"os": "linux", "arch": "x86_64", "user": "pipelit", "pid1": "tini"}
    }
  }
}
```

### 8.2 `.env` — secrets only

```
FIELD_ENCRYPTION_KEY=<auto-generated Fernet key>
SECRET_KEY=<auto-generated random string>
```

Both auto-generated by the wizard on first run.

### 8.3 Settings load order

1. `conf.json` (platform config)
2. `.env` (secrets)
3. Environment variables (override everything)

### 8.4 Paths derived from `pipelit_dir`

| Path | Derived as |
|---|---|
| Config file | `{pipelit_dir}/conf.json` |
| Skills directory | `{pipelit_dir}/skills/` |
| Default workspace parent | `{pipelit_dir}/workspaces/` |
| Default database | `{pipelit_dir}/db.sqlite3` |
| Checkpoints DB | per-workspace or `{pipelit_dir}/checkpoints.db` |
| MCP config | `{pipelit_dir}/mcp_config.json` (unify from `~/.config/aichat-platform/`) |

### 8.5 Removed config

- `ALLOWED_HOSTS` — dead config, never used (Django-ism). Delete from Settings.
- `WORKSPACE_DIR` — replaced by per-workspace DB records. Default workspace path derived from `pipelit_dir`.
- `SKILLS_DIR` — derived from `pipelit_dir/skills/`.

---

## 9. Workspace Management

### 9.1 Database model

```python
class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. "default", "data-pipeline"
    path: Mapped[str] = mapped_column(String(500))               # resolved absolute path
    allow_network: Mapped[bool] = mapped_column(default=False)   # network access in bwrap
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    user_profile_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id"))
```

Venv is always at `{workspace.path}/.venv` — no separate column needed.

### 9.2 Workspace page (new sidebar item)

- List registered workspaces (name, path, network access, created date)
- Create workspace — name required, path auto-derived as `{pipelit_dir}/workspaces/{name}` (overridable)
- Toggle network access per workspace
- Delete workspace (with confirmation)
- A "default" workspace is auto-created during setup wizard

### 9.3 Node config integration

- `deep_agent`, `code`, and future sandbox-using nodes get a **workspace dropdown** instead of freeform text
- `extra_config.workspace_id` references the `Workspace.id`
- Workspace path resolved at execution time from the DB record

### 9.4 Future extensions

Workspaces are the unit of isolation that grows over time:
- Filesystem + venv (current)
- Git repo initialization
- GitHub auth (per-workspace `gh` config)
- Per-workspace credentials
- Per-workspace environment variables

---

## 10. Code Node Sandboxing

### 10.1 Current state

- **`code.py`** — in-process `exec()`, zero isolation, category `logic`
- **`code_execute.py`** — subprocess + regex blocklist, category `sub_component` (tool for agents)
- **`run_command.py`** — subprocess `shell=True`, category `sub_component` (tool for agents)

### 10.2 Changes

**Remove `code_execute`** — redundant with `run_command`. The regex blocklist is security theater since `run_command` has no such restrictions. Remove:
- `platform/components/code_execute.py`
- `platform/schemas/node_type_defs.py` — remove `code_execute` registration
- `platform/frontend/` — remove any `code_execute` references in types/palette

**Sandbox the `code` node** — rewrite from in-process `exec()` to subprocess execution:
1. Write code to a temp file in the workspace
2. Run via `subprocess.run()` (like `code_execute` does today)
3. Wrap in bwrap when available (reuse `_build_bwrap_command()`)
4. In container mode, subprocess with scrubbed env is sufficient

**Sandbox `run_command`** — wrap subprocess calls in bwrap when available, using the workspace assigned to the parent agent node.

---

## 11. Settings Page Expansion

### 11.1 Current state

`/settings` only has theme selection.

### 11.2 New sections

- **Environment** (read-only) — OS, container detection, bwrap status, runtime capabilities, tool availability
- **Sandbox mode** — dropdown: auto / container / bwrap
- **Data directory** (`pipelit_dir`)
- **Database URL**
- **Redis URL**
- **Platform base URL**
- **CORS allow all origins**
- **Logging** — level dropdown, file path
- **Zombie threshold**

### 11.3 Hot-reload vs restart

| Hot-reloadable | Restart required |
|---|---|
| `log_level` | `database_url` |
| `zombie_execution_threshold_seconds` | `redis_url` |
| | `pipelit_dir` |
| | `platform_base_url` |
| | `sandbox_mode` |
| | `cors_allow_all_origins` |

Settings page shows a "Restart required for changes to take effect" banner when restart-required fields are modified.

---

## 12. Implementation Order

### Phase 1: Config Foundation
1. Create `conf.json` schema and loader
2. Update `Settings` class to load from `conf.json` → `.env` → env vars
3. Remove `ALLOWED_HOSTS` from Settings
4. Auto-generate `FIELD_ENCRYPTION_KEY` + `SECRET_KEY` on first startup

### Phase 2: Environment Detection, Capabilities & Sandbox Mode
5. Implement `detect_capabilities()` (Python, cached at startup)
6. Add `_detect_container()` to `sandboxed_backend.py`
7. Implement `_resolve_sandbox_mode()` returning `SandboxResolution`
8. Add `--clearenv` to existing `_build_bwrap_command()`
9. Add `_build_sandbox_env()` for container mode env scrubbing
10. Update `SandboxedShellBackend.__init__()` to use resolved mode
11. Add startup re-validation (`validate_environment_on_startup()`)
12. Tests for container detection, capability detection, sandbox mode config

### Phase 3: Setup Wizard
13. Extend `GET /auth/setup-status/` with environment info and capabilities
14. Extend `POST /auth/setup/` to accept config + write `conf.json` with capabilities
15. Frontend: setup wizard page (environment gate → admin account → done)

### Phase 4: Workspace Management
16. `Workspace` SQLAlchemy model (with `allow_network`) + Alembic migration
17. Workspace CRUD API endpoints
18. Frontend: Workspaces page (sidebar item)
19. Update node config to use workspace dropdown instead of freeform text
20. Create "default" workspace during setup wizard

### Phase 5: Code Node Sandboxing
21. Remove `code_execute` component, node type registration, and frontend references
22. Rewrite `code.py` to use subprocess execution
23. Wrap `code` and `run_command` subprocess calls in bwrap when available
24. Inject capability report into `deep_agent` system context at session start

### Phase 6: Settings Page
25. Expand `/settings` with all `conf.json` fields + capabilities display
26. Implement save → write `conf.json` + hot-reload where possible
27. Restart-required banner for non-hot-reloadable fields
