# Launch Roadmap: v0.2.0 → v0.4.0

## Context

The platform is at v0.1.0 — feature-rich but not shippable. Ingress security is solid (bwrap namespace isolation), but egress is wide open (tools run outside sandbox with full worker-process access). There are no Docker artifacts despite deployment docs referencing them. The goal is to ship a self-hosted beta first, then harden for multi-user, then prepare for SaaS.

### Security Architecture Decision

**Core principle:** Any tool that executes agent-controlled commands (shell, HTTP, math eval) must run through `backend.execute()` inside the sandbox. Platform operations (DB, Redis, LLM calls) stay in the worker process.

**Remove (redundant — agents have `run_command`, non-agent workflows have `code` node):**

| Tool | Replaced by |
|------|-------------|
| `http_request` | `code` node with Python snippet / `run_command` + `curl` |
| `web_search` | `code` node calling SearXNG / `run_command` + `curl` |
| `calculator` | `code` node with Python snippet |
| `datetime` | `code` node with Python snippet |

**Harden (remove unsandboxed fallbacks):**

| Tool | Currently does | Fix |
|------|---------------|-----|
| `run_command` | `subprocess.run(shell=True)` fallback when no workspace | Require workspace — return error if none |
| `code` | `subprocess.run(["python3", ...])` fallback when no workspace | Require workspace — return error if none |

**Exceptions (stay in worker) — with justification:**

