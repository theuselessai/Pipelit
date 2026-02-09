# Multi-Agent Delegation Architecture

## Piplit Platform — Design Specification

### Date: 2025-02-09
### Status: Draft — Pre-implementation

---

## 1. Overview

This document specifies the architecture for hierarchical multi-agent task delegation in Piplit. An agent receives a complex goal, decomposes it into tasks, dynamically creates or discovers workflows to execute those tasks, tracks progress through a Jira-like registry, learns from outcomes, and improves over time.

The design builds entirely on Piplit's existing primitives (workflow CRUD, agent nodes, tool sub-components, subworkflow execution) with the addition of a task registry model and 4 new agent tools.

---

## 2. Architecture Summary

```
User message
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  TRIGGER (chat / telegram / webhook)                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  MAIN AGENT                                                 │
│                                                             │
│  Decides:                                                   │
│  ├── Simple question? → respond directly                    │
│  ├── Single tool call? → use tool, respond                  │
│  ├── Multi-step goal? → create epic, decompose into tasks   │
│  └── Familiar goal? → search registry, reuse workflow       │
│                                                             │
│  Tools:                                                     │
│  ├── Core: memory_read, memory_write, http_request          │
│  ├── Registry: epic_create, epic_status, epic_update,       │
│  │            epic_search, task_create, task_list,           │
│  │            task_update, task_cancel                       │
│  ├── Workflow: workflow_create, workflow_discover,           │
│  │            spawn_and_await                                │
│  └── Self: whoami, platform_api                             │
│                                                             │
└──────────────┬──────────────────────────────────────────────┘
               │
               │  For complex tasks:
               │  1. Create epic
               │  2. Decompose into tasks with dependencies
               │  3. For each task: execute inline OR delegate to workflow
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  TASK REGISTRY                                              │
│                                                             │
│  Epic: "Join Moltbook"                                      │
│  ├── Task 1: "Fetch instructions"        ✅ completed       │
│  ├── Task 2: "Register via API"          ✅ completed       │
│  └── Task 3: "Set up webhook"            🔄 running         │
│              └── workflow: moltbook-verify (created)         │
│                                                             │
│  Tracks: status, dependencies, cost, workflow linkage,      │
│          result summaries, retry state                       │
│                                                             │
└──────────────┬──────────────────────────────────────────────┘
               │
               │  Tasks execute via:
               │  a) Inline tool calls (simple tasks)
               │  b) spawn_and_await (complex tasks → subworkflow)
               │  c) workflow_create → spawn_and_await (novel tasks)
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  WORKFLOW EXECUTION (existing Piplit infrastructure)         │
│                                                             │
│  Subworkflows run via LangGraph + RQ                        │
│  Results flow back through orchestrator                     │
│  Cost metrics sync to task registry                         │
│  Completed patterns persist as reusable workflows           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Key Architectural Decisions

### 3.1 Workflows over agents

**Decision:** The unit of delegation is workflows, not agents.

Agents are single nodes. Workflows are composable graphs with triggers, tools, routing, and memory — strictly more expressive. The platform already has full workflow CRUD via API, `platform_api` as an agent tool, and `workflow` node for subworkflow execution. An agent delegating to a workflow subsumes delegating to an agent.

### 3.2 Dynamic subworkflows over JSON plans

**Decision:** Agents create executable workflow graphs, not static JSON task plans.

A JSON plan (subtasks, dependencies, estimates) is dead data that needs a separate system to execute. A dynamically created subworkflow IS the plan AND is immediately executable:
- Nodes = subtasks
- Edges = dependencies
- Fan-out topology = parallel groups

This eliminates the "plan → interpret → execute" pipeline.

### 3.3 Subworkflows as executable procedural memory

**Decision:** Dynamically created subworkflows persist as reusable procedures.

```
Novel task arrives
  → Agent searches existing workflows (epic_search / workflow_discover)
  → No match found
  → Agent creates subworkflow via workflow_create
  → Executes it
  → Success → workflow persists, tagged with goal/description
  → Next similar task → agent finds and reuses or forks it
```

Unlike text-based procedure memory, these are actual runnable graphs — inspectable on the canvas, versionable, shareable between agents.

### 3.4 Two-level task hierarchy (Jira model)

**Decision:** Epics and Tasks only. No subtasks in the registry.

- **Epic** = top-level goal ("Write comprehensive tests for platform auth"). Spans multiple tasks, tracks budget, aggregates cost.
- **Task** = discrete unit of work ("Analyze coverage gaps in auth module"). Maps to one workflow execution (or one inline tool call sequence).
- **Subtask** = nodes within a workflow. Already exist as workflow internals. Not modelled in the registry.

### 3.5 Inline vs. delegate decision

**Decision:** The agent decides per-task whether to execute inline or delegate.

- **Inline**: Simple tasks (single HTTP call, memory lookup, code snippet) — agent does it directly via tools, records result in task registry.
- **Delegate**: Complex tasks requiring multi-step execution, their own agent, or persistent artifacts — agent uses `spawn_and_await` to run a subworkflow.
- **Create + delegate**: Novel complex tasks where no suitable workflow exists — agent uses `workflow_create` then `spawn_and_await`.

No separate planning agent or research agent is required. The main agent handles decomposition. A planning agent only becomes necessary if task decomposition itself is complex enough to warrant delegation (recursive self-application of the pattern).

---

## 4. What Already Exists

| Capability | Status | Implementation |
|---|---|---|
| Triggers (Telegram/Chat/Webhook) | ✅ Full | `trigger_telegram`, `trigger_chat`, `trigger_webhook` |
| Agent with tools | ✅ Full | `agent` node + 12 tool sub-component types |
| Memory read/write | ✅ Full | `memory_read` / `memory_write` tools |
| Workflow inspect / self-modify | ✅ Partial | `whoami` + `platform_api` tools |
| Human confirmation | ✅ Full | `human_confirmation` node |
| Subworkflow execution | ✅ Basic | `workflow` node (child execution) |
| Conditional routing | ✅ Full | `switch` node + per-edge `condition_value` |
| Sequential & DAG execution | ✅ Full | Topology-based ordering, RQ job queue |
| Loop iteration | ✅ Full | `loop` node with body subgraph |
| State flow between nodes | ✅ Full | `node_outputs` + Jinja2 expression resolution |
| Agent API credentials | ✅ Full | `create_agent_user` tool |
| Platform API access | ✅ Full | `platform_api` tool |
| Workflow CRUD via REST | ✅ Full | `/api/v1/workflows/`, `/nodes/`, `/edges/` |

---

## 5. What Needs to Be Built

### 5.1 Summary

| Component | Type | Depends On | Complexity |
|---|---|---|---|
| **Task Registry** (Epic + Task models) | New SQLAlchemy models + API + migration | Nothing | Medium |
| **Registry Agent Tools** | New tool components | Task Registry | Low |
| **`spawn_and_await`** | New tool component | Task Registry | High |
| **`workflow_create`** | New tool component | Nothing | Medium |
| **`workflow_discover`** | New tool component | Nothing | Low |
| **Execution → Task cost sync** | Orchestrator hook | Task Registry | Low |
| **Feedback / tagging** | Enhancement to registry | Task Registry | Low |

### 5.2 Implementation order

```
Phase 1: Task Registry
  ├── Epic + Task SQLAlchemy models
  ├── Alembic migration
  ├── Pydantic schemas
  ├── API endpoints (/epics/, /tasks/)
  └── WebSocket events (task_created, task_updated, epic_updated)

