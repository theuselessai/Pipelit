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

The 8 original gaps collapse into 4 concrete pieces, three of which are just new tools:

| Gap | What's Needed | Type |
|---|---|---|
| **Workflow discovery** | Tool for agents to search existing workflows by description, tags, or capability — not just `GET /workflows/` listing all | New tool |
| **Workflow creation tool** | Higher-level tool than raw `platform_api` — takes a structured goal/spec and creates nodes + edges in one call | New tool |
| **Spawn-and-await from tool context** | Today `workflow` node is a static graph node. Agents need a tool-callable way to spawn a subworkflow mid-execution and block until it returns results | New tool |
| **Execution feedback / tagging** | After subworkflow completes, tag it with success/failure, cost, duration — so future discovery can rank workflows by reliability and fitness | Enhancement |

---

## What This Means

- No new orchestration layer needed
- No worker pool infrastructure
- No task registry system
- No separate planning engine
- Build on existing workflow primitives + 3-4 new tools
- The "multi-agent delegation" capability emerges from agents composing workflows dynamically

---

## Next Steps

- Design the 4 pieces listed above
- Define tool schemas and component specs
- Plan implementation order and dependencies
