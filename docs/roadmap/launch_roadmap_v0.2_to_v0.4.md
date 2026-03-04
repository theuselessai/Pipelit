## STATUS SUMMARY

**Overall Completion:** 65% (Q1 2026)

### Recent Progress (Since v0.1.0)
- ✅ Phase 1.1: Telegram handler implemented (PR #106 - document upload support)
- ✅ Phase 1.1: Web search system implemented (PR #107 - GLM provider integration)
- ✅ Phase 1.1: Activity-based timeout watchdog (PR #104)
- ✅ Phase P0: Sandbox, skills, providers documentation (PR #101)
- ✅ Phase P1+P2: Docs-site implementation (PR #103)
- ✅ Phase 1.2: Node cleanup - aggregator removed, human_confirmation wired (planned)
- 🟡 Phase 2.1: Message gateway - Architecture designed (PR #114), moved to v0.3.0
- 🟡 Phase 2.2: Docker artifacts - Moved to v0.3.0 (self-hosted deployment)

### Current Priorities (Revised)
**Phase 1 (v0.2.0) - Complete by March 15:**
1. Wire up human_confirmation in builder - 1-2 days
2. Remove redundant tools and harden egress - 1-2 days
3. Final integration testing and docs - 2-3 days

**Phase 2 (v0.3.0) - Target April-May 2026:**
1. Docker artifacts (Dockerfile, docker-compose.yml) - 2-3 days
2. Message gateway implementation:
   - Fix GLM/MiniMax context windows (5 min)
   - Test configurable_alternatives pattern (4-6 hrs)
   - Build gateway components (1 week)
3. Multi-user & self-hosted hardening - 2-3 weeks

---

# Launch Roadmap: v0.2.0 → v0.4.0

---

## Phase 1: v0.2.0 — Core Security & Stability (Target: Mid-March 2026)

**Goal:** Secure agent execution + reliable platform operations. Release as alpha for trusted users only.

**Scope:** Sandbox hardening, timeouts, health checks, documentation. NO Docker or multi-user yet.

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

## Phase 2: v0.3.0 — Deployment & Multi-Model (Target: Late April 2026)

**Goal:** Self-hosted deployment infrastructure + seamless model switching.

**Scope:** Docker, message gateway, multi-user primitives.

### 2.1 Docker Artifacts 🟡 PLANNED (2-3 days)

Create full Docker deployment stack:
- `Dockerfile` — multi-stage: Node 20 Alpine (frontend) + Python 3.13-slim (backend)
- `docker-compose.yml` — 4 services: Redis, backend, worker, scheduler
- `platform/entrypoint.sh` — Alembic migrations + gunicorn startup
- `.dockerignore` — exclude dev files

**Dependencies:** Phase 1 completion
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

**Dependencies:** Phase 1 completion
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
| **1** | v0.2.0 | Mar 15 | 🟡 95% | Alpha (trusted users) |
| **2** | v0.3.0 | Apr-May | ⏳ Planned | Beta (self-hosted) |
| **3** | v0.4.0 | June | ⏳ Planned | SaaS Ready |

**Critical Path:**
- Complete Phase 1 (Mar 15) → human_confirmation + tool cleanup
- Phase 2.1: Docker (Mar 18-21)
- Phase 2.2: Message gateway (Mar 21 - Apr 4)
- Phase 2.3: Multi-user (Apr 4-25)
- Phase 3: SaaS hardening (May-June)

1. `docker compose up` starts all 4 services, frontend accessible at `:8000`
2. `http_request`, `web_search`, `calculator`, `datetime` tools no longer exist — removed from registry, palette, and type defs
3. `aggregator` removed from frontend and node type registry
4. `human_confirmation` → downstream edge triggers `interrupt_before`; removing the edge clears it
5. `run_command` / `code` without workspace return error, not unsandboxed execution
6. `platform_api` tool `base_url` cannot be overridden by LLM
7. Execution with timeout configured fails gracefully after limit
8. `GET /health` returns service status without auth
9. Existing test suite passes (`python -m pytest tests/ -v`)