Phase 2: Registry agent tools
  ├── epic_create, epic_status, epic_search
  ├── task_create, task_list, task_update, task_cancel
  └── Register as tool sub-components in NODE_TYPE_REGISTRY

Phase 3: spawn_and_await tool
  ├── Design execution model (blocking vs. orchestrator-mediated)
  ├── Implement tool component
  ├── Integration with task registry (auto-link execution_id)
  └── Post-execution cost sync hook

Phase 4: workflow_create + workflow_discover tools
  ├── workflow_create: structured spec → nodes + edges in one call
  ├── workflow_discover: search workflows by description/tags/capability
  └── Tag-based and port-signature matching

Phase 5: Feedback loop
  ├── Auto-tag completed epics with success/failure metrics
  ├── Sync to procedural memory (memory_write)
  └── Discovery ranking by historical success rate and cost
```

---

## 6. Task Registry — Detailed Design

### 6.1 Design Principles

1. **Epics and Tasks only** — subtasks are workflow internals (nodes), not registry entries
2. **Tasks map 1:1 to workflow executions** — status is largely derived, not duplicated
3. **Agents are first-class consumers** — every field exists because an agent needs it for decision-making
4. **Cost rolls up** — task costs aggregate to epic level automatically
5. **Searchable by intent** — agents find past work by goal description and tags, not just IDs

### 6.2 Epic Model

```python
class Epic(Base):
    __tablename__ = "epics"

    id = Column(String, primary_key=True, default=generate_ulid)

    # ── Identity ──────────────────────────────────────────────
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    tags = Column(JSON, default=list)

    # ── Ownership ─────────────────────────────────────────────
    created_by_node_id = Column(String, nullable=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    # Nullable: set when a human user is known (e.g., telegram trigger),
    # left null when created by agents or in nested delegation chains.
    user_profile_id = Column(Integer, ForeignKey("user_profiles.id"), nullable=True)

    # ── Lifecycle ─────────────────────────────────────────────
    status = Column(String, default="planning")
    # Values: planning | active | paused | completed | failed | cancelled
    priority = Column(Integer, default=2)
    # Values: 1=critical, 2=high, 3=medium, 4=low

    # ── Budget ────────────────────────────────────────────────
    budget_tokens = Column(Integer, nullable=True)
    budget_usd = Column(Float, nullable=True)
    spent_tokens = Column(Integer, default=0)
    spent_usd = Column(Float, default=0.0)
    agent_overhead_tokens = Column(Integer, default=0)
    agent_overhead_usd = Column(Float, default=0.0)

    # ── Progress ──────────────────────────────────────────────
    total_tasks = Column(Integer, default=0)
    completed_tasks = Column(Integer, default=0)
    failed_tasks = Column(Integer, default=0)

    # ── Timestamps ────────────────────────────────────────────
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime, nullable=True)

    # ── Outcome ───────────────────────────────────────────────
    result_summary = Column(Text, nullable=True)

    # ── Relations ─────────────────────────────────────────────
    tasks = relationship("Task", back_populates="epic", order_by="Task.created_at")
```

### 6.3 Task Model

```python
class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_ulid)

    # ── Identity ──────────────────────────────────────────────
    epic_id = Column(String, ForeignKey("epics.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    tags = Column(JSON, default=list)

    # ── Ownership ─────────────────────────────────────────────
    created_by_node_id = Column(String, nullable=True)

    # ── Lifecycle ─────────────────────────────────────────────
    status = Column(String, default="pending")
    # Values: pending | blocked | running | completed | failed | cancelled
    priority = Column(Integer, default=2)

    # ── Workflow linkage ──────────────────────────────────────
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    workflow_slug = Column(String, nullable=True)
    execution_id = Column(String, nullable=True)  # Soft ref, not FK
    workflow_source = Column(String, default="inline")
    # Values: inline | existing | created | template

    # ── Dependencies ──────────────────────────────────────────
    depends_on = Column(JSON, default=list)  # List of task IDs

    # ── Requirements ───────────────────────────────────────────
    # Capabilities needed for the workflow executing this task.
    # Format: {"model": "gpt-4", "tools": ["code", "web_search"], "trigger": "webhook", "memory": true}
    requirements = Column(JSON, default=dict)

    # ── Cost tracking ─────────────────────────────────────────
    estimated_tokens = Column(Integer, nullable=True)
    actual_tokens = Column(Integer, default=0)
    actual_usd = Column(Float, default=0.0)
    llm_calls = Column(Integer, default=0)
    tool_invocations = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)

    # ── Timestamps ────────────────────────────────────────────
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # ── Outcome ───────────────────────────────────────────────
    result_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=2)

    # ── Agent notes ───────────────────────────────────────────
    notes = Column(JSON, default=list)
    # Format: [{"timestamp": "...", "text": "..."}]

    # ── Relations ─────────────────────────────────────────────
    epic = relationship("Epic", back_populates="tasks")
