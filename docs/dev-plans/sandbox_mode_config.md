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

## 12. Frontend Design

All new pages follow existing patterns: Shadcn/ui components, Lucide React icons, `space-y-*` vertical spacing, `Card` sections, `Select` dropdowns, `Table` for lists, `Dialog` for create/edit forms.

### 12.1 Setup Wizard (`/setup`)

Replaces the current single-card setup page. Multi-step flow with a step indicator.

```
┌─────────────────────────────────────────────────────────────┐
│                     Set Up Pipelit                          │
│                                                             │
│          ● Environment ─── ○ Account ─── ○ Done             │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Environment Check                                    │  │
│  │                                                       │  │
│  │  OS            Linux x86_64                      ✓    │  │
│  │  Sandbox       bwrap (/usr/bin/bwrap)            ✓    │  │
│  │  Container     Not detected                      —    │  │
│  │  Python        3.11.6                            ✓    │  │
│  │  Node.js       Not found                         ✗    │  │
│  │  Redis         localhost:6379 (connected)        ✓    │  │
│  │                                                       │  │
│  │  ▸ Advanced Configuration                             │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  Database URL   [sqlite:///~/.config/pipelit/db]│  │  │
│  │  │  Redis URL      [redis://localhost:6379/0     ] │  │  │
│  │  │  Log Level      [INFO ▾]                        │  │  │
│  │  │  Platform URL   [http://localhost:8000        ] │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │                                                       │  │
│  │                                      [ Next → ]       │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Blocked state (Linux no bwrap):**
```
│  │  OS            Linux x86_64                      ✓    │
│  │  Sandbox       Not found                         ✗    │
│  │                                                       │
│  │  ┌─ ⚠ Alert ──────────────────────────────────────┐   │
│  │  │ bwrap is required for sandboxed execution.     │   │
│  │  │ Install with: apt install bubblewrap           │   │
│  │  └────────────────────────────────────────────────┘   │
│  │                                                       │
│  │                    [ Re-check ]  [ Next → ] (disabled)│
```

**Blocked state (macOS):**
```
│  │  OS            macOS arm64                       ✓    │
│  │  Sandbox       Not supported on macOS            ✗    │
│  │                                                       │
│  │  ┌─ ⚠ Alert ──────────────────────────────────────┐   │
│  │  │ macOS is not supported for bare metal installs.│   │
│  │  │ Please run Pipelit in Docker.                  │   │
│  │  │ → Docker Setup Guide                           │   │
│  │  └────────────────────────────────────────────────┘   │
```

**Step 2: Account**
```
│          ✓ Environment ─── ● Account ─── ○ Done             │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Create Admin Account                                 │  │
│  │                                                       │  │
│  │  Username       [                              ]      │  │
│  │  Password       [                              ]      │  │
│  │  Confirm        [                              ]      │  │
│  │                                                       │  │
│  │                          [ ← Back ]  [ Create → ]     │  │
│  └───────────────────────────────────────────────────────┘  │
```

**Step 3: Done**
```
│          ✓ Environment ─── ✓ Account ─── ● Done             │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  ✓  Setup Complete                                    │  │
│  │                                                       │  │
│  │  Admin account created.                               │  │
│  │  Default workspace created at:                        │  │
│  │    ~/.config/pipelit/workspaces/default                │  │
│  │  Configuration saved to:                              │  │
│  │    ~/.config/pipelit/conf.json                         │  │
│  │                                                       │  │
│  │                              [ Go to Dashboard → ]    │  │
│  └───────────────────────────────────────────────────────┘  │
```

**Components used:** `Card`, `Button`, `Input`, `Label`, `Select`, `Alert`, `Badge` (for ✓/✗ status), step indicator (custom, three dots with connecting lines).

### 12.2 Workspaces Page (`/workspaces`)

Follows the CredentialsPage pattern: table + create dialog.

```
┌──────────────────────────────────────────────────────────────────┐
│  Workspaces                                    [ + Add Workspace]│
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  ☐  Name           Path                      Network  Date│  │
│  │  ── ────────────── ──────────────────────── ──────── ─────│  │
│  │  ☐  default        ~/.config/pipelit/works…  Off      Feb │  │
│  │  ☐  data-pipeline  ~/.config/pipelit/works…  On       Feb │  │
│  │  ☐  research       /mnt/data/research         Off      Feb │  │
│  │                                                            │  │
│  │  ─────────────────────────────────────────────────────────│  │
│  │  Page 1 of 1                                              │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**Create dialog:**
```
┌─────────────────────────────────────────┐
│  Add Workspace                          │
│                                         │
│  Name          [                    ]   │
│                                         │
│  Path          [auto-derived       ]   │
│  (auto-filled from pipelit_dir/         │
│   workspaces/{name}, editable)          │
│                                         │
│  Network Access                         │
│  Allow outbound network   [ toggle ]    │
│  in sandboxed execution                 │
│                                         │
│              [ Cancel ]  [ Create ]     │
└─────────────────────────────────────────┘
```

