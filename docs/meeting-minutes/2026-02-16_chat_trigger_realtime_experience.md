# Chat Trigger Real-Time Experience — Phase 1 Design

**Date:** 2026-02-16 (Sunday)
**Participants:** Yao, Claude
**Duration:** Single session
**Status:** Design finalized, ready for implementation

-----

## 1. Problem Statement

When a user sends a message via Chat Trigger, the current ChatPanel shows only a loading spinner until the entire execution completes. There is no visibility into which nodes are running, which tools are being called, or how far along the execution is. This makes the experience feel opaque, especially for multi-step workflows.

-----

## 2. Key Decisions

| Decision | Outcome |
|----------|---------|
| **Real-time granularity** | Push results once per node completion. **No token streaming.** |
| **UI form factor** | Step indicator (collapsible step list), not streaming text |
| **Data source** | Reuse existing `node_status` WebSocket events — no new event types needed |
| **Change scope** | Frontend-only (or near-zero backend changes). Existing `node_status` events already contain all required fields |

-----

## 3. Phase 1 Scope

**One-liner:** ChatPanel subscribes to execution events, renders `node_status` as a step list, and displays the final result on completion.

### In Scope

- ChatPanel listens to `node_status` events and displays real-time node execution states
- Tool invocations shown as indented sub-items under their parent agent node
- Switch routing decisions displayed as `→ route: xxx`; skipped branches marked as `skipped`
- Token usage and duration shown after completion
- Error information displayed on failure (error message + error_code)

### Out of Scope (Phase 2+)

- Token streaming / character-by-character output
- Sub-agent / nested execution display
- Meta Agent
- TUI implementation (GUI first)

-----

## 4. GUI Design Spec

### Core Principle

**Auto-expand during execution, auto-collapse after completion.** Don't interrupt reading flow; let users drill into details when curious.

### Step Panel Behavior

| State | Behavior |
|-------|----------|
| During execution | Step panel auto-expands, nodes append in real time |
| After completion | Auto-collapses to one-line summary: `▶ N steps · Xs · N tok` (click to expand) |

### Node Status Icons

| Icon | Meaning |
|------|---------|
| `⚡` | Running (with spinner animation) |
| `✅` | Success |
| `❌` | Failed |
| `⊘` | Skipped (grayed out) |
| `🔧` | Tool call (indented under parent agent) |

### Information Display Per Node Type

- **Agent / LLM nodes:** duration + token count
- **Tool nodes:** duration only
- **Switch nodes:** routing target `→ target_node`
- **Failed nodes:** error message + error_code

-----

## 5. Mockup Scenarios

Five scenarios were mocked up to validate the design across different workflow topologies:

### Scenario 1 — Simple tool call

**Workflow:** `trigger_chat → agent_1 (datetime tool)`
**Input:** "check local time"

```
▶ 2 steps · 1.3s · 180 tok

✅ trigger_chat
✅ agent_1         1.2s · 180 tok
   🔧 datetime ✓
```

### Scenario 2 — Multi-step with multiple tool calls

**Workflow:** `trigger_chat → agent_1 (web_search ×3) → code_1`
**Input:** "summarize the latest news about SpaceX"

```
▶ 3 steps · 8.5s · 2,340 tok

✅ trigger_chat
✅ agent_1         8.4s · 2,340 tok
   🔧 web_search ✓  2.1s
   🔧 web_search ✓  1.8s
   🔧 web_search ✓  1.5s
✅ code_1           0.1s
```

### Scenario 3 — Branch routing with switch

**Workflow:** `trigger_chat → categorizer_1 → switch_1 → [agent_tech / agent_general]`
**Input:** "how do I fix a segfault in my C program"

```
▶ 4 steps · 3.8s · 890 tok

✅ trigger_chat
✅ categorizer_1   0.6s · 210 tok
   → route: tech
✅ switch_1        → agent_tech
✅ agent_tech      2.9s · 680 tok
⊘  agent_general   skipped
```

### Scenario 4 — Failure state

**Workflow:** `trigger_chat → agent_1 (http_request tool)`
**Input:** "check if example.com API is up"

```
▶ 2 steps · 5.1s ── ⚠ failed

✅ trigger_chat
❌ agent_1          5.1s
   🔧 http_request ❌ timeout
   error: Connection timed out after 5s
```

### Scenario 5 — Long chain with multiple tools

**Workflow:** `trigger_chat → agent_1 (web_search, calculator, datetime) → code_1 → agent_2`
**Input:** "what's the current BTC price in JPY and how much is 0.5 BTC"

```
▶ 4 steps · 6.7s · 1,520 tok

✅ trigger_chat
✅ agent_1         4.2s · 980 tok
   🔧 web_search ✓     1.9s
   🔧 calculator ✓     0.1s
   🔧 datetime ✓       0.1s
✅ code_1          0.3s
✅ agent_2         2.2s · 540 tok
```

-----

## 6. Implementation Path

1. **New ChatPanel step indicator component** — Renders the collapsible step list
2. **State management** — Collect `node_status` events by `execution_id`, build ordered step list
3. **Collapse/expand logic** — Auto-expand during execution, auto-collapse on `execution_completed`
4. **Tool attribution** — Identify which tools belong to which agent via edge relationships or node_id prefix
5. **Backend** — No changes or minimal changes (existing `node_status` events already include `node_id`, `status`, `duration_ms`, `output`, `token_usage`, `error`, `error_code`)

-----

## 7. Open Questions

- [ ] Should `trigger_chat` appear in the step list? (It's a pass-through that completes almost instantly)
- [ ] Should historical messages preserve step data? (Or only live sessions show steps)
- [ ] Token display format: `180 tok` (total) vs `180 in / 50 out` (split)