```

### 6.4 Status Lifecycles

**Epic:**
```
planning ──► active ──► completed
                │  ▲
                │  │
                ▼  │
              paused
                │
                ▼
            cancelled

active ──► failed (if unrecoverable)
```

**Task:**
```
pending ──► blocked ──► running ──► completed
               │           │
               │           ▼
               │        failed ──► pending (retry)
               │
               ▼
           cancelled
```

### 6.5 Dependency Resolution

```python
def resolve_task_status(task: Task, all_tasks: dict[str, Task]) -> str:
    if task.status == "cancelled":
        return "cancelled"

    if task.status == "pending" and task.depends_on:
        for dep_id in task.depends_on:
            dep = all_tasks.get(dep_id)
            if not dep:
                continue
            if dep.status == "failed":
                return "blocked"
            if dep.status not in ("completed",):
                return "blocked"

    return task.status
```

### 6.6 Cost Aggregation

```python
def sync_epic_costs(epic: Epic):
    tasks = epic.tasks
    epic.spent_tokens = sum(t.actual_tokens for t in tasks)
    epic.spent_usd = sum(t.actual_usd for t in tasks)
    epic.total_tasks = len(tasks)
    epic.completed_tasks = sum(1 for t in tasks if t.status == "completed")
    epic.failed_tasks = sum(1 for t in tasks if t.status == "failed")

def check_budget(epic: Epic, estimated_tokens: int) -> tuple[bool, str]:
    if epic.budget_tokens and (epic.spent_tokens + estimated_tokens > epic.budget_tokens):
        return False, f"Would exceed token budget"
    return True, "ok"
```

### 6.7 API Endpoints

All under `/api/v1/`, authenticated via Bearer token.

**Epics:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/epics/` | List epics (filter by status, tags, workflow_id) |
| `POST` | `/epics/` | Create epic |
| `GET` | `/epics/{id}/` | Get epic with task summary |
| `PATCH` | `/epics/{id}/` | Update epic |
| `DELETE` | `/epics/{id}/` | Delete epic and child tasks |
| `GET` | `/epics/{id}/tasks/` | List tasks for an epic |
| `POST` | `/epics/search/` | Search by goal description / tags |

**Tasks:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/epics/{id}/tasks/` | Create task under epic |
| `GET` | `/tasks/{id}/` | Get task detail |
| `PATCH` | `/tasks/{id}/` | Update task |
| `DELETE` | `/tasks/{id}/` | Delete task |
| `POST` | `/tasks/{id}/retry/` | Reset failed task for retry |
| `POST` | `/tasks/{id}/cancel/` | Cancel task and execution |
| `GET` | `/tasks/actionable/` | Tasks with dependencies met, ready to run |
| `POST` | `/tasks/search/` | Search by description / tags |

---

## 7. New Agent Tools — Detailed Design

### 7.1 Registry Tools

These are registered as tool sub-components (like `memory_read`, `calculator`, etc.) and connected to agent nodes via tool edges.

#### `epic_create`

```
Input:  { title, description, tags[], budget_tokens?, budget_usd?, priority? }
Output: { epic_id, status: "planning" }
```

#### `epic_status`

```
Input:  { epic_id }
Output: {
    epic_id, title, status, priority,
    progress: { total, completed, running, failed, blocked, pending },
    cost: { spent_tokens, spent_usd, budget_tokens, budget_usd, overhead_tokens },
    tasks: [{ id, title, status, workflow_slug, duration_ms }]
}
```

#### `epic_update`

```
Input:  { epic_id, status?, result_summary?, budget_tokens?, budget_usd?, priority? }
Output: { epic_id, status }
Side effects: If cancelled → cancels all running child tasks
```

#### `epic_search`

```
Input:  { query, tags[]?, status? }
Output: { epics: [{ id, title, tags, status, success_rate, avg_cost_usd }] }
```

Key tool for the "neural link" concept — agent searches past epics to find reusable workflows and proven patterns.

#### `task_create`

```
Input:  { epic_id, title, description, tags[], depends_on[], priority?,
          workflow_slug?, estimated_tokens?,
          requirements?: { model?, tools[]?, trigger?, memory? } }
Output: { task_id, status: "pending"|"blocked" }
```

The `requirements` field declares capabilities needed for the workflow executing this task. Used by `workflow_discover` for gap-analysis matching and by `workflow_create` for resource resolution. See `workflow_dsl_spec.md`.

#### `task_list`

```
Input:  { epic_id?, status?, tags[]? }
Output: { tasks: [{ id, title, status, epic_id, depends_on, cost }] }
```

#### `task_update`

```
Input:  { task_id, status?, notes?, result_summary?, error_message? }
Output: { task_id, status }
```

#### `task_cancel`

```
Input:  { task_id, reason? }
Output: { task_id, status: "cancelled", execution_cancelled: bool }
Side effects: Cancels associated workflow execution if running
```

### 7.2 `workflow_create`

Higher-level tool than raw `platform_api`. Accepts a **YAML-based Workflow DSL** and compiles it to Pipelit API calls (nodes + edges). See `workflow_dsl_spec.md` for the full DSL specification.

**Two modes:**

1. **Create from scratch** — Full DSL with trigger, steps, tools, and model declarations
2. **Fork and patch** (`based_on` + `patches`) — Start from an existing workflow, apply incremental modifications

```
Input: {
    dsl: "name: 'Moltbook Webhook Verification'\ndescription: '...'\ntrigger:\n  type: webhook\nsteps:\n  - id: validate\n    type: code\n    snippet: |\n      return {'token': payload['verify_token']}\n",
    tags: ["webhook", "verification", "moltbook"]  // optional override
}