**Row actions:** Edit (toggle network), Delete (with confirmation dialog, "default" workspace cannot be deleted).

**Components used:** `Table`, `Card`, `Dialog`, `Input`, `Label`, `Switch`, `Button`, `Checkbox`, `Badge` (for network On/Off), `PaginationControls`.

### 12.3 Settings Page Expansion (`/settings`)

Adds new Card sections below existing Appearance/Theme/MFA cards.

```
┌──────────────────────────────────────────────────────────────────┐
│  Settings                                                        │
│                                                                  │
│  ┌── Appearance ──────────────────────────────────────────────┐  │
│  │  (existing: System/Light/Dark theme buttons)               │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── System Theme ────────────────────────────────────────────┐  │
│  │  (existing: color theme dropdown)                          │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── Two-Factor Authentication ───────────────────────────────┐  │
│  │  (existing: MFA enable/disable)                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── Environment ─────────────────────────────────────────────┐  │
│  │                                                             │  │
│  │  OS              linux / x86_64                             │  │
│  │  Container       docker                    [Badge: docker]  │  │
│  │  Sandbox Mode    bwrap                     [Badge: active]  │  │
│  │  bwrap           /usr/bin/bwrap            [Badge: ✓]       │  │
│  │                                                             │  │
│  │  Runtimes        python3 3.11.6  ✓                          │  │
│  │                  node            ✗  not found               │  │
│  │                  pip3 23.2.1     ✓                          │  │
│  │                                                             │  │
│  │  Shell Tools     ls ✓  grep ✓  curl ✓  git ✓  jq ✗        │  │
│  │                  (27 of 30 available)                       │  │
│  │                                                             │  │
│  │  Network         DNS ✓  HTTP ✓                              │  │
│  │                                                             │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── Platform Configuration ──────────────────────────────────┐  │
│  │                                              ⚠ Restart     │  │
│  │                                                required    │  │
│  │  Data Directory    [~/.config/pipelit              ]       │  │
│  │  Database URL      [sqlite:///~/.config/pipelit/db ]       │  │
│  │  Redis URL         [redis://localhost:6379/0       ]       │  │
│  │  Platform URL      [http://localhost:8000          ]       │  │
│  │  CORS Allow All    [ toggle on ]                           │  │
│  │                                                             │  │
│  │  Sandbox Mode      [auto ▾]                                │  │
│  │                                                             │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── Logging ─────────────────────────────────────────────────┐  │
│  │  Log Level         [INFO ▾]                                │  │
│  │  Log File          [                               ]       │  │
│  │                    (empty = console only)                  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌── Advanced ────────────────────────────────────────────────┐  │
│  │  Zombie Threshold  [900         ] seconds                  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│                                              [ Save Changes ]    │
└──────────────────────────────────────────────────────────────────┘
```

**Restart banner:** An `Alert` with `variant="warning"` appears at the top of the "Platform Configuration" card when any restart-required field is modified. Shown after save, not during editing.

**Components used:** Existing `Card` pattern with multiple sections, `Select` for dropdowns (sandbox mode, log level), `Input` for text fields, `Switch` for boolean toggles, `Badge` for status indicators, `Alert` for restart warning.

### 12.4 Node Details Panel — Workspace Dropdown

In `NodeDetailsPanel.tsx`, for `deep_agent`, `code`, and future sandboxed node types, the freeform `filesystem_root_dir` text field is replaced with a workspace dropdown.

```
┌── Node Config ─────────────────────┐
│                                    │
│  Label         [deep_agent_a1b2]   │
│  System Prompt [Edit ↗]            │
│                                    │
│  Workspace     [default         ▾] │
│                ┌────────────────┐  │
│                │ default        │  │
│                │ data-pipeline  │  │
│                │ research       │  │
│                └────────────────┘  │
│                                    │
│  Conversation Memory  [ toggle ]   │
│  ...                               │
└────────────────────────────────────┘
```

Uses the standard `<Select>` pattern. Workspace list fetched via a `useWorkspaces()` TanStack Query hook. Saves as `extra_config.workspace_id` (integer).

### 12.5 Sidebar Navigation Update

Add "Workspaces" to the nav items in `AppLayout.tsx`:

```
  Workflows       (existing)
  Credentials     (existing)
  Executions      (existing)
  Workspaces      ← NEW (HardDrive icon)
  Epics           (existing)
  Memories        (existing)
  Agent Users     (existing)
```

Positioned after Executions since workspaces are infrastructure-level, similar to credentials.

### 12.6 Routes Update

Add to `App.tsx`:

```
/setup          → SetupWizardPage (replaces current SetupPage)
/workspaces     → WorkspacesPage (new, protected)
/settings       → SettingsPage (expanded)
```

---

## 13. Implementation Order

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

---

## 13. Testing Plan

Testing follows existing project patterns: in-memory SQLite for DB tests, `SimpleNamespace` mocks for component factories, `@patch` for external services, `@pytest.mark.skipif` for bwrap-dependent tests. Target: 92% coverage on all new code (matching `codecov.yml`).

### Phase 1: Config Foundation — `test_config.py`

**`TestConfJsonLoader`**
- `test_load_conf_json_defaults` — no `conf.json` exists → Settings uses built-in defaults
- `test_load_conf_json_overrides` — write a `conf.json` to `tmp_path`, verify Settings picks up values (`sandbox_mode`, `database_url`, `redis_url`, etc.)
- `test_env_var_overrides_conf_json` — set env var + `conf.json` → env var wins
- `test_conf_json_missing_keys_uses_defaults` — partial `conf.json` (only `sandbox_mode`) → other fields use defaults
- `test_conf_json_invalid_json_raises` — malformed JSON → clear error, not silent fallback
- `test_settings_load_order` — verify: `conf.json` < `.env` < env vars

**`TestSecretAutoGeneration`**
- `test_auto_generate_encryption_key` — start with no `FIELD_ENCRYPTION_KEY` → server startup generates and writes to `.env`
- `test_auto_generate_secret_key` — same for `SECRET_KEY`
- `test_existing_key_not_overwritten` — `.env` already has a key → startup doesn't regenerate
- `test_generated_key_is_valid_fernet` — auto-generated key can encrypt/decrypt roundtrip

**`TestRemovedConfig`**
- `test_allowed_hosts_removed` — `Settings` no longer has `ALLOWED_HOSTS` attribute
- `test_workspace_dir_removed` — `Settings` no longer has `WORKSPACE_DIR`
- `test_skills_dir_removed` — `Settings` no longer has `SKILLS_DIR`

### Phase 2: Environment Detection & Sandbox — `test_sandboxed_backend.py` (extend existing)

**`TestContainerDetection`**
- `test_detect_dockerenv` — mock `os.path.exists("/.dockerenv")` → returns `"docker"`
- `test_detect_codespaces` — mock `CODESPACES=true` env var → returns `"codespaces"`
- `test_detect_gitpod` — mock `GITPOD_WORKSPACE_ID` env var → returns `"gitpod"`
- `test_detect_cgroup_docker` — mock `/proc/1/cgroup` with `docker` content → returns `"container"`
- `test_detect_cgroup_kubepods` — mock `/proc/1/cgroup` with `kubepods` → returns `"container"`
- `test_detect_podman` — mock `/run/.containerenv` exists → returns `"podman"`
- `test_detect_none_bare_metal` — nothing present → returns `None`
- `test_detection_order_priority` — both `/.dockerenv` and `CODESPACES` set → returns `"docker"` (first check wins)

**`TestSandboxResolution`**
- `test_auto_mode_with_bwrap` → `SandboxResolution(mode="bwrap", can_execute=True)`
- `test_auto_mode_container_no_bwrap` → `SandboxResolution(mode="container", can_execute=True)`
- `test_auto_mode_nothing_available` → `SandboxResolution(mode="none", can_execute=False)`
- `test_bwrap_mode_with_bwrap` → `SandboxResolution(mode="bwrap", can_execute=True)`
- `test_bwrap_mode_missing_bwrap` → `can_execute=False`, reason contains "not installed"
- `test_container_mode_in_container` → `SandboxResolution(mode="container", can_execute=True)`
- `test_container_mode_not_in_container` → `can_execute=False`, reason contains "not detected"

**`TestClearenvSecurity`** (skipif no bwrap)
- `test_clearenv_no_inherited_env` — set `SECRET_TEST_VAR=leaked` in host env, execute `echo $SECRET_TEST_VAR` in sandbox → empty output
- `test_clearenv_explicit_vars_set` — execute `echo $HOME:$PATH:$TMPDIR` → verify `/`, venv path, `/tmp`
- `test_field_encryption_key_not_leaked` — set `FIELD_ENCRYPTION_KEY` in host, verify not visible inside sandbox
- `test_database_url_not_leaked` — same for `DATABASE_URL`

