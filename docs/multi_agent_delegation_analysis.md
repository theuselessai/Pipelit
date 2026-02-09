# Multi-Agent Delegation Architecture — Gap Analysis & Design Direction

## Date: 2025-02-09

## Context

Analysis of what's needed to implement a hierarchical multi-agent task delegation system (Trigger → Main Agent → Planning → Worker Pool → Result Aggregation) purely with the existing node/component system, and the architectural decisions reached.

---

## Proposed Architecture (Original)

```
Trigger → Main Agent → delegate_task() → Planning Agent → Worker Pool → Results → Main Agent (resumed)
```

- **Main Agent**: Has tools for memory, workflow inspection, task delegation, human guidance
- **Planning Agent**: Decomposes goals into subtasks with dependencies, parallel groups, cost estimates
- **Worker Pool**: Parallel agents scoped to specific tools, executing subtasks independently
- **Result Aggregation**: Main agent collects results, handles failures, logs to memory

---

## What Already Exists

| Capability | Status | Implementation |
|---|---|---|
| Triggers (Telegram/Chat/Webhook) | Full | `trigger_telegram`, `trigger_chat`, `trigger_webhook` |
| Agent with tools | Full | `agent` node + 12 tool sub-component types |
| Memory read/write | Full | `memory_read` / `memory_write` tools |
| Workflow inspect / self-modify | Partial | `whoami` + `platform_api` tools |
| Ask human for guidance | Full | `human_confirmation` node |
| Subworkflow execution | Basic | `workflow` node (child execution with parent linkage) |
| Conditional routing | Full | `switch` node + per-edge `condition_value` |
| Sequential & DAG execution | Full | Topology-based ordering, RQ job queue |
| Loop iteration | Full | `loop` node with body subgraph |
| State flow between nodes | Full | `node_outputs` + Jinja2 expression resolution |
| Agent API credentials | Full | `create_agent_user` tool |
| Platform API access | Full | `platform_api` tool (agents can call any endpoint) |

---

## Initial Gap Identification (8 Gaps)

1. **No `delegate_task` tool** — Agents can't dynamically spawn work at runtime; the graph is static at design time
2. **No Planning Agent / dynamic decomposition** — Nothing produces structured plans with subtasks, dependencies, and parallel groups
3. **No Worker Pool / parallel agent spawning** — Parallelism is implicit (DAG fan-out), not dynamically created
4. **No task lifecycle management** — No `task_list`, `task_cancel`, status tracking for delegated work
5. **No result aggregation back to delegator** — No dynamic await-and-collect mechanism
6. **No runtime resource awareness** — No budget tracking, rate limits, cost estimation
7. **No dynamic tool scoping per worker** — Every tool connected to an agent is always available
8. **No execution feedback loop** — No automatic post-execution learning (episodes → procedures)

---

## Key Architectural Insight: Workflows Over Agents

### Decision: The unit of delegation should be workflows, not agents

**Rationale:**

- Agents are single nodes. Workflows are composable graphs with triggers, tools, routing, memory — strictly more expressive.
- The platform already has full workflow CRUD via API, `platform_api` tool, `workflow` node for subworkflow execution, and `create_agent_user` for agent API keys.
- An agent delegating to a workflow subsumes delegating to an agent.

### Decision: Dynamic subworkflows over JSON plans

**Rationale:**

- A JSON plan (subtasks, dependencies, estimates) is dead data that needs a separate system (worker pool, task registry, result collection) to execute.
- A dynamically created subworkflow IS the plan AND is immediately executable:
  - **Nodes** = subtasks
  - **Edges** = dependencies
  - **Fan-out topology** = parallel groups
- Eliminates the entire "plan → interpret → execute" pipeline — the plan and the execution substrate are the same thing.

### Decision: Dynamic subworkflows solve tool scoping for free

- When the main agent builds a subworkflow, it connects only the tools that subtask needs.
- The graph topology IS the permission model. No separate access control system needed.

### Decision: Subworkflows as executable procedural memory ("neural links")

Dynamically created subworkflows become reusable procedures that improve over time:

```
Novel task arrives
  → Agent searches existing workflows (memory / API)
  → No match found
  → Agent creates subworkflow via platform_api
  → Executes it
  → Success → workflow persists, tagged with goal/description
  → Next similar task → agent finds and reuses or forks it

Over time:
  - Library of proven subworkflows grows organically
  - Frequently-used ones get refined (agent patches them)
  - Failed ones get abandoned or fixed
  - Multiple agents across workflows discover and share them
```

Unlike text-based procedure memory, these are actual runnable graphs — inspectable on the canvas, versionable, shareable.

---

## Revised Gap List (Collapsed)

The 8 original gaps collapse into 5 concrete pieces:

| Gap | What's Needed | Type |
|---|---|---|
| **Task registry** | Semantic layer on top of executions that tracks agent intent, delegated task dependencies, links goals to workflows/executions, and declares capability requirements per task. Tasks specify `requirements` (model, tools, trigger, memory) that feed into workflow discovery and creation | New model + tools |
| **Workflow discovery** | Tool for agents to search workflows by requirements with gap-analysis scoring — returns match scores and has/missing/extra breakdowns. Three-tier decision: full match → reuse, partial → fork+patch, none → create from scratch | New tool |
| **Workflow creation tool** | YAML-based Workflow DSL — agents define workflows declaratively (steps, triggers, tools, model) with capability-based resource resolution and fork+patch mode for partial reuse. Compiles to API calls. See `workflow_dsl_spec.md` | New tool |
| **Spawn-and-await from tool context** | Agents need a tool-callable way to spawn a subworkflow mid-execution and get results back. Uses LangGraph's `interrupt()` + existing `_subworkflow` orchestrator pattern — non-blocking, zero RQ workers held. Dual checkpointer strategy: SqliteSaver (durable) when conversation memory is on, Redis checkpointer (ephemeral, auto-expires) when off. | New tool |
| **Execution feedback / tagging** | After subworkflow completes, tag it with success/failure, cost, duration — so future discovery can rank workflows by reliability and fitness | Enhancement |

### Why a Task Registry Is Still Needed

Dynamic subworkflows replace the worker pool and planning engine, but NOT the task registry. Subworkflows are the execution mechanism; the task registry is the **semantic layer** that gives agents awareness of their own delegations.

**Without a task registry, the main agent has amnesia about its delegations:**

| What the agent needs to know | Where it lives today |
|---|---|
| "Why did I spawn this?" (goal/intent) | Nowhere |
| "Which of my subtasks are still running?" | Would need to query executions + remember which are "mine" |
| "Task B depends on Task A finishing" | Nowhere — edge dependencies are within a workflow, not across spawned workflows |
| "What was I working on?" (resume after interruption) | Nowhere — agent loses context between executions |
| "This subtask failed, cancel the others?" | No cancel-by-parent mechanism |
| "Which subworkflow solved goal X last time?" | Nowhere — no link between intent and execution |

**The task registry bridges intent and execution. It tracks:**

- **Goal/description** — why this task exists (semantic, searchable)
- **Associated workflow + execution ID** — what's running it
- **Parent task** — for hierarchical decomposition
- **Dependencies** — what must finish before this task can start
- **Status + result summary** — outcome
- **Cost/duration metrics** — for the feedback loop and budget tracking

**This is also what makes the "neural link" concept work** — without a task registry, agents can create subworkflows but can't find them by purpose later. The registry is the index that connects "I need coverage analysis" to "workflow X solved that last time with 95% success rate."

---

## What This Means

- No new orchestration layer needed
- No worker pool infrastructure
- No separate planning engine
- Build on existing workflow primitives + task registry + new tools
- The "multi-agent delegation" capability emerges from agents composing workflows dynamically
- The task registry provides the semantic memory that makes delegation stateful and resumable

---

## Resolved Design Decisions

1. **`spawn_and_await` execution model** — Non-blocking. Uses LangGraph's `interrupt()` primitive to pause the agent's ReAct loop, reuses the existing `_subworkflow` orchestrator pattern (same as the `workflow` node). Zero RQ workers blocked. The agent node runs twice as two separate RQ jobs with a gap while the child executes.

2. **Dual checkpointer strategy** — `spawn_and_await` requires a checkpointer to save/restore mid-tool-call state. Two backends selected by agent config:
   - `conversation_memory=ON`: `SqliteSaver` (SQLite) — durable, permanent. Interrupt state is part of conversation history.
   - `conversation_memory=OFF` + `spawn_and_await`: Redis checkpointer — ephemeral, auto-expires via Redis TTL (1h). New dependency: `langgraph-checkpoint-redis`.
   - Neither: No checkpointer (unchanged from today).

3. **Workflow DSL** — YAML-based declarative workflow definition language for programmatic creation by agents. Implicit linear flow, inline tool/model declarations, capability-based resource resolution (`inherit`, `capability`). Two modes: create from scratch and fork+patch (`based_on` + `patches`). See `workflow_dsl_spec.md`.

4. **Capability-based resource resolution** — Tasks declare `requirements` (model, tools, trigger, memory) instead of specific credentials. `workflow_discover` scores workflows against requirements (gap analysis with `has`/`missing`/`extra`). `workflow_create` resolves capabilities to concrete credentials via `inherit` (parent's) or `capability` matching (query credentials API).

5. **Three-tier workflow discovery** — `workflow_discover` returns `match_score` per result:
   - Full match (≥0.95) → reuse as-is via `spawn_and_await`
   - Partial match (≥0.5) → fork+patch via `workflow_create` with `based_on` + `patches`
   - No match (<0.5) → create from scratch via `workflow_create` with full DSL

---

## Next Steps

- ~~Design the task registry model (schema, API, agent tools)~~ — see `task_registry_design.md` ✓
- ~~Design the 4 remaining tools (workflow discovery, creation, spawn-and-await, feedback)~~ — see `multiagent_delegation_architecture.md` ✓
- ~~Define tool schemas and component specs~~ — see `tool_schemas_and_component_specs.md` ✓
- ~~Design Workflow DSL for programmatic workflow creation~~ — see `workflow_dsl_spec.md` ✓
- Plan implementation order and dependencies
- Implement Phase 1: Task Registry (models, migration, API, WebSocket events)