Output: {
    workflow_id: 42,
    slug: "moltbook-verify",
    node_count: 2,
    edge_count: 1,
    webhook_url: "/api/v1/webhooks/moltbook-verify/",
    mode: "created"  // or "forked" if based_on was used
}
```

**Fork and patch example:**

```
Input: {
    dsl: "based_on: 'moltbook-verify'\nname: 'ServiceX Verification'\npatches:\n  - action: update_prompt\n    step_id: code_1\n    snippet: |\n      return {'token': payload['sx_token']}\n"
}

Output: {
    workflow_id: 43,
    slug: "servicex-verification",
    node_count: 2,
    edge_count: 1,
    mode: "forked",
    based_on: "moltbook-verify"
}
```

**Key DSL features:**
- **Implicit linear flow** — Steps execute in declaration order; no explicit edges needed
- **Capability-based model resolution** — `model: {capability: "gpt-4"}` resolves to concrete credential at compile time
- **`inherit` keyword** — `model: {inherit: true}` copies the parent agent's model/credential
- **Inline tool declarations** — Agent steps declare tools directly; compiler creates tool nodes + edges
- **Patch actions** — `add_step`, `remove_step`, `update_prompt`, `add_tool`, `remove_tool`, `update_config`, etc.

**Design note:** The DSL is ephemeral — it's compiled to the standard node/edge representation at creation time. The workflow stores nodes and edges, not YAML. The DSL is a creation-time convenience, not a persistent format.

### 7.3 `workflow_discover`

Searches existing workflows by description, tags, or **capability requirements** — with gap-analysis scoring for three-tier reuse decisions.

```
Input:  {
    query?: "webhook verification",
    tags[]?: ["webhook"],
    requirements?: { model?: "gpt-4", tools[]?: ["code", "web_search"], trigger?: "webhook", memory?: true }
}

Output: { workflows: [{
    slug: "moltbook-verify",
    name: "Moltbook Webhook Verification",
    description: "...",
    tags: ["webhook", "verification"],

    // Capability inventory
    trigger_types: ["trigger_webhook"],
    tool_types: ["code"],
    model_name: "gpt-4o",
    has_memory: false,

    // Gap analysis (only when requirements provided)
    match_score: 0.85,           // 0.0–1.0, weighted capability match
    has: ["code", "webhook"],    // Requirements satisfied
    missing: ["web_search"],     // Requirements not satisfied
    extra: ["http_request"],     // Capabilities beyond requirements

    // Performance metrics
    execution_count: 12,
    success_rate: 0.92,
    avg_duration_ms: 4500,
    avg_cost_usd: 0.03
}]}
```

**Three-tier reuse decision:**

| Match Score | Action | Description |
|-------------|--------|-------------|
| ≥ 0.95 | **Reuse as-is** | Full match — `spawn_and_await` directly |
| ≥ 0.50 | **Fork + patch** | Partial match — `workflow_create` with `based_on` + `patches` to fill gaps |
| < 0.50 | **Create from scratch** | No match — `workflow_create` with full DSL |

**Gap analysis scoring:**

```
match_score = (matched_requirements / total_requirements) * weight_capability
            + tag_overlap_ratio * weight_tags
            + success_rate * weight_reliability
```

Weights are tunable. Default: capability=0.6, tags=0.2, reliability=0.2.

Goes beyond `GET /workflows/` by:
- Gap-analysis scoring against declared requirements
- Showing exactly what's missing vs. what's available (for fork+patch decisions)
- Aggregating execution metrics (success rate, avg cost, duration)
- Filtering by capability signature (trigger type, tool types, model)

### 7.4 `spawn_and_await`

The critical path tool. Spawns a subworkflow execution and returns results to the calling agent.

```
Input:  {
    task_id: "tk_01JKGHI",           // Links to task registry
    workflow_slug: "moltbook-verify",
    payload: { ... },                  // Passed to child workflow trigger
    timeout_seconds: 300
}
Output: {
    execution_id: "exec_xyz",
    status: "completed",
    final_output: { ... },
    duration_ms: 2340,
    tokens_used: 8500
}
```

**Execution model: Interrupt/resume via LangGraph (non-blocking)**

**Decision:** Use LangGraph's `interrupt()` primitive + the existing `_subworkflow` orchestrator pattern. No RQ workers are blocked.

The platform's existing `workflow` node already implements non-blocking subworkflow execution — the component returns a `_subworkflow` signal, releases the RQ worker, and the orchestrator re-enqueues the node after the child completes. `spawn_and_await` reuses this exact mechanism, but from inside an agent's ReAct loop via LangGraph's `interrupt()`.

**How it works:**

```python
from langgraph.types import interrupt

@tool
def spawn_and_await(task_id: str, workflow_slug: str, payload: dict, timeout_seconds: int = 300):
    """Spawn a subworkflow and wait for results."""
    # interrupt() raises a special exception that:
    # 1. Stops the ReAct loop
    # 2. Saves full agent state (conversation + pending tool call) to checkpointer
    # 3. Returns control to agent_node, which emits _subworkflow signal
    result = interrupt({
        "action": "spawn_workflow",
        "task_id": task_id,
        "workflow_slug": workflow_slug,
        "payload": payload,
        "timeout_seconds": timeout_seconds,
    })
    # When resumed after child completes, interrupt() returns the child's output
    return json.dumps(result)