**`TestContainerModeEnvScrubbing`**
- `test_build_sandbox_env_clean` — verify `_build_sandbox_env()` returns only `PATH`, `HOME`, `TMPDIR`, `LANG`
- `test_build_sandbox_env_no_secrets` — verify none of `FIELD_ENCRYPTION_KEY`, `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL` present

**`TestStartupRevalidation`**
- `test_revalidation_bwrap_still_present` — stored bwrap_available=True, bwrap still exists → no warnings
- `test_revalidation_bwrap_disappeared` — stored bwrap_available=True, bwrap gone → warning logged
- `test_revalidation_container_disappeared` — stored container="docker", no longer in container → warning logged
- `test_revalidation_updates_stored_state` — after re-validation, `detected_environment` in conf.json reflects current state

### Phase 2 (cont): Capability Detection — `test_capabilities.py`

**`TestDetectRuntimes`**
- `test_python3_available` — mock `shutil.which("python3")` + version subprocess → `{"available": True, "version": "..."}`
- `test_node_not_available` — mock `shutil.which("node")` returns None → `{"available": False}`
- `test_version_timeout` — mock subprocess timeout → `{"available": True, "version": "unknown"}`
- `test_all_runtimes_checked` — verify all expected keys present (python3, python, node, npm, pip3, pip, ruby, go, java, cargo)

**`TestDetectShellTools`**
- `test_common_tools_detected` — mock several tools present → all show `available: True`
- `test_missing_tool` — mock `shutil.which` returns None for `jq` → `{"available": False}`
- `test_busybox_detection` — mock symlink target contains "busybox" → `{"busybox": True}`

**`TestDetectNetwork`**
- `test_dns_available` — mock nslookup success → `{"dns": True}`
- `test_dns_unavailable` — mock nslookup timeout → `{"dns": False}`
- `test_http_available` — mock curl returns 200 → `{"http": True}`
- `test_http_blocked` — mock curl timeout → `{"http": False}`
- `test_curl_not_installed` — mock FileNotFoundError → `{"http": False}`

**`TestDetectFilesystem`**
- `test_workspace_writable` — real `tmp_path` → readable and writable
- `test_tmp_writable` — `/tmp` check (always True in CI)

**`TestCapabilitiesCache`**
- `test_cached_at_startup` — call `detect_capabilities()` twice → subprocess only spawned once (cached)
- `test_re_check_refreshes_cache` — explicit re-check call → subprocess spawned again

### Phase 3: Setup Wizard — `test_setup_wizard.py`

**`TestSetupStatusAPI`** (uses `TestClient` + `dependency_overrides`)
- `test_setup_status_needs_setup` — no users in DB → `{"needs_setup": true, "environment": {...}}`
- `test_setup_status_already_setup` — user exists → `{"needs_setup": false}`
- `test_setup_status_includes_environment` — verify response has `os`, `container`, `bwrap_available`, `capabilities`
- `test_setup_status_unauthenticated` — no bearer token required

**`TestSetupAPI`**
- `test_setup_creates_user_and_config` — POST with username/password/sandbox_mode → user created, `conf.json` written, 201
- `test_setup_writes_conf_json` — verify `conf.json` contents match request params
- `test_setup_creates_default_workspace` — after setup, a "default" workspace exists in DB
- `test_setup_generates_secrets` — `.env` file has `FIELD_ENCRYPTION_KEY` and `SECRET_KEY` after setup
- `test_setup_rejects_second_call` — second POST → 409 Conflict
- `test_setup_with_config_overrides` — pass `redis_url`, `database_url` overrides → reflected in `conf.json`

**`TestEnvironmentGate`** (unit tests for gate logic)
- `test_gate_passes_linux_bwrap` — Linux + bwrap → gate passes
- `test_gate_passes_container` — container detected → gate passes
- `test_gate_blocks_linux_no_bwrap` — Linux + no bwrap + no container → gate blocks with message
- `test_gate_blocks_macos` — macOS + no container → gate blocks with Docker recommendation

### Phase 4: Workspace Management — `test_workspace.py`

**`TestWorkspaceModel`**
- `test_create_workspace` — insert workspace row → verify name, path, allow_network defaults
- `test_unique_name_constraint` — duplicate name → IntegrityError
- `test_venv_path_derived` — workspace.path + "/.venv" (no separate column)

