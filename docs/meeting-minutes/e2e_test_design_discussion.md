# E2E Test Design Discussion: Minimum Coverage Path

> Date: 2025-02-14
> Status: Design Discussion

## Background

The platform has grown to significant complexity (~23 registered node types, 20 tool types, multiple edge types, and various execution scenarios). A comprehensive E2E test suite is needed as a safety net.

## Core Question

> Can we design a single test path (shortest path) that traverses ALL node types and ALL possible scenarios on each node?

## Answer: No — Mutually Exclusive Scenarios Prevent Single-Path Coverage

A single execution can only follow **one branch** at each decision point:

- `human_confirmation` → either `confirmed` OR `cancelled`, not both
- `switch` → matches one branch per execution (match A / match B / `__other__`)
- `loop` body → either all succeed OR one fails, not both
- `workflow` (sub) → child either succeeds OR fails

Therefore, one execution path can cover each node type **once** but cannot cover all **scenarios** per node.

## Executable Node Types (12)

| # | Node | Key Scenarios |
|---|------|--------------|
| 1 | `identify_user` | 2 (found / new) |
| 2 | `agent` | 3 (success / tool_call / spawn_and_await) |
| 3 | `categorizer` | 2 (match / unknown) |
| 4 | `router` | 2 (field / expression) |
| 5 | `switch` | 3 (match / `__other__` / no match) |
| 6 | `loop` | 3 (iterate / empty / body_error+continue) |
| 7 | `code` | 2 (success / runtime error) |
| 8 | `filter` | 2 (match some / match none) |
| 9 | `merge` | 2 (append / combine) |
| 10 | `wait` | 1 |
| 11 | `human_confirmation` | 2 (confirmed / cancelled) |
| 12 | `workflow` (sub) | 2 (child success / child fail) |

**Tool nodes (20):** Sub-components invoked by agent — each has success/error scenarios.

**Unimplemented (3):** `extractor`, `aggregator`, `error_handler` — skip for now.

## Proposed Minimum Coverage: 3 Workflows

### Workflow 1: "Golden Happy Path"

Covers all 12 executable node types, one happy-path scenario each, plus ~8 tool types.

```
trigger_chat
  → identify_user (found)
    → agent + [ai_model, calculator, datetime, http_request]
      → code (success)
        → switch (match branch A)
          → filter (match some)
            → merge (append, fan-in with branch B)
        → switch (match branch B) [conditional edge]
          → loop (3 items, body = code → loop_return)
            → merge
              → wait (1s)
                → human_confirmation (confirmed)
                  → workflow (child success)
                    → categorizer + [ai_model, output_parser]
```

### Workflow 2: "Failure & Edge Cases"

Covers mutually exclusive scenarios: failures, empty loops, fallback routing, cancellations.

```
trigger_manual
  → identify_user (new user)
    → code (runtime error → retry → fail)
      ↓ (execution fails here)

trigger_schedule (separate branch, same canvas)
  → loop (empty array → skip body → direct advance)
    → switch (__other__ fallback)
      → human_confirmation (cancelled → _route="cancelled")
        → workflow (child fail → propagate)
```

### Workflow 3: "Tool Coverage"

One agent node connected to all 20 tool types, verifying each tool is callable.

```
trigger_chat
  → agent + [ALL tools: run_command, web_search, code_execute,
             memory_read, memory_write, create_agent_user,
             platform_api, whoami, get_totp_code, epic_tools,
             task_tools, scheduler_tools, system_health,
             spawn_and_await, workflow_create, workflow_discover,
             calculator, datetime, http_request]
```

## Coverage Matrix

```
                    WF1    WF2    WF3    Total
identify_user       found  new    -      2/2
agent               ok     -      tools  2/3
categorizer         match  -      -      1/2
switch              A,B    other  -      3/3
loop                ok     empty  -      2/3
code                ok     error  -      2/2
filter              some   -      -      1/2
merge               append -      -      1/2
wait                ok     -      -      1/1
human_confirmation  yes    no     -      2/2
workflow(sub)       ok     fail   -      2/2
tools               8/20   0/20   20/20  20/20
```

**Remaining gaps** (can be added to WF2):
- `loop` with `body_error + on_error=continue`
- `filter` with match none
- `merge` with combine mode
- `categorizer` with unknown fallback

## Edge Types Covered

| Edge Type | WF1 | WF2 | WF3 |
|-----------|-----|-----|-----|
| `direct` | yes | yes | yes |
| `conditional` | yes (switch) | yes (switch __other__) | - |
| `loop_body` | yes | - | - |
| `loop_return` | yes | - | - |
| `llm` (sub-component) | yes | - | yes |
| `tool` (sub-component) | yes | - | yes |
| `memory` (sub-component) | - | - | yes |
| `output_parser` (sub-component) | yes | - | - |

## Open Design Decisions

1. **Static vs. Dynamic test workflows:**
   - **Option A: Hardcoded JSON fixtures** — Simple, deterministic, easy to debug
   - **Option B: DSL-compiled workflows** — Uses existing `dsl_compiler`, more maintainable
   - **Option C: Property-based fuzz** — Random node combinations for edge cases

2. **LLM mocking strategy:** Agent and categorizer nodes require LLM calls — need consistent mock responses that produce deterministic routing.

3. **Redis/RQ in tests:** Need either synchronous execution mode or test worker infrastructure.

## Node Scenario Detail

### Switch Node Operators (all need coverage eventually)
- Universal: `exists`, `does_not_exist`, `is_empty`, `is_not_empty`
- String: `equals`, `not_equals`, `contains`, `not_contains`, `starts_with`, `ends_with`, `matches_regex`
- Number: `gt`, `lt`, `gte`, `lte`
- Datetime: `after`, `before`
- Boolean: `is_true`, `is_false`
- Array length: `length_eq`, `length_gt`, `length_lt`

### Orchestrator-Level Scenarios
- Node retry (up to 3 retries with exponential backoff)
- Fan-in at merge nodes (wait for all incoming edges)
- Delayed execution via `wait` node (`_delay_seconds`)
- Child workflow spawning and parent resumption
- Interrupt before/after (human_confirmation)
- Loop iteration management (Redis state tracking)
- Budget exceeded → execution failure
- Jinja2 expression resolution in `system_prompt` and `extra_config`