```

**Execution flow (zero blocked workers):**

```
RQ Job 1: execute_node_job(exec, "main_agent")
  → agent.invoke({"messages": [...]})
  → LLM reasons: "I need to delegate this task"
  → LLM calls spawn_and_await tool
  → Tool calls interrupt() → raises, ReAct loop stops
  → Checkpointer saves: full conversation + pending tool call state
  → agent.invoke() returns with interrupt signal
  → agent_node detects interrupt, returns {"_subworkflow": {"child_execution_id": "..."}}
  → Orchestrator handles _subworkflow (existing pattern): publishes WAITING status
  → RQ worker releases ✅

  ... child workflow executes on other RQ workers ...

RQ Job N: child execution completes
  → _handle_child_completion() injects result into state["_subworkflow_results"]
  → Re-enqueues: execute_node_job(exec, "main_agent")

RQ Job N+1: execute_node_job(exec, "main_agent")  ← re-invocation
  → agent_node detects _subworkflow_results, calls:
    agent.invoke(Command(resume=child_result), config={"thread_id": ...})
  → Checkpointer loads saved state: conversation + pending tool call
  → interrupt() returns child_result to the tool function
  → Tool returns stringified result to LLM
  → LLM continues reasoning: "The subworkflow returned..."
  → Normal completion
  → RQ worker releases ✅
```

This reuses the existing orchestrator infrastructure (`_subworkflow` signal, `_handle_child_completion`, `_subworkflow_results` state injection) with zero new orchestration code. The only new piece is the agent component detecting interrupt signals and translating them to `_subworkflow` returns.

**Checkpointer requirement:** `spawn_and_await` requires a checkpointer on the agent to save/restore mid-tool-call state. See section 7.5 for the dual checkpointer strategy that makes this work regardless of conversation memory settings.

**Timeout enforcement:**

When `spawn_and_await` creates the child execution, it also schedules a delayed RQ job at `now + timeout_seconds`. This watchdog job checks if the child execution is still running — if so, cancels it. On cancellation, the orchestrator resumes the parent agent with a timeout error result (`{"error": "timeout", "timeout_seconds": 300}`). The agent can then decide to retry, skip, or fail the task.

```python
# Scheduled at child creation time:
rq_scheduler.enqueue_in(
    timedelta(seconds=timeout),
    check_spawn_timeout,
    child_execution_id=child_execution_id,
    task_id=task_id,
    parent_execution_id=execution_id,
    parent_node_id=node_id,
)
```

**Sequential spawn_and_await (multiple calls in one agent run):**

An agent may call `spawn_and_await` multiple times in a single execution (e.g., spawn task A, resume, spawn task B, resume). Each interrupt/resume cycle must cleanly hand off state. The critical detail:

```python
# IMPORTANT: Use .pop() not .get() to consume the result.
# Without this, a stale result from cycle N would be visible
# in cycle N+1's initial invocation, causing the agent to
# resume with the wrong child's output.
#
# Flow for sequential spawns:
#   Cycle 1: orchestrator sets _subworkflow_results[node_id] = child_A_result
#            → agent_node .pop()s it, resumes agent with child_A_result
#            → key is now absent
#   Cycle 2: agent calls spawn_and_await again → interrupt → _subworkflow signal
#            → orchestrator sets _subworkflow_results[node_id] = child_B_result
#            → agent_node .pop()s it, resumes agent with child_B_result
child_result = state.get("_subworkflow_results", {}).pop(node_id, None)
```

**Side effects:**
- Sets `task.execution_id` and `task.status = "running"`
- Schedules timeout watchdog RQ job
- On completion: calls `sync_task_from_execution` to update cost metrics
- On failure: increments `task.retry_count`, sets status appropriately

### 7.5 Dual Checkpointer Strategy

**Problem:** `spawn_and_await` requires a LangGraph checkpointer to save agent state during interrupt/resume. Currently, checkpointing is only enabled when `conversation_memory=True`. An agent that needs task delegation but not conversation memory would be unable to use `spawn_and_await`.

**Solution:** Two checkpointer backends, selected by agent configuration:

| Scenario | Checkpointer | Storage | Thread ID | Lifecycle |
|---|---|---|---|---|
| `conversation_memory=ON` | `SqliteSaver` | SQLite (`checkpoints.db`) | `{user_id}:{chat_id}:{workflow_id}` | Permanent — conversation history persists across executions |
| `conversation_memory=OFF` + has `spawn_and_await` tool | Redis checkpointer | Redis | `exec:{execution_id}:{node_id}` | Ephemeral — auto-expires with execution state (1h TTL) |
| Neither | None | — | — | One-shot, no checkpointing |

**Why two backends:**

- **SqliteSaver** (existing): Durable conversation history. Agent remembers past chats. Interrupt state is saved as part of the conversation timeline — the pending tool call becomes another checkpoint entry alongside past messages.
- **Redis checkpointer** (new): Throwaway interrupt state. Agent starts fresh each execution, no conversation memory. The checkpoint only exists to bridge the gap between interrupt and resume within a single execution. Auto-expires via Redis TTL — no cleanup logic needed.

**How they coexist:** LangGraph's `create_react_agent` takes one `checkpointer` parameter. The agent factory selects which one based on configuration:

```python
# In agent_factory:
needs_checkpointer = conversation_memory or has_spawn_and_await_tool

if conversation_memory:
    checkpointer = _get_sqlite_checkpointer()    # Durable, permanent
    thread_id = f"{user_id}:{chat_id}:{workflow_id}"
elif has_spawn_and_await_tool:
    checkpointer = _get_redis_checkpointer()      # Ephemeral, auto-expires
    thread_id = f"exec:{execution_id}:{node_id}"
else:
    checkpointer = None
```

**When conversation memory is ON, interrupt state is part of the conversation:**

```
Checkpoint history for thread "user1:chat1:wf1":

  [Human("hello")]                                    ← execution 1
  [Human("hello"), AI("Hi!")]                         ← execution 1
  [..., Human("join moltbook")]                       ← execution 3
  [..., AI(tool_call: http_request)]                  ← step 1
  [..., Tool("instructions...")]                      ← step 2
  [..., AI(tool_call: spawn_and_await)]               ← step 3 (interrupt)
  [..., Tool("child result")]                         ← step 3 (resumed)
  [..., AI("Done. Webhook is live.")]                 ← step 4
