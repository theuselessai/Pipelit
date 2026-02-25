# Plan: Sandbox Mode, Setup Wizard & Platform Configuration

> **Created:** 2026-02-25
> **Updated:** 2026-02-25
> **Status:** Draft
> **Scope:** Environment detection, setup wizard, conf.json, workspace management, code node sandboxing

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

---

## 2. Environment Detection & Sandbox Modes

### 2.1 `SANDBOX_MODE` values

| Value | Behavior | Use case |
|---|---|---|
| `auto` (default) | Use bwrap if available, else detect container, else warn + fallback | Smart default |
| `container` | Skip bwrap, no warning — trust container boundary | Docker / Codespaces / Gitpod |
| `bwrap` | Require bwrap, **error** if missing | Bare metal Linux enforcement |

### 2.2 Container auto-detection (`auto` mode)

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

### 2.3 Behavior matrix

| Environment | bwrap | container | Result |
|---|---|---|---|
| Linux bare metal | yes | no | bwrap sandbox |
| Linux bare metal | no | no | **Blocked at setup wizard** — must install bwrap |
| Docker / k8s | no | yes | container-trusted, no warning |
| macOS bare metal | no | no | **Blocked at setup wizard** — must use Docker |

### 2.4 macOS policy

No `sandbox-exec` implementation. Documentation recommends macOS users run Pipelit in Docker. The setup wizard blocks bare-metal macOS with a clear message.

---

## 3. Setup Wizard

### 3.1 Flow

**Step 1: Environment Check (gate)**
- Auto-detect: OS, bwrap availability, container environment
- **Linux + bwrap** → pass
- **Container detected** → pass (sandbox_mode = container)
- **Linux bare metal + no bwrap** → **blocked**: "bwrap is required. Install with `apt install bubblewrap`" + Re-check button
- **macOS bare metal** → **blocked**: "macOS requires Docker. See setup docs." + link
- Advanced expandable section for overriding: `redis_url`, `database_url`, `log_level`, `platform_base_url`, etc.

**Step 2: Create Admin Account**
- Username + password

**Step 3: Done**
- Auto-generate `FIELD_ENCRYPTION_KEY` + `SECRET_KEY` → append to `.env`
- Write `conf.json` to `{pipelit_dir}/conf.json`
- Create admin user in database
- Mark `setup_completed: true`

### 3.2 Pre-flight (server startup)

Before the wizard UI loads, the server checks:
1. If `FIELD_ENCRYPTION_KEY` is empty → auto-generate Fernet key, append to `.env`, set in `os.environ`
2. This must happen before SQLAlchemy model import since `EncryptedString` reads the env var at module load time

### 3.3 API changes

- `GET /auth/setup-status/` — extended to return `{ needs_setup: bool, environment: { os, container, bwrap_available } }`
- `POST /auth/setup/` — expanded to accept `sandbox_mode`, `pipelit_dir`, and optional config overrides alongside `username`/`password`

---

## 4. Configuration Architecture

