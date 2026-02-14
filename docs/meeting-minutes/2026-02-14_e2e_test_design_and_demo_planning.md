# Meeting Minutes: E2E Test Design & Killer Demo Planning

> **Date:** 2026-02-14
> **Branch:** `claude/killer-demo-self-healing-Szw6Z`
> **Participants:** Developer + Claude Code

---

## 1. Session Overview

This session focused on two main themes: designing a "killer demo" showcasing the platform's self-healing agent capabilities, and planning comprehensive E2E test coverage across all node types. The conversation also touched on Telegram bot polling architecture and legacy code cleanup.

---

## 2. Killer Demo — Self-Healing Agent Concept

### Goal
Build a compelling demonstration showing the platform's autonomous agent capabilities — specifically agents that can detect failures, diagnose issues, and self-heal by modifying their own workflows.

### Key Ideas Discussed
- Agents that monitor their own execution status and respond to failures
- Self-modifying workflows that adapt based on runtime outcomes
- Integration with the existing `spawn_and_await` mechanism for hierarchical task delegation
- Leveraging the Workflow DSL compiler so agents can programmatically create/modify workflows

---

## 3. Telegram Bot Polling Architecture

### Context
Instead of relying on the legacy webhook-based `trigger_telegram` handler, a new polling-based approach was designed using existing platform primitives.

### Proposed Architecture
- **Schedule trigger** → periodic polling (e.g., every 5s)
- **HTTP Request node** → calls Telegram `getUpdates` API
- **Agent node** → processes incoming messages
- **HTTP Request node** → calls Telegram `sendMessage` API

### Benefits
- No webhook infrastructure needed (no public URL, no ngrok)
- Uses only standard node types — fully visual on the canvas
- Demonstrates platform composability as a selling point

### Action Items (Pending)
- [ ] Create Telegram bot polling workflow template
- [ ] Create Email monitor polling workflow template (Gmail/IMAP via HTTP)
- [ ] Verify scheduler + http_request can run polling end-to-end
- [ ] Evaluate removing legacy `trigger_telegram` handler (`handlers/telegram.py`)

---

## 4. E2E Test Design — Minimum Coverage Path

### Core Question
> Can we design a single test path that traverses ALL node types and ALL possible scenarios?

### Conclusion: No — Minimum 3 Workflows Required

Mutually exclusive scenarios at decision points (switch branches, human confirmation accept/reject, loop success/failure) make single-path coverage impossible.

### 12 Executable Node Types Identified

| # | Node | Scenarios |
|---|------|-----------|
| 1 | `identify_user` | found / new |
| 2 | `agent` | success / tool_call / spawn_and_await |
| 3 | `categorizer` | match / unknown |
| 4 | `router` | field / expression |
| 5 | `switch` | match / `__other__` / no match |
| 6 | `loop` | iterate / empty / body_error+continue |
| 7 | `code` | success / runtime error |
| 8 | `filter` | match some / match none |
| 9 | `merge` | append / combine |
| 10 | `wait` | 1 scenario |
| 11 | `human_confirmation` | confirmed / cancelled |
| 12 | `workflow` (sub) | child success / child fail |

### 3 Minimum Coverage Workflows

1. **Workflow 1: "Golden Happy Path"** — All 12 node types, happy-path scenario each, ~8 tool types
2. **Workflow 2: "Failure & Edge Cases"** — Mutually exclusive failure scenarios (errors, empty loops, cancellations, fallback routing)
3. **Workflow 3: "Tool Coverage"** — One agent connected to all 20 tool types

### Coverage Matrix Summary
- Node type coverage: 12/12 across WF1+WF2
- Tool coverage: 20/20 via WF3
- Edge type coverage: all 8 types (direct, conditional, loop_body, loop_return, llm, tool, memory, output_parser)

### Remaining Gaps Identified
- `loop` with `body_error + on_error=continue`
- `filter` with match none
- `merge` with combine mode
- `categorizer` with unknown fallback

### Open Design Decisions
1. **Test workflow creation:** Hardcoded JSON fixtures vs DSL-compiled vs property-based fuzz
2. **LLM mocking:** Need deterministic mock responses for agent/categorizer nodes
3. **Redis/RQ in tests:** Synchronous execution mode vs test worker infrastructure

---

## 5. Documentation Reorganization

At the end of the session, the decision was made to:
- Summarize this conversation as meeting minutes under `docs/meeting-minutes/`
- Reorganize all existing docs into categorized subfolders:
  - `docs/architecture/` — Design specs and architecture documents
  - `docs/dev-plans/` — Development plans and roadmaps
  - `docs/meeting-minutes/` — Conversation summaries
  - `docs/testing/` — Test plans and test results
  - `docs/diagnostics/` — Debugging and root cause analysis
  - `docs/assets/` — Images and diagrams (unchanged)

---

## 6. Artifacts Produced

| Artifact | Status |
|----------|--------|
| `docs/e2e_test_design_discussion.md` | Created → moved to `docs/meeting-minutes/` |
| `docs/meeting-minutes/2026-02-14_e2e_test_design_and_demo_planning.md` | This file |
| Docs folder reorganization | Completed this session |

---

## 7. Next Steps

1. **Killer Demo Implementation** — Build the self-healing workflow demo
2. **Telegram Polling Template** — Create and test the schedule-based polling workflow
3. **E2E Test Suite** — Implement the 3 minimum coverage workflows once design decisions are finalized
4. **Legacy Cleanup** — Evaluate removal of webhook-based trigger_telegram handler