```

The interrupt is transparent — it's just another step in the conversation timeline. Future executions see the full history including the delegated task and its result.

**When conversation memory is OFF (Redis ephemeral):**

Same interrupt/resume mechanics, but the checkpoint is scoped to `exec:{execution_id}:{node_id}`. It exists only for the duration of the execution. No cross-execution memory. Redis TTL (matching execution state TTL of 1 hour) handles cleanup automatically.

**Dependency:** `langgraph-checkpoint-redis` package for the Redis checkpointer backend.

---

## 8. Integration Points

### 8.1 Orchestrator → Task cost sync

After a workflow execution completes, a post-execution hook aggregates metrics:

```python
async def sync_task_from_execution(task_id: str, execution: WorkflowExecution):
    task = db.query(Task).get(task_id)
    if not task:
        return

    logs = execution.logs
    task.actual_tokens = sum(log.metadata.get("tokens", 0) for log in logs)
    task.llm_calls = sum(1 for log in logs if log.metadata.get("is_llm_call"))
    task.tool_invocations = sum(1 for log in logs if log.metadata.get("is_tool_call"))
    task.duration_ms = int((execution.completed_at - execution.started_at).total_seconds() * 1000)
    # USD cost computed from credential pricing metadata.
    # LLMProviderCredential stores pricing: {"input_per_1k": 0.01, "output_per_1k": 0.03}
    # set by the admin when configuring credentials.
    task.actual_usd = compute_cost_from_credential(task.actual_tokens, credential_id)

    if execution.status == "completed":
        task.status = "completed"
        task.completed_at = execution.completed_at
    elif execution.status == "failed":
        task.retry_count += 1
        task.status = "failed" if task.retry_count >= task.max_retries else "pending"
        task.error_message = execution.error_message

    sync_epic_costs(task.epic)
    unblock_dependents(task)
```

### 8.2 WebSocket events

New event types on the global WebSocket:

```
Channel: epic:<epic_id>
Events:
  task_created    — { task_id, epic_id, title, status }
  task_updated    — { task_id, status, cost? }
  epic_updated    — { epic_id, status, progress }
```

### 8.3 Feedback loop — discovery ↔ memory bridge

After an epic completes successfully, persist as procedural memory:

```python
memory_write(
    key=f"procedure:{epic.id}",
    value={
        "goal": epic.title,
        "tags": epic.tags,
        "workflow_ids": [t.workflow_id for t in epic.tasks],
        "success_rate": epic.completed_tasks / epic.total_tasks,
        "avg_cost_usd": epic.spent_usd / max(epic.total_tasks, 1),
        "duration_ms": total_duration,
    },
    fact_type="procedure"
)
```

Future agents discover successful patterns via both registry (structured query through `epic_search`) and memory (semantic search through `memory_read`).

---

## 9. Execution Walkthrough — "Join Moltbook"

Concrete trace of the full architecture handling: `"Read https://moltbook.com/skill.md and follow the instructions to join Moltbook"`

### Step 0: Starting state

```
Canvas: [trigger_chat] → [main_agent + tools]
Registry: Empty
```

### Step 1: Trigger fires

`trigger_chat` receives message, outputs `{ text: "Read https://...", payload: {...} }` to main_agent.

### Step 2: Agent creates epic

Agent reasons: multi-step goal → create epic to track it.

```
Tool call: epic_create({
    title: "Join Moltbook",
    description: "Read moltbook.com/skill.md and follow join instructions",
    tags: ["moltbook", "onboarding", "external-service"]
})
→ { epic_id: "ep_01JKXYZ" }
```

**Registry:**
```
ep_01JKXYZ — "Join Moltbook" — planning — 0 tasks
```

### Step 3: Agent fetches URL and creates research task

```
Tool call: task_create({
    epic_id: "ep_01JKXYZ",
    title: "Fetch and analyze Moltbook skill.md",
    tags: ["research", "fetch"]
})
→ { task_id: "tk_01JKABC" }

Tool call: http_request({ url: "https://moltbook.com/skill.md" })
→ Returns instructions: register, submit profile, verify webhook

Tool call: task_update({
    task_id: "tk_01JKABC",
    status: "completed",
    result_summary: "Join requires: 1) register via API, 2) submit profile, 3) verify webhook"
})
```

**Registry:**
```
ep_01JKXYZ — "Join Moltbook" — active — 1/1 completed
  └── tk_01JKABC — "Fetch and analyze skill.md" — ✅ completed — inline
```

### Step 4: Agent decomposes remaining work

```
Tool call: task_create({
    epic_id: "ep_01JKXYZ",
    title: "Register agent with Moltbook API",
    tags: ["registration", "api-call"]
})
→ { task_id: "tk_01JKDEF" }

Tool call: task_create({
    epic_id: "ep_01JKXYZ",
    title: "Set up webhook endpoint for Moltbook verification",
    tags: ["webhook", "verification"],
    depends_on: ["tk_01JKDEF"]
})
→ { task_id: "tk_01JKGHI", status: "blocked" }
```

**Registry:**
```
ep_01JKXYZ — "Join Moltbook" — active — 1/3 completed
  ├── tk_01JKABC — "Fetch and analyze skill.md"      — ✅ completed
  ├── tk_01JKDEF — "Register with Moltbook API"      — ⏳ pending
  └── tk_01JKGHI — "Set up webhook for verification" — 🔒 blocked
```

### Step 5: Agent executes registration (inline)

```
Tool call: task_update({ task_id: "tk_01JKDEF", status: "running" })

