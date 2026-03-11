## STATUS SUMMARY

**Last Updated:** March 11, 2026

### v0.2.0 Alpha — Released March 7, 2026

**Remaining work:**
1. Remove unsandboxed fallbacks from `run_command`/`code` (#124) — in progress

### v0.3.0 Progress

- ✅ Phase 2.2: Message Gateway — msg-gateway integration (PR #135, merged Mar 11 2026)
- 🟡 Phase 2.1: Docker Artifacts — planned
- 🟡 Phase 2.3: Skill to Workflow — planned
- 🟡 Phase 2.4: Human Confirmation — planned
- 🟡 Phase 2.5: Meta Agent — optional

### Recent Progress (Since v0.1.0)
- ✅ Phase 2.2: msg-gateway unified messaging layer (PR #135 — replaces Telegram polling, adds GatewayClient, inbound webhook, credential CRUD)
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
- 🟡 Phase 1.6: Unsandboxed fallback removal — in progress (#124)

---

# Launch Roadmap: v0.2.0 → v0.4.0

---

## Phase 1: v0.2.0 — Core Security & Stability (Release: March 7, 2026)

**Goal:** Secure agent execution + reliable platform operations. Release as alpha for trusted users only.

**Scope:** Sandbox hardening, timeouts, health checks, documentation. NO Docker or multi-user yet.

**Status:** 98% complete — releasing March 7

### 1.1 Sandbox Egress Control ✅ DONE

Remove 4 redundant tools (http_request, web_search, calculator, datetime) — agents have `run_command` in sandbox, workflows have `code` node.

**Status:** ✅ Complete

### 1.2 Node Cleanup ✅ DONE

**Remove `aggregator`** ✅ DONE

**Status:** ✅ Complete

### 1.3 Execution Timeouts ✅ DONE

Max execution time per agent: configurable, defaults 5 minutes. Activity-based watchdog prevents hung processes.

**Status:** ✅ Complete (PR #104)

### 1.4 Health Check + Hardening ✅ DONE

`/health` endpoint, production config, v0.2.0 version bump.

**Status:** ✅ Complete

### 1.5 Documentation ✅ DONE

Docs-site P0 (sandbox, skills, providers), P1+P2 (health, tutorial, FAQ, cleanup).

**Status:** ✅ Complete (PRs #101, #103)

### 1.6 Remove Unsandboxed Fallbacks 🟡 IN PROGRESS

Remove subprocess fallbacks from `run_command` and `code` when no workspace exists. Harden platform_api base_url.

**Status:** In progress (1-2 days)

---

## Phase 2: v0.3.0 — Deployment, Multi-Model & Fidelity (Target: April–May 2026)

**Goal:** Self-hosted deployment infrastructure + seamless model switching + improved agent fidelity.

**Scope:** Docker, message gateway, skill distillation, safety enhancements.

### 2.1 Docker Artifacts 🟡 PLANNED (2-3 days)

Create full Docker deployment stack:
- `Dockerfile` — multi-stage: Node 20 Alpine (frontend) + Python 3.13-slim (backend)
- `docker-compose.yml` — 4 services: Redis, backend, worker, scheduler
- `platform/entrypoint.sh` — Alembic migrations + gunicorn startup
- `.dockerignore` — exclude dev files

**Dependencies:** v0.2.0 release
**Effort:** 2-3 days
**Blockers:** None
**Priority:** P0 (enables self-hosted deployment)

### 2.2 Message Gateway ✅ DONE (PR #135, merged Mar 11 2026)

Replaced the original plan to build in-Pipelit InputAdapters/ModelRouter/PipelitGateway with [msg-gateway](https://github.com/theuselessai/msg-gateway) as the external unified messaging layer.

**What shipped (PR #135):**
- `POST /api/v1/inbound` — webhook endpoint receiving normalized messages from msg-gateway
- `GatewayClient` HTTP client for gateway admin + send APIs
- `GatewayCredential` model replacing `TelegramCredential`
- `verify_gateway_token()` auth dependency
- Gateway credential CRUD UI on frontend
- 3 Alembic migrations + 152 gateway-specific tests
- Removed: Telegram polling, Telegram handler, chat endpoints, ChatPanel UI

**Original plan (superseded):**
- ~~Build InputAdapters (Telegram, Email, Slack)~~ → handled by msg-gateway adapters
- ~~Build ModelRouter with configurable_alternatives~~ → gateway-level routing
- ~~Build PipelitGateway dispatcher~~ → replaced by `GatewayClient`

**Reference:** PR #114 (architecture), PR #135 (implementation)

### 2.3 Skill to Workflow Distillation 🟡 PLANNED (1-2 weeks)

Improve agent fidelity by distilling skills into deterministic workflows.

**Phase 2.3a: skill_to_workflow Tool** (1 week)
- LLM reads skill description → generates YAML DSL
- Call `compile_dsl()` to create workflow
- User can review/edit on canvas

**Phase 2.3b: Basic Workflow Template** (3-5 days)
- Read skill.md
- LLM analyze + generate DSL
- Validate + create workflow
- Optional: human_confirmation before creation

**Dependencies:** None (standalone feature)
**Effort:** 1-2 weeks
**Priority:** P1 (improves fidelity, user control)
**Reference:** Meeting 2026-03-06

### 2.4 Human Confirmation Wiring 🟡 PLANNED (1-2 days)

Wire up `human_confirmation` node for manual approval in workflows.

- Auto-set `interrupt_before` on downstream nodes
- Update builder edge handlers
- Add to node palette

**Dependencies:** None
**Effort:** 1-2 days
**Priority:** P1 (safety enhancement)
**Note:** Deferred from v0.2.0

### 2.5 Meta Agent Reactive Mode 🟡 OPTIONAL (2-3 weeks)

Implement Meta Agent for observing and managing Main Agent behavior.

**Phase 2.5a: Meta Agent Setup** (1 week)
- Deep Agent + platform_api tools
- System prompt: administrator role
- Can query execution logs

**Phase 2.5b: Interactive Commands** (1-2 weeks)
- "Show recent agent behavior"
- "Distill this skill"
- "Add safety check to workflow"

**Dependencies:** skill_to_workflow (2.3)
**Effort:** 2-3 weeks
**Priority:** P2 (nice to have, not blocker)
**Note:** Can run in parallel with other Phase 2 items

### 2.6 Multi-User Primitives 🟡 DEFERRED

Tenant isolation, permission model, audit logging.

**Dependencies:** Docker (2.1) + Gateway (2.2)
**Effort:** 2-3 weeks
**Status:** Deferred to v0.4.0
**Note:** SaaS-ready features, not needed for self-hosted deployment

---

## Phase 3: v0.4.0 — Multi-Tenant & Memory (Target: June–July 2026)

**Goal:** Multi-tenant SaaS deployment + agent memory foundation for self-evolution.

**Scope:** Multi-user infrastructure, memory tables, basic self-awareness.

### 3.1 Multi-User Primitives 🟡 PLANNED (2-3 weeks)

Tenant isolation, permission model, audit logging.

**Components:**
- Tenant isolation (data access control)
- Permission model (role-based access)
- Audit logging (immutable action records)

**Dependencies:** v0.3.0 complete
**Effort:** 2-3 weeks
**Priority:** P0 (SaaS requirement)

### 3.2 Memory Tables 🟡 PLANNED (1 week)

Foundation for Self-Evolving Agent (Phase 1 from self-evolving roadmap).

**Tables:**
- `MemoryEpisode` — Raw execution logs
- `MemoryFact` — Extracted knowledge
- `MemoryProcedure` — Reusable patterns

**Dependencies:** None
**Effort:** 1 week
**Priority:** P1 (enables agent learning)

### 3.3 Memory Read/Write Nodes 🟡 PLANNED (1-2 weeks)

Allow agents to store and retrieve knowledge.

**Nodes:**
- `memory_read` — Key lookup, query search
- `memory_write` — Store facts, update existing

**Dependencies:** Memory Tables (3.2)
**Effort:** 1-2 weeks
**Priority:** P1 (self-evolution foundation)

### 3.4 TOTP Verification Node 🟡 PLANNED (3-5 days)

Time-based OTP verification for critical workflow steps.

**Dependencies:** None
**Effort:** 3-5 days
**Priority:** P2 (safety enhancement)

**Status:** Pending Phase 2 completion

---

## Summary

| Phase | Version | Target | Status | Completion | Focus |
|-------|---------|--------|--------|------------|-------|
| **1** | v0.2.0 | **Mar 7** | 🟡 #124 remaining | Alpha (trusted users) | Security & Stability |
| **2** | v0.3.0 | Apr–May | 🟡 2/5 done (Gateway ✅, rest planned) | Beta (self-hosted) | Deployment, Multi-Model, Fidelity |
| **3** | v0.4.0 | June–July | ⏳ Planned | SaaS Ready | Multi-Tenant & Memory |

**Critical Path:**
- **v0.2.0 Finish** — Unsandboxed fallback removal (#124)
- **Phase 2.2: Message Gateway** ✅ Done (PR #135)
- **Phase 2.1: Docker** (2-3 days)
- **Phase 2.3: Skill to Workflow** (1-2 weeks)
- **Phase 2.4: Human Confirmation** (1-2 days)
- **Phase 2.5: Meta Agent** (optional, 2-3 weeks)
- **Phase 3.1-3.3: Multi-User + Memory** (June–July)

**Key Decisions:**
1. ~~Message Gateway is the highest priority~~ ✅ Done — msg-gateway is the unified messaging layer (PR #135)
2. skill_to_workflow enables gradual fidelity improvement
3. human_confirmation deferred to v0.3.0 (safety enhancement, not blocker)
4. Memory tables moved up to v0.4.0 (foundation for self-evolution)
5. Meta Agent is optional, can run in parallel

## Acceptance Criteria

### v0.2.0 (Alpha)

1. `http_request`, `web_search`, `calculator`, `datetime` tools no longer exist — removed from registry, palette, and type defs
2. `aggregator` removed from frontend and node type registry
3. `run_command` / `code` without workspace return error, not unsandboxed execution
4. `platform_api` tool `base_url` cannot be overridden by LLM
5. Execution with timeout configured fails gracefully after limit
6. `GET /health` returns service status without auth
7. Existing test suite passes (`python -m pytest tests/ -v`)

### v0.3.0 (Beta)

1. Docker deployment works with `docker-compose up`
2. ~~Message Gateway enables mid-conversation model switching without data loss~~ ✅ msg-gateway integration shipped (PR #135)
3. `skill_to_workflow` tool generates valid YAML DSL from skill descriptions
4. `human_confirmation` node can pause execution for manual approval
5. Meta Agent can query execution logs and suggest workflow improvements (optional)

### v0.4.0 (SaaS Ready)

1. Multi-user tenant isolation enforced at database level
2. Memory tables store episodes, facts, and procedures
3. `memory_read` / `memory_write` nodes functional
4. `totp_verification` node available for critical operations

---

## References

- **2026-03-04:** Message Gateway architecture design (PR #114)
- **2026-03-06:** Skill to Workflow & Meta Agent discussion (docs/meeting-minutes/2026-03-06-skill-to-workflow/)
- **2026-03-11:** msg-gateway integration shipped (PR #135) — replaces in-Pipelit messaging, closes #134 and #126
- **Self-Evolving Agent Roadmap:** docs/architecture/self_aware_self_evolving_agent_platform_roadmap.md
