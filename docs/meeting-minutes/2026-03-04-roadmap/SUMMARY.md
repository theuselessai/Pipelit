# Meeting: Pipelit Roadmap Overview (2026-03-04)

**Participants:** Architect, Claude (Deep Agent)
**Duration:** ~1 hour
**Purpose:** Review current status of Pipelit codebase against v0.2.0 → v0.4.0 roadmap

---

## Current Status

### Overall: 65% Phase 1 Complete

The platform has made significant progress in Q1 2026. Phase 1 (v0.2.0 beta) is nearing completion with key integrations and security hardening nearly done. Two critical blockers remain: Docker artifacts and message gateway implementation.

---

## What's Completed ✅

| Item | PR | Status |
|------|----|----|
| **Telegram Handler** | #106 | ✅ Implemented with document upload + metadata |
| **Web Search System** | #107 | ✅ GLM provider integration complete |
| **Activity Timeout** | #104 | ✅ Watchdog implemented (max_execution_seconds) |
| **Documentation** | #101, #103 | ✅ P0 + P1+P2 docs-site built |
| **Message Gateway** | #114 | ✅ Architecture designed and documented |
| **Sandbox Egress** | Ongoing | ✅ 4 redundant tools removed, 2 hardened |
| **Execution Timeouts** | Multiple | ✅ Model + orchestrator + migration + UI |
| **Health Endpoint** | Multiple | ✅ /health check implemented |

---

## What's Blocked 🔴

| Item | Reason | Impact |
|------|--------|--------|
| **Docker Artifacts** | Not created | Can't ship self-hosted beta |
| **Node Cleanup** | Designer needed | human_confirmation not auto-wired in builder |
| **Message Gateway** | GLM/MiniMax missing from context windows | Gateway will break with GLM/MiniMax |
| **Tool Removal** | Migration planning needed | 4 tools (http_request, web_search, calculator, datetime) still in codebase |

---

## Critical Path to v0.2.0

1. **Create Docker artifacts** (Dockerfile, docker-compose.yml, entrypoint.sh)
   - Effort: 2-3 days
   - Blocker for: Self-hosted deployment
   - Dependencies: None

2. **Fix message gateway blockers**
   - Add GLM/MiniMax to context windows: 5 minutes
   - Test configurable_alternatives: 4-6 hours
   - Build gateway components: 1 week
   - Effort: 1-2 weeks total
   - Blocker for: Mid-conversation model switching
   - Dependencies: Context window fix (required before other work)

3. **Remove redundant tools + harden egress**
   - Delete 4 tools, remove imports
   - Harden 2 fallbacks (run_command, code)
   - Lock platform_api base_url
   - Effort: 1-2 days
   - Blocker for: Security hardening
   - Dependencies: Workflow migration guide

4. **Wire human_confirmation in builder**
   - Auto-set interrupt_before on downstream nodes
   - Update edge creation/deletion handlers
   - Effort: 1-2 days
   - Blocker for: Approval workflow patterns
   - Dependencies: None

---

## Timeline Estimate

| Phase | Work | Duration | Target |
|-------|------|----------|--------|
| **Week 1** | Docker + message gateway blockers | 3-4 days | By March 10 |
| **Week 1-2** | Message gateway implementation | 7-10 days | By March 17 |
| **Week 2** | Node cleanup + tool removal | 2-3 days | By March 19 |
| **Week 2** | human_confirmation wiring | 1-2 days | By March 21 |
| **Week 3** | Integration testing + docs | 3-4 days | By March 28 |
| **Final** | v0.2.0 release | — | Early April 2026 |

---

## Key Decisions

**Decision: Proceed with Docker-first approach**
- Self-hosted beta is the launch gate
- Create `docker compose up` workflow first
- Simplifies deployment and testing

**Decision: Fix message gateway GLM/MiniMax blockers immediately**
- 5-minute fix prevents cascading failures
- Must happen before any gateway implementation

**Decision: Keep tool removal as separate phase**
- Don't block Docker on this
- Can be parallel work
- Requires workflow migration guide for users

---

## Architecture Insights

### Message Gateway Status
The gateway design is solid. Per PR #114 analysis:
- 80% of needed code already exists in services/llm.py, context.py, state.py
- 2 critical gaps: GLM/MiniMax missing from context window dictionary
- 1 untested pattern: configurable_alternatives model switching (needs prototype)
- ~600 lines of new code needed (5-phase implementation)

### Telegram Integration
Fully functional with document upload support. Ready for production use in single-user deployments.

### Skill System
Production-ready with 6 core skills:
- dev-workflow-claude (unified dev lifecycle)
- dev-workflow-opencode (OpenCode variant)
- meeting-mode-claude (passive capture + explicit triggers)
- meeting-mode-opencode (OpenCode variant)
- intermediary-delivery (fire-and-forget messaging)
- opencode-configuration (setup)

---

## Action Items

### Immediate (This Week)
- [ ] **Architect:** Create Dockerfile + docker-compose.yml + entrypoint.sh
- [ ] **Architect:** Add GLM/MiniMax to MODEL_CONTEXT_WINDOWS (5 min fix)
- [ ] **Architect:** Test configurable_alternatives pattern (prototype)

### This Sprint (Week 1-2)
- [ ] Build message gateway InputAdapters, ModelRouter, Gateway dispatcher
- [ ] Write workflow migration guide for tool removal
- [ ] Plan human_confirmation builder integration

### Next Sprint (Week 2-3)
- [ ] Remove 4 redundant tools (http_request, web_search, calculator, datetime)
- [ ] Harden run_command + code fallbacks
- [ ] Wire human_confirmation auto-interrupt in builder

### Before v0.2.0 Release
- [ ] Integration tests (Docker + all features)
- [ ] Security audit (sandbox, egress control)
- [ ] User documentation + deployment guide

---

## Notes

- The platform is well-architected for the roadmap
- Q1 progress has been solid (5+ major features)
- Message gateway and Docker are the only blockers to v0.2.0
- Both are technically straightforward with clear implementation plans
- Timeline is realistic: 4-6 weeks to production beta

---

**Next Meeting:** After Docker artifacts created (March 10, 2026)
**Recording:** Captured via intermediary-delivery + meeting-mode-claude skill