Tool call: http_request({
    url: "https://moltbook.com/api/register",
    method: "POST",
    body: { agent_name: "piplit-main", capabilities: [...] }
})
→ { agent_id: "mb_789", webhook_verify_token: "vt_abc123" }

Tool call: task_update({
    task_id: "tk_01JKDEF",
    status: "completed",
    result_summary: "Registered as mb_789. Token: vt_abc123."
})
```

**Registry:**
```
ep_01JKXYZ — "Join Moltbook" — active — 2/3 completed
  ├── tk_01JKABC — "Fetch and analyze skill.md"      — ✅ completed
  ├── tk_01JKDEF — "Register with Moltbook API"      — ✅ completed
  └── tk_01JKGHI — "Set up webhook for verification" — ⏳ pending (unblocked)
```

### Step 6: Agent creates workflow for webhook (dynamic creation)

This task needs a persistent artifact — a webhook endpoint. Agent creates a new workflow.

```
Tool call: task_update({ task_id: "tk_01JKGHI", status: "running" })

Tool call: workflow_create({
    dsl: """
      name: "Moltbook Webhook Verification"
      description: "Receives Moltbook verification ping, responds with token"
      tags: ["webhook", "verification", "moltbook"]
      trigger:
        type: webhook
      steps:
        - id: verify
          type: code
          snippet: |
            import json
            payload = json.loads(input_data)
            return {"token": payload["verify_token"], "status": "ok"}
    """
})
→ { workflow_id: 42, slug: "moltbook-verify", mode: "created" }

Tool call: task_update({
    task_id: "tk_01JKGHI",
    status: "completed",
    workflow_slug: "moltbook-verify",
    workflow_source: "created",
    result_summary: "Created webhook workflow. Endpoint live."
})
```

**Registry:**
```
ep_01JKXYZ — "Join Moltbook" — active — 3/3 completed
  ├── tk_01JKABC — "Fetch and analyze skill.md"      — ✅ completed — inline
  ├── tk_01JKDEF — "Register with Moltbook API"      — ✅ completed — inline
  └── tk_01JKGHI — "Set up webhook for verification" — ✅ completed — workflow: moltbook-verify (created)
```

### Step 7: Agent closes epic

```
Tool call: epic_update({
    epic_id: "ep_01JKXYZ",
    status: "completed",
    result_summary: "Registered with Moltbook as mb_789. Webhook endpoint live."
})
```

Agent responds to user: "Done. Registered with Moltbook and set up a verification webhook."

### What happens next time

Future request: "Set up a webhook for ServiceX verification"

```
Tool call: epic_search({ query: "webhook verification", tags: ["webhook"] })
→ Returns ep_01JKXYZ with workflow "moltbook-verify" — 100% success rate

Tool call: workflow_discover({
    query: "webhook verification",
    requirements: '{"trigger": "webhook", "tools": ["code"]}'
})
→ [{"slug": "moltbook-verify", "match_score": 0.95,
    "has": ["webhook", "code"], "missing": [], "extra": []}]

# High match score — fork and patch instead of creating from scratch:
Tool call: workflow_create({
    dsl: """
      based_on: "moltbook-verify"
      name: "ServiceX Webhook Verification"
      tags: ["webhook", "verification", "servicex"]
      patches:
        - action: update_prompt
          step_id: "code_1"
          snippet: |
            return {"token": payload["sx_token"], "status": "ok"}
    """
})
→ { slug: "servicex-verify", mode: "forked", based_on: "moltbook-verify" }

Reuse instead of reinventing. The fork preserves the proven structure.
```

---

## 10. Node Type Registry Additions

New tool sub-components to register in `schemas/node_type_defs.py`:

```python
# ── Task Registry Tools ───────────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="epic_create",
    display_name="Create Epic",
    description="Create a tracked epic (top-level goal) in the task registry",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="epic_status",
    display_name="Epic Status",
    description="Get progress, cost, and task breakdown for an epic",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="epic_update",
    display_name="Update Epic",
    description="Update an epic's status, budget, or result summary",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="epic_search",
    display_name="Search Epics",
    description="Search past epics by goal description and tags",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="task_create",
    display_name="Create Task",
    description="Create a task under an epic with optional dependencies",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="task_list",
    display_name="List Tasks",
    description="List tasks filtered by epic, status, or tags",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="task_update",
    display_name="Update Task",
    description="Update task status, notes, or result summary",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="task_cancel",
    display_name="Cancel Task",
    description="Cancel a task and its running execution",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

# ── Workflow Management Tools ─────────────────────────────────

register_node_type(NodeTypeSpec(
    component_type="workflow_create_tool",
    display_name="Create Workflow",
    description="Create a new workflow with nodes and edges from a structured spec",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="workflow_discover",
    display_name="Discover Workflows",
    description="Search existing workflows by description, tags, or capability",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))