### 4.1 `conf.json` — platform runtime config

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
    "bwrap_available": false
  }
}
```

### 4.2 `.env` — secrets only

```
FIELD_ENCRYPTION_KEY=<auto-generated Fernet key>
SECRET_KEY=<auto-generated random string>
```

Both auto-generated by the wizard on first run.

### 4.3 Settings load order

1. `conf.json` (platform config)
2. `.env` (secrets)
3. Environment variables (override everything)

### 4.4 Paths derived from `pipelit_dir`

| Path | Derived as |
|---|---|
| Config file | `{pipelit_dir}/conf.json` |
| Skills directory | `{pipelit_dir}/skills/` |
| Default workspace parent | `{pipelit_dir}/workspaces/` |
| Default database | `{pipelit_dir}/db.sqlite3` |
| Checkpoints DB | per-workspace or `{pipelit_dir}/checkpoints.db` |
| MCP config | `{pipelit_dir}/mcp_config.json` (unify from `~/.config/aichat-platform/`) |

### 4.5 Removed config

- `ALLOWED_HOSTS` — dead config, never used (Django-ism). Delete from Settings.
- `WORKSPACE_DIR` — replaced by per-workspace DB records. Default workspace path derived from `pipelit_dir`.
- `SKILLS_DIR` — derived from `pipelit_dir/skills/`.

---

## 5. Workspace Management

### 5.1 Database model

```python
class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. "default", "data-pipeline"
    path: Mapped[str] = mapped_column(String(500))               # resolved absolute path
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    user_profile_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id"))
```

### 5.2 Workspace page (new sidebar item)

- List registered workspaces (name, path, created date)
- Create workspace — name required, path auto-derived as `{pipelit_dir}/workspaces/{name}` (overridable)
- Delete workspace (with confirmation)
- A "default" workspace is auto-created during setup wizard

### 5.3 Node config integration

- `deep_agent`, `code`, and future sandbox-using nodes get a **workspace dropdown** instead of freeform text
- `extra_config.workspace_id` references the `Workspace.id`
- Workspace path resolved at execution time from the DB record

### 5.4 Future extensions

Workspaces are the unit of isolation that grows over time:
- Filesystem + venv (current)
- Git repo initialization
- GitHub auth (per-workspace `gh` config)
- Per-workspace credentials
- Per-workspace environment variables

---

## 6. Code Node Sandboxing

### 6.1 Current state

- **`code.py`** — in-process `exec()`, zero isolation, category `logic`
- **`code_execute.py`** — subprocess + regex blocklist, category `sub_component` (tool for agents)
- **`run_command.py`** — subprocess `shell=True`, category `sub_component` (tool for agents)

### 6.2 Changes

**Remove `code_execute`** — redundant with `run_command`. The regex blocklist is security theater since `run_command` has no such restrictions. Remove:
- `platform/components/code_execute.py`
- `platform/schemas/node_type_defs.py` — remove `code_execute` registration
- `platform/frontend/` — remove any `code_execute` references in types/palette

**Sandbox the `code` node** — rewrite from in-process `exec()` to subprocess execution:
1. Write code to a temp file in the workspace
2. Run via `subprocess.run()` (like `code_execute` does today)
3. Wrap in bwrap when available (reuse `_build_bwrap_command()`)
4. In container mode, subprocess alone is sufficient

**Sandbox `run_command`** — wrap subprocess calls in bwrap when available, using the workspace assigned to the parent agent node.

---

## 7. Settings Page Expansion

### 7.1 Current state

`/settings` only has theme selection.

### 7.2 New sections

- **Environment** (read-only) — OS, container detection, bwrap status
- **Sandbox mode** — dropdown: auto / container / bwrap
- **Data directory** (`pipelit_dir`)
- **Database URL**
- **Redis URL**
- **Platform base URL**
- **CORS allow all origins**
- **Logging** — level dropdown, file path
- **Zombie threshold**

### 7.3 Hot-reload vs restart

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

## 8. Implementation Order

### Phase 1: Config Foundation
1. Create `conf.json` schema and loader
2. Update `Settings` class to load from `conf.json` → `.env` → env vars
3. Remove `ALLOWED_HOSTS` from Settings
4. Auto-generate `FIELD_ENCRYPTION_KEY` + `SECRET_KEY` on first startup

### Phase 2: Environment Detection & Sandbox Mode
5. Add `_detect_container()` to `sandboxed_backend.py`
6. Add `_resolve_sandbox_mode()` combining config + detection
7. Update `SandboxedShellBackend.__init__()` to use resolved mode
8. Tests for container detection and sandbox mode config

### Phase 3: Setup Wizard
9. Extend `GET /auth/setup-status/` with environment info
10. Extend `POST /auth/setup/` to accept config + write `conf.json`
11. Frontend: setup wizard page (environment gate → admin account → done)

### Phase 4: Workspace Management
12. `Workspace` SQLAlchemy model + Alembic migration
13. Workspace CRUD API endpoints
14. Frontend: Workspaces page (sidebar item)
15. Update node config to use workspace dropdown instead of freeform text
16. Create "default" workspace during setup wizard

### Phase 5: Code Node Sandboxing
17. Remove `code_execute` component, node type registration, and frontend references
18. Rewrite `code.py` to use subprocess execution
19. Wrap `code` and `run_command` subprocess calls in bwrap when available

### Phase 6: Settings Page
20. Expand `/settings` with all `conf.json` fields
21. Implement save → write `conf.json` + hot-reload where possible
22. Restart-required banner for non-hot-reloadable fields