*LLM invocation (platform calls provider APIs on user's behalf):*
- `agent`, `deep_agent`, `ai_model`, `chat_model`, `categorizer`

*Platform CRUD (structured DB/Redis ops, not agent-controlled execution):*
- Read-only: `system_health`, `whoami`, `workflow_discover`, `memory_read`, `identify_user`
- Read-write: `memory_write`, `create_agent_user`, `get_totp_code`, `workflow_create`, `epic_tools`, `task_tools`, `scheduler_tools`, `subworkflow`
- `platform_api` — intentionally calls own API; lock `base_url` to platform address only

*Pure flow control (no I/O):*
- `trigger_*`, `router`, `switch`, `output_parser`, `filter`, `merge`, `loop`, `wait`, `human_confirmation`, `spawn_and_await`

---

## Phase 1: v0.2.0 — Self-Hosted Beta

**Goal:** `docker compose up` takes someone from zero to running Pipelit. Agent-controlled execution is sandboxed.

### 1.1 Sandbox Egress Control

**Remove 4 redundant tools** — agents already have `run_command` in the sandbox, and non-agent workflows have the `code` node. These convenience wrappers are unnecessary attack surface:

**Files to delete:**
- `platform/components/http_request.py`
- `platform/components/web_search.py`
- `platform/components/calculator.py`
- `platform/components/datetime_tool.py`

**Files to modify:**
- `platform/components/__init__.py` — remove imports for deleted components
- `platform/components/run_command.py` — remove unsandboxed `subprocess.run` fallback; return error if no workspace/backend
- `platform/components/code.py` — remove unsandboxed `subprocess.run` fallback; return error if no workspace/backend
- `platform/components/platform_api.py` — lock `base_url` to platform's own address (one-line hardening)
- `platform/schemas/node_type_defs.py` — remove the 4 deleted node type registrations
- Frontend node type definitions — remove the 4 tool types from palette/types

**Migration note:** Existing workflows using these tools will break. This is a v0.2.0 breaking change — acceptable for a pre-release.

### 1.2 Node Cleanup

**Remove `aggregator`** — registered in `node_type_defs.py` and frontend (icon, palette, type union) but has no backend implementation. Its functionality is covered by `merge` in `data_ops.py`.

**Files to modify:**
- `platform/schemas/node_type_defs.py` — remove `aggregator` registration
- `platform/frontend/src/types/models.ts` — remove from `ComponentType` union
- `platform/frontend/src/features/workflows/components/WorkflowCanvas.tsx` — remove icon mapping
- `platform/frontend/src/features/workflows/components/NodePalette.tsx` — remove from "Other" category

**Wire up `human_confirmation`** — the component code exists but isn't integrated into the builder. When a `human_confirmation` node is connected to a downstream node, the builder should automatically set `interrupt_before` on that downstream node. When the edge is deleted, remove the flag.

Runtime flow:
1. `human_confirmation` runs, outputs prompt + `_route`
2. LangGraph interrupts before the downstream node (`interrupt_before`)
3. Orchestrator sends prompt to user via WebSocket
4. User confirms/cancels → orchestrator resumes with `_resume_input`
5. `human_confirmation` re-runs, reads response, sets `_route: "confirmed"` or `"cancelled"`
6. Conditional routing continues or cancels

**Files to modify:**
- `platform/services/builder.py` — detect `human_confirmation` → downstream edges, set `interrupt_before` on target nodes
- `platform/api/nodes.py` — on edge create/delete involving `human_confirmation`, toggle `interrupt_before` flag on the target node

### 1.3 Docker Artifacts

**Create:**
- `Dockerfile` — multi-stage: Node 20 Alpine builds frontend, Python 3.13-slim runs backend. Install `bubblewrap` in the image.
- `docker-compose.yml` — 4 services: `redis` (Alpine, healthcheck, volume), `backend` (gunicorn + uvicorn workers), `worker` (rq worker-pool), `scheduler` (rq worker --with-scheduler). Two networks: `internal` (Redis-only, no internet) and `external` (outbound access).
- `platform/entrypoint.sh` — runs `alembic upgrade head` then `exec gunicorn`
- `.dockerignore`

**Modify:**
- `platform/requirements.txt` — add `gunicorn>=22.0`
- `platform/config.py` — ensure `DATABASE_URL` default works with Docker mount paths

**bwrap-in-Docker:** Install bwrap in the image, document `--cap-add SYS_ADMIN` on the container. Container provides outer isolation; bwrap provides inner isolation between workspaces. If users skip `SYS_ADMIN`, auto-detection falls back to `container` mode (env scrubbing only).

### 1.4 Execution Timeouts

**Modify:**
- `platform/models/workflow.py` — add `max_execution_seconds` (default 600)
- `platform/services/orchestrator.py` — check elapsed time before dispatching each node; fail with `timeout` error code if exceeded
- Alembic migration for new column

### 1.5 Health Check + Production Hardening

**Modify:**
- `platform/main.py` — add `GET /health` (no auth): `{"status": "ok", "version": "...", "redis": bool, "database": bool}`
- `platform/config.py` — CORS default to `false` when `DEBUG=false`; error on startup if `SECRET_KEY` is default and `DEBUG=false`
- `VERSION` — bump to `0.2.0`

### 1.6 Documentation Update

Update all docs to reflect v0.2.0 changes before release.

**`docs-site/`** (MkDocs Material — public-facing):
- Component reference — remove `http_request`, `web_search`, `calculator`, `datetime`, `aggregator` entries; add `human_confirmation` usage guide
- Deployment guide — update Docker docs to match actual `Dockerfile` and `docker-compose.yml` (currently describes artifacts that don't exist)
- Configuration — document execution timeouts, `GET /health` endpoint, production hardening settings
- Changelog — v0.2.0 release notes (breaking changes: removed tools, sandbox requirement for `run_command`/`code`)

**`docs/`** (internal dev docs):
- Archive completed dev plans to `docs/archive/`
- Update `CLAUDE.md` — reflect removed components, new Docker setup, `human_confirmation` wiring

**`README.md`** — update quickstart to use `docker compose up`

### Phase 1 Summary

| Item | Effort |
|------|--------|
| Sandbox egress control (remove 4 tools, harden 2, lock platform_api) | 1 day |
| Node cleanup (remove aggregator, wire up human_confirmation) | 1 day |
| Docker artifacts (Dockerfile, compose, entrypoint, dockerignore) | 1-2 days |
| Execution timeouts | half day |
| Health check + production config | half day |
| Documentation update (docs-site, docs, README, CLAUDE.md, changelog) | 1 day |
| **Total** | **~5-6 days** |

---

## Phase 2: v0.3.0 — Hardening

**Goal:** Tighten sandbox boundaries and add test coverage.

### 2.1 Workspace Domain Allowlists
- Add `allowed_domains` to Workspace model
- Frontend UI for managing per-workspace domain lists
- `backend.execute()` enforces allowlist via sandbox network config

### 2.2 Frontend Tests
- Vitest + React Testing Library setup
- Auth flows, workflow CRUD, WebSocket manager tests

### 2.3 Documentation Update
- Update docs-site and changelog for v0.3.0
- Document workspace domain allowlists

---

## Phase 3: v0.4.0 — Multi-User Readiness

**Goal:** Address gaps that matter once other people deploy it.

### 3.1 Agent API Key Scoping
- Add `scope` JSON field to `APIKey` model (permission strings like `workflow:read`, `execution:create`)
- Human users default to `["*"]` (backward compatible)
- Agent users get restricted scopes
- `check_permission()` dependency in auth chain

### 3.2 Non-Root UID in bwrap
- Add `--uid 1000 --gid 1000` to `_build_bwrap_command`
- Ensure workspace + rootfs ownership

### 3.3 Rate Limiting
- Redis-based rate limiter on auth, execution creation, chat endpoints

### 3.4 Documentation Update
- Update docs-site and changelog for v0.4.0
- Document API key scoping, rate limits

---

## Verification (Phase 1)

1. `docker compose up` starts all 4 services, frontend accessible at `:8000`
2. `http_request`, `web_search`, `calculator`, `datetime` tools no longer exist — removed from registry, palette, and type defs
3. `aggregator` removed from frontend and node type registry
4. `human_confirmation` → downstream edge triggers `interrupt_before`; removing the edge clears it
5. `run_command` / `code` without workspace return error, not unsandboxed execution
6. `platform_api` tool `base_url` cannot be overridden by LLM
7. Execution with timeout configured fails gracefully after limit
8. `GET /health` returns service status without auth
9. Existing test suite passes (`python -m pytest tests/ -v`)