register_node_type(NodeTypeSpec(
    component_type="spawn_and_await",
    display_name="Spawn & Await",
    description="Execute a subworkflow and wait for results, linked to task registry",
    category="sub_component",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING)],
))
```

---

## 11. Migration

Single Alembic migration. One additive change to an existing model: `Workflow.tags`.

```python
def upgrade():
    op.create_table("epics",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), default=""),
        sa.Column("tags", sa.JSON(), default=[]),
        sa.Column("created_by_node_id", sa.String(), nullable=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id"), nullable=True),
        sa.Column("user_profile_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=True),
        sa.Column("status", sa.String(), default="planning"),
        sa.Column("priority", sa.Integer(), default=2),
        sa.Column("budget_tokens", sa.Integer(), nullable=True),
        sa.Column("budget_usd", sa.Float(), nullable=True),
        sa.Column("spent_tokens", sa.Integer(), default=0),
        sa.Column("spent_usd", sa.Float(), default=0.0),
        sa.Column("agent_overhead_tokens", sa.Integer(), default=0),
        sa.Column("agent_overhead_usd", sa.Float(), default=0.0),
        sa.Column("total_tasks", sa.Integer(), default=0),
        sa.Column("completed_tasks", sa.Integer(), default=0),
        sa.Column("failed_tasks", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
    )
    op.create_table("tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("epic_id", sa.String(), sa.ForeignKey("epics.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), default=""),
        sa.Column("tags", sa.JSON(), default=[]),
        sa.Column("created_by_node_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), default="pending"),
        sa.Column("priority", sa.Integer(), default=2),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id"), nullable=True),
        sa.Column("workflow_slug", sa.String(), nullable=True),
        sa.Column("execution_id", sa.String(), nullable=True),
        sa.Column("workflow_source", sa.String(), default="inline"),
        sa.Column("depends_on", sa.JSON(), default=[]),
        sa.Column("requirements", sa.JSON(), default={}),
        sa.Column("estimated_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_tokens", sa.Integer(), default=0),
        sa.Column("actual_usd", sa.Float(), default=0.0),
        sa.Column("llm_calls", sa.Integer(), default=0),
        sa.Column("tool_invocations", sa.Integer(), default=0),
        sa.Column("duration_ms", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), default=0),
        sa.Column("max_retries", sa.Integer(), default=2),
        sa.Column("notes", sa.JSON(), default=[]),
    )
    op.create_index("ix_epics_status", "epics", ["status"])
    op.create_index("ix_epics_user_profile_id", "epics", ["user_profile_id"])
    op.create_index("ix_tasks_epic_id", "tasks", ["epic_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_workflow_id", "tasks", ["workflow_id"])

    # ── Add tags to existing Workflow model ─────────────────────
    op.add_column("workflows", sa.Column("tags", sa.JSON(), server_default="[]"))

def downgrade():
    op.drop_column("workflows", "tags")
    op.drop_table("tasks")
    op.drop_table("epics")
```

---

## 12. Open Design Questions

1. ~~**`spawn_and_await` execution model**~~ — **RESOLVED.** Non-blocking interrupt/resume via LangGraph's `interrupt()` primitive. Reuses existing `_subworkflow` orchestrator pattern. Dual checkpointer strategy (SqliteSaver for conversation memory, Redis for ephemeral) ensures it works regardless of agent configuration. See sections 7.4 and 7.5.

2. **`execution_id` as FK or soft reference?** — Soft reference (string) is more resilient to execution cleanup. Starting with soft reference.

3. **Epic nesting?** — Current design is flat. Add `parent_epic_id` later if agents decompose epics into sub-epics.

4. ~~**`workflow_create` granularity**~~ — **RESOLVED.** YAML-based Workflow DSL with implicit linear flow, inline tool declarations, capability-based model resolution, and fork+patch mode (`based_on` + `patches`). See `workflow_dsl_spec.md`.

5. ~~**Discovery ranking**~~ — **RESOLVED.** Gap-analysis scoring: `workflow_discover` accepts `requirements` (model, tools, trigger, memory), returns `match_score` + `has`/`missing`/`extra` per result. Three-tier decision: full match (≥0.95) → reuse, partial match (≥0.5) → fork+patch, no match (<0.5) → create from scratch. See section 7.3.

6. ~~**Garbage collection**~~ — **RESOLVED.** Manual management via a Kanban-style task board UI (like Jira). Epics and tasks are exposed in the frontend for users to archive, delete, or reorganize. No automated GC policy needed initially.

7. ~~**Inline task cost tracking**~~ — **RESOLVED.** LangGraph callbacks track per-step token usage. Between `task_update(status="running")` and `task_update(status="completed")`, sum the tokens from callback reports and write to `task.actual_tokens`. The Epic's `agent_overhead_tokens` captures reasoning cost outside any task (decomposition, planning). Three cost categories: delegated task cost (from child execution), inline task cost (from callback delta), agent overhead (everything else).

8. ~~**Epic `user_profile_id` ownership**~~ — **RESOLVED.** Made nullable. Epics created by agents in nested delegation chains don't have a meaningful human owner. Set when a human user is known (e.g., telegram trigger provides user context), left null otherwise. Provenance tracked via `created_by_node_id` + `workflow_id`.

9. ~~**`Workflow.tags` column**~~ — **RESOLVED.** Add `tags = Column(JSON, default=list)` to the existing `Workflow` model in the same migration. Additive change, defaults to `[]` for existing workflows.

10. ~~**`spawn_and_await` timeout enforcement**~~ — **RESOLVED.** RQ scheduled watchdog job at `now + timeout_seconds`. Checks if child execution is still running, cancels it if so, resumes parent agent with timeout error. See section 7.4.

11. ~~**Sequential `spawn_and_await` state cleanup**~~ — **RESOLVED.** `agent_node` uses `.pop()` (not `.get()`) to consume `_subworkflow_results[node_id]` after reading, ensuring stale results from cycle N don't leak into cycle N+1. See section 7.4 code comments.

12. ~~**Token-to-USD cost computation**~~ — **RESOLVED.** Pricing metadata stored on `LLMProviderCredential` as a `pricing` JSON field (e.g., `{"input_per_1k": 0.01, "output_per_1k": 0.03}`). Set by admin when configuring credentials. `compute_cost_from_credential()` reads pricing from the credential used by the execution.

---

## 13. Market Context

No existing multi-agent framework implements this architecture. Closest comparisons:

- **CrewAI**: Has tasks with dependencies and hierarchical delegation, but design-time only. No persistent registry, no epic grouping, no cross-execution visibility, no dynamic workflow creation.
- **LangGraph**: Graph-based execution with checkpointing, but no task abstraction layer. State is per-execution, not across executions.
- **Research (Agent Workflow Memory, ICE, MUSE)**: Describes the concept of consolidating trajectories into reusable procedures, but as text-based memory, not executable graph artifacts.

The combination of: agent-created executable workflow graphs + persistent epic/task registry + cost tracking + discovery-based reuse is novel. The gap between Piplit's current state and this architecture is 4-5 new components built on existing primitives.
