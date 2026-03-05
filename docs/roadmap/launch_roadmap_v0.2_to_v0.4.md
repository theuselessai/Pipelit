## STATUS SUMMARY

**Last Updated:** March 5, 2026
**Overall Completion:** 95% (v0.2.0 Alpha)

### v0.2.0 Alpha Release — March 7, 2026

v0.2.0 is **95% complete** and releasing this weekend (March 7, 2026) as an alpha for trusted users.

**Remaining work (2-4 days):**
1. Wire up `human_confirmation` in builder — 1-2 days
2. Remove unsandboxed fallbacks from `run_command`/`code` — 1-2 days

**Deferred to v0.3.0:**
- Message gateway implementation (architecture designed in PR #114)
- Docker artifacts (Dockerfile, docker-compose.yml)

### Recent Progress (Since v0.1.0)
- ✅ Phase 1.1: Sandbox egress control — redundant tools removed
- ✅ Phase 1.1: Telegram handler implemented (PR #106 — document upload support)
- ✅ Phase 1.1: Web search system implemented (PR #107 — GLM provider integration)
- ✅ Phase 1.1: Activity-based timeout watchdog (PR #104)
- ✅ Phase 1.2: Aggregator node removed
- ✅ Phase 1.3: Execution timeouts — configurable, defaults 5 min
- ✅ Phase 1.4: Health check + production hardening
- ✅ Phase 1.5: Documentation — sandbox, skills, providers, health, tutorial, FAQ (PRs #101, #103)
- ✅ Phase P0+P1+P2: Docs-site implementation (PR #103)
- ✅ Skill directories mounted into bwrap sandbox (PR #116)
- ✅ Telegram trigger matching by bot token + concurrent polling fix (PR #117)
- 🟡 Phase 1.2: `human_confirmation` wiring — planned (1-2 days)
- 🟡 Phase 1.6: Unsandboxed fallback removal — planned (1-2 days)

---

# Launch Roadmap: v0.2.0 → v0.4.0

---

## Phase 1: v0.2.0 — Core Security & Stability (Release: March 7, 2026)

**Goal:** Secure agent execution + reliable platform operations. Release as alpha for trusted users only.

**Scope:** Sandbox hardening, timeouts, health checks, documentation. NO Docker or multi-user yet.

**Status:** 95% complete — releasing March 7

### 1.1 Sandbox Egress Control ✅ DONE

Remove 4 redundant tools (http_request, web_search, calculator, datetime) — agents have `run_command` in sandbox, workflows have `code` node.

**Status:** ✅ Complete

### 1.2 Node Cleanup 🟡 IN PROGRESS

**Remove `aggregator`** ✅ DONE
**Wire up `human_confirmation`** 🟡 PLANNED (1-2 days)
- Auto-set `interrupt_before` on downstream nodes
- Update builder edge handlers

**Status:** 95% (just need human_confirmation wiring)

### 1.3 Execution Timeouts ✅ DONE

Max execution time per agent: configurable, defaults 5 minutes. Activity-based watchdog prevents hung processes.

**Status:** ✅ Complete (PR #104)

### 1.4 Health Check + Hardening ✅ DONE

`/health` endpoint, production config, v0.2.0 version bump.

**Status:** ✅ Complete

### 1.5 Documentation ✅ DONE

Docs-site P0 (sandbox, skills, providers), P1+P2 (health, tutorial, FAQ, cleanup).

**Status:** ✅ Complete (PRs #101, #103)

### 1.6 Remove Unsandboxed Fallbacks 🟡 PLANNED (1-2 days)

Remove subprocess fallbacks from `run_command` and `code` when no workspace exists. Harden platform_api base_url.

**Status:** Ready to implement after human_confirmation wiring

---

## Phase 2: v0.3.0 — Deployment & Multi-Model (Target: April–May 2026)

**Goal:** Self-hosted deployment infrastructure + seamless model switching.

**Scope:** Docker, message gateway, multi-user primitives.

### 2.1 Docker Artifacts 🟡 PLANNED (2-3 days)

Create full Docker deployment stack:
- `Dockerfile` — multi-stage: Node 20 Alpine (frontend) + Python 3.13-slim (backend)
- `docker-compose.yml` — 4 services: Redis, backend, worker, scheduler
- `platform/entrypoint.sh` — Alembic migrations + gunicorn startup
- `.dockerignore` — exclude dev files

**Dependencies:** v0.2.0 release
**Effort:** 2-3 days
**Blockers:** None

### 2.2 Message Gateway 🟡 PLANNED (2-3 weeks)

Enable seamless mid-conversation model switching (Claude ↔ GLM ↔ MiniMax).

**Phase 2.2a: Blockers** (1 day)
- Add GLM/MiniMax to MODEL_CONTEXT_WINDOWS (5 min)
- Prototype + test configurable_alternatives pattern (4-6 hrs)

**Phase 2.2b: Implementation** (2 weeks)
- Build InputAdapters (Telegram, Email, Slack) — ~200 lines
- Build ModelRouter with configurable_alternatives — ~150 lines
- Build PipelitGateway dispatcher — ~250 lines
- Integration tests + docs

**Dependencies:** v0.2.0 release
**Effort:** 2-3 weeks total
**Reference:** PR #114 analysis (80% reusable code exists)

### 2.3 Multi-User Primitives 🟡 PLANNED (2-3 weeks)

Tenant isolation, permission model, audit logging.

**Dependencies:** Docker (2.1) + Gateway (2.2)
**Effort:** 2-3 weeks
**Status:** Designed but not scheduled

---

## Phase 3: v0.4.0 — SaaS Ready (Target: June 2026)

**Goal:** Multi-tenant SaaS deployment with compliance.

**Scope:** Identity federation, rate limiting, billing, compliance audit trail.

**Status:** Pending Phase 2 completion

---

## Summary

| Phase | Version | Target | Status | Completion |
|-------|---------|--------|--------|------------|
| **1** | v0.2.0 | **Mar 7** | 🟡 95% — releasing this weekend | Alpha (trusted users) |
| **2** | v0.3.0 | Apr–May | ⏳ Planned | Beta (self-hosted) |
| **3** | v0.4.0 | June | ⏳ Planned | SaaS Ready |

**Critical Path:**
- ~~Complete Phase 1 (Mar 15) → human_confirmation + tool cleanup~~
- **v0.2.0 Alpha Release (Mar 7)** — human_confirmation + unsandboxed fallback removal
- Phase 2.1: Docker (mid-April)
- Phase 2.2: Message gateway (April–May)
- Phase 2.3: Multi-user (May)
- Phase 3: SaaS hardening (June)

## Acceptance Criteria (v0.2.0)

1. `http_request`, `web_search`, `calculator`, `datetime` tools no longer exist — removed from registry, palette, and type defs
2. `aggregator` removed from frontend and node type registry
3. `human_confirmation` → downstream edge triggers `interrupt_before`; removing the edge clears it
4. `run_command` / `code` without workspace return error, not unsandboxed execution
5. `platform_api` tool `base_url` cannot be overridden by LLM
6. Execution with timeout configured fails gracefully after limit
7. `GET /health` returns service status without auth
8. Existing test suite passes (`python -m pytest tests/ -v`)