**`TestWorkspaceAPI`** (uses `auth_client` fixture)
- `test_list_workspaces` — GET → `{"items": [...], "total": N}`
- `test_create_workspace` — POST with name → 201, path auto-derived from `pipelit_dir`
- `test_create_workspace_custom_path` — POST with name + path → path used as-is
- `test_create_workspace_duplicate_name` — POST duplicate → 409
- `test_delete_workspace` — DELETE → 204, workspace gone from DB
- `test_delete_default_workspace_blocked` — DELETE "default" → 403 (cannot delete default)
- `test_update_workspace_network_toggle` — PATCH allow_network=True → updated

**`TestWorkspaceNodeIntegration`**
- `test_node_config_workspace_id` — create node with `extra_config.workspace_id` → resolves to correct path at execution
- `test_node_config_invalid_workspace_id` — nonexistent workspace_id → validation error
- `test_default_workspace_used_when_unset` — node without workspace_id → uses "default" workspace

### Phase 5: Code Node Sandboxing — `test_code_sandbox.py`

**`TestCodeExecuteRemoval`**
- `test_code_execute_component_removed` — verify `code_execute` not in component registry
- `test_code_execute_node_type_removed` — verify `code_execute` not in `NODE_TYPE_REGISTRY`

**`TestCodeNodeSubprocess`**
- `test_python_code_runs_in_subprocess` — code node output matches expected result (not in-process exec)
- `test_code_node_cannot_access_server_env` — code that reads `os.environ["FIELD_ENCRYPTION_KEY"]` → fails or empty
- `test_code_node_timeout` — long-running code → timeout error
- `test_code_node_state_access` — code can access `state` and `node_outputs` (passed via serialization)
- `test_code_node_error_handling` — code raises exception → error returned, not server crash

**`TestCodeNodeBwrap`** (skipif no bwrap)
- `test_code_runs_inside_bwrap` — verify sandbox boundary (cannot read outside workspace)
- `test_code_writes_persist_in_workspace` — file written by code → exists in workspace dir

**`TestRunCommandSandbox`** (skipif no bwrap)
- `test_run_command_uses_bwrap` — command runs inside sandbox
- `test_run_command_no_host_access` — `cat /etc/shadow` → fails in sandbox
- `test_run_command_workspace_writable` — can create files in workspace

**`TestRunCommandContainerMode`**
- `test_run_command_scrubbed_env` — in container mode, subprocess env doesn't contain secrets

### Phase 6: Settings Page — `test_settings_api.py`

**`TestSettingsReadAPI`**
- `test_get_settings` — GET → returns current `conf.json` values
- `test_get_settings_includes_capabilities` — response includes `detected_environment.capabilities`
- `test_get_settings_requires_auth` — no bearer token → 401

**`TestSettingsWriteAPI`**
- `test_update_log_level` — PATCH `log_level=DEBUG` → conf.json updated, takes effect immediately
- `test_update_database_url` — PATCH `database_url` → conf.json updated, response includes restart warning
- `test_update_sandbox_mode` — PATCH `sandbox_mode=bwrap` → conf.json updated, restart required
- `test_invalid_sandbox_mode_rejected` — PATCH `sandbox_mode=invalid` → 422
- `test_settings_persist_across_restart` — write to conf.json → re-load Settings → values match

### Cross-Cutting: Integration Tests — `test_sandbox_integration.py`

**`TestEndToEndBwrap`** (skipif no bwrap)
- `test_deep_agent_uses_clearenv` — full deep_agent execution with bwrap → no secrets in sandbox env
- `test_workspace_isolation` — two workspaces, agent in workspace A cannot read workspace B
- `test_network_blocked_by_default` — agent tries `curl` → network unreachable
- `test_network_allowed_when_enabled` — workspace with `allow_network=True` → curl succeeds

**`TestEndToEndContainerMode`**
- `test_container_mode_no_bwrap_no_warning` — mock container detected, no bwrap → INFO log (not WARNING)
- `test_container_mode_env_scrubbed` — subprocess doesn't have server secrets

**`TestSetupToExecution`** (full flow)
- `test_fresh_setup_to_agent_run` — setup wizard → create workspace → create workflow with deep_agent → execute → verify sandboxed output

### CI Considerations

- **bwrap tests**: Run on ubuntu-latest (bwrap available by default). Marked `skipif` for local macOS dev.
- **Container detection tests**: All mocked — no real container needed.
- **Capability detection tests**: All mocked — no real network probes in CI.
- **Config file tests**: Use `tmp_path` for `conf.json` and `.env` — no host filesystem side effects.
- **Frontend**: No test runner (existing pattern). Covered by TypeScript build + lint. Setup wizard page verified via API tests + manual QA.
