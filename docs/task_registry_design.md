# Task Registry — Design Specification

## Date: 2025-02-09

## Purpose

A persistent, queryable project management layer for autonomous agent work. Provides agents with Jira-like awareness of their delegations: why work was spawned, what's running, what depends on what, what it cost, and what succeeded or failed. Two levels: **Epics** (top-level goals) and **Tasks** (discrete delegations mapped to workflow executions).

---

## Design Principles

1. **Epics and Tasks only** — subtasks are workflow internals (nodes), not registry entries
2. **Tasks map 1:1 to workflow executions** — status is largely derived, not duplicated
3. **Agents are first-class consumers** — every field exists because an agent needs it for decision-making
4. **Cost rolls up** — task costs aggregate to epic level automatically
5. **Searchable by intent** — agents find past work by goal description and tags, not just IDs

---

## SQLAlchemy Models

### Epic

```python
class Epic(Base):
    __tablename__ = "epics"

    id = Column(String, primary_key=True, default=generate_ulid)  # ep_xxxxxxxxxxxx
    
    # ── Identity ──────────────────────────────────────────────
    title = Column(String, nullable=False)              # "Write comprehensive tests for platform auth"
    description = Column(Text, default="")              # Detailed goal, constraints, acceptance criteria
    tags = Column(JSON, default=list)                   # ["testing", "auth", "coverage"] — for discovery
    
    # ── Ownership ─────────────────────────────────────────────
    created_by_node_id = Column(String, nullable=True)  # Node ID of the agent that created this epic
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)  # Parent workflow context
    # Nullable: set when a human user is known (e.g., telegram trigger),
    # left null when created by agents or in nested delegation chains.
    user_profile_id = Column(Integer, ForeignKey("user_profiles.id"), nullable=True)
    
    # ── Lifecycle ─────────────────────────────────────────────
    status = Column(String, default="planning")         # planning | active | paused | completed | failed | cancelled
    priority = Column(Integer, default=2)               # 1=critical, 2=high, 3=medium, 4=low
    
    # ── Budget ────────────────────────────────────────────────
    budget_tokens = Column(Integer, nullable=True)      # Token ceiling (null = unlimited)
    budget_usd = Column(Float, nullable=True)           # USD ceiling (null = unlimited)
    spent_tokens = Column(Integer, default=0)           # Running total from child tasks
    spent_usd = Column(Float, default=0.0)              # Running total from child tasks
    agent_overhead_tokens = Column(Integer, default=0)  # Main agent's own reasoning cost
    agent_overhead_usd = Column(Float, default=0.0)     # Main agent's own reasoning cost
    
    # ── Progress ──────────────────────────────────────────────
    total_tasks = Column(Integer, default=0)
    completed_tasks = Column(Integer, default=0)
    failed_tasks = Column(Integer, default=0)
    
    # ── Timestamps ────────────────────────────────────────────
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # ── Outcome ───────────────────────────────────────────────
    result_summary = Column(Text, nullable=True)        # Agent-written summary of what was achieved
    
    # ── Relations ─────────────────────────────────────────────
    tasks = relationship("Task", back_populates="epic", order_by="Task.created_at")
```

### Task

```python
class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_ulid)  # tk_xxxxxxxxxxxx
    
    # ── Identity ──────────────────────────────────────────────
    epic_id = Column(String, ForeignKey("epics.id"), nullable=False)
    title = Column(String, nullable=False)              # "Analyze coverage gaps in auth module"
    description = Column(Text, default="")              # What this task should accomplish
    tags = Column(JSON, default=list)                   # ["coverage", "analysis"] — for discovery
    
    # ── Ownership ─────────────────────────────────────────────
    created_by_node_id = Column(String, nullable=True)  # Agent node that spawned this task
    
    # ── Lifecycle ─────────────────────────────────────────────
    status = Column(String, default="pending")          # pending | blocked | running | completed | failed | cancelled
    priority = Column(Integer, default=2)               # Inherited from epic, can be overridden
    
    # ── Workflow linkage ──────────────────────────────────────
    # Which workflow runs this task, and which execution is currently active
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)     # Assigned workflow
    workflow_slug = Column(String, nullable=True)                                 # For convenience
    execution_id = Column(String, nullable=True)                                  # Current execution
    
    # A task may be executed inline or reference a workflow (existing, created, or template)
    workflow_source = Column(String, default="inline") # inline | existing | created | template
    
    # ── Dependencies ──────────────────────────────────────────
    depends_on = Column(JSON, default=list)             # List of task IDs that must complete first

    # ── Requirements ───────────────────────────────────────────
    # Capabilities needed by the workflow that executes this task.
    # Used by workflow_discover for gap-analysis matching and by
    # workflow_create for capability-based resource resolution.
    # Format: {"model": "gpt-4", "tools": ["code", "web_search"], "trigger": "webhook", "memory": true}
    requirements = Column(JSON, default=dict)

    # ── Cost tracking ─────────────────────────────────────────
    estimated_tokens = Column(Integer, nullable=True)   # Agent's prediction before execution
    actual_tokens = Column(Integer, default=0)          # From execution logs (input + output)
    actual_usd = Column(Float, default=0.0)             # Computed from model pricing × tokens
    llm_calls = Column(Integer, default=0)              # Count of individual completions
    tool_invocations = Column(Integer, default=0)       # Count of tool uses
    duration_ms = Column(Integer, default=0)            # Wall clock time
    
    # ── Timestamps ────────────────────────────────────────────
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # ── Outcome ───────────────────────────────────────────────
    result_summary = Column(Text, nullable=True)        # Agent-written: what was the output
    error_message = Column(Text, nullable=True)         # If failed: why
    retry_count = Column(Integer, default=0)            # How many times this was retried
    max_retries = Column(Integer, default=2)            # Auto-retry limit
    
    # ── Agent notes ───────────────────────────────────────────
    # Running log the agent appends to as it works — separate from execution logs
    notes = Column(JSON, default=list)                  # [{"timestamp": "...", "text": "Switched strategy..."}]
    
    # ── Relations ─────────────────────────────────────────────
    epic = relationship("Epic", back_populates="tasks")
```

---

## Status Lifecycle

### Epic

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

- `planning` → Agent is decomposing the goal, tasks not yet created
- `active` → At least one task is running or pending
- `paused` → Agent or human paused work (budget exceeded, waiting for input)
- `completed` → All tasks finished successfully (or acceptably)
- `failed` → Unrecoverable failure, agent gave up
- `cancelled` → Human or agent cancelled

### Task

```
pending ──► blocked ──► running ──► completed
               │           │
               │           ▼
               │        failed ──► pending (retry)
               │
               ▼
           cancelled
```

- `pending` → Created, waiting to be picked up
- `blocked` → Dependencies not yet met (computed from `depends_on`)
- `running` → Workflow execution in progress
- `completed` → Execution succeeded
- `failed` → Execution failed (may auto-retry up to `max_retries`)
- `cancelled` → Cancelled by parent agent (e.g., sibling failed, epic cancelled)

---

## Dependency Resolution

A task's effective status considers its `depends_on` list:

```python
def resolve_task_status(task: Task, all_tasks: dict[str, Task]) -> str:
    """Compute effective status, accounting for dependencies."""
    if task.status == "cancelled":
        return "cancelled"
    
    if task.status == "pending" and task.depends_on:
        for dep_id in task.depends_on:
            dep = all_tasks.get(dep_id)
            if not dep:
                continue
            if dep.status == "failed":
                return "blocked"  # Dependency failed — can't proceed
            if dep.status not in ("completed",):
                return "blocked"  # Dependency not done yet
    
    return task.status
```

When a task completes, the agent (or a post-execution hook) checks: which pending tasks now have all dependencies met? Those transition from `blocked` → `pending` and are eligible for spawn-and-await.

---

## Cost Aggregation

Costs roll up from Task → Epic automatically:

```python
def sync_epic_costs(epic: Epic):
    """Recompute epic cost totals from child tasks."""
    tasks = epic.tasks
    epic.spent_tokens = sum(t.actual_tokens for t in tasks)
    epic.spent_usd = sum(t.actual_usd for t in tasks)
    epic.total_tasks = len(tasks)
    epic.completed_tasks = sum(1 for t in tasks if t.status == "completed")
    epic.failed_tasks = sum(1 for t in tasks if t.status == "failed")
```

Budget check before spawning a new task:

```python
def check_budget(epic: Epic, estimated_tokens: int) -> tuple[bool, str]:
    """Can the epic afford another task?"""
    if epic.budget_tokens and (epic.spent_tokens + estimated_tokens > epic.budget_tokens):
        return False, f"Would exceed token budget ({epic.spent_tokens + estimated_tokens} > {epic.budget_tokens})"
    if epic.budget_usd and (epic.spent_usd + estimate_usd(estimated_tokens) > epic.budget_usd):
        return False, f"Would exceed USD budget"
    return True, "ok"
```

---

## API Endpoints

All under `/api/v1/`, authenticated via Bearer token.

### Epics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/epics/` | List epics (filter by status, tags, workflow_id) |
| `POST` | `/epics/` | Create epic |
| `GET` | `/epics/{id}/` | Get epic with task summary |
| `PATCH` | `/epics/{id}/` | Update epic (status, budget, description) |
| `DELETE` | `/epics/{id}/` | Delete epic and all child tasks |
| `GET` | `/epics/{id}/tasks/` | List tasks for an epic |
| `POST` | `/epics/search/` | Semantic search by goal description / tags |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/epics/{id}/tasks/` | Create task under epic |
| `GET` | `/tasks/{id}/` | Get task detail with execution link |
| `PATCH` | `/tasks/{id}/` | Update task (status, notes, assignment) |
| `DELETE` | `/tasks/{id}/` | Delete task |
| `POST` | `/tasks/{id}/retry/` | Reset failed task for retry |
| `POST` | `/tasks/{id}/cancel/` | Cancel task and its execution |
| `GET` | `/tasks/actionable/` | List tasks with all dependencies met, ready to run |
| `POST` | `/tasks/search/` | Search by description / tags |

---

## Agent Tools

These are the tools agents use to interact with the registry. Each maps to API calls via `platform_api` or could be purpose-built components.

### `epic_create`

```
Input:  { title, description, tags[], budget_tokens?, budget_usd?, priority? }
Output: { epic_id, status: "planning" }
```

### `epic_status`

```
Input:  { epic_id }
Output: { 
    epic_id, title, status, priority,
    progress: { total: 5, completed: 2, running: 1, failed: 0, blocked: 1, pending: 1 },
    cost: { spent_tokens, spent_usd, budget_tokens, budget_usd, overhead_tokens },
    tasks: [{ id, title, status, workflow_slug, duration_ms }]
}
```

### `task_create`

```
Input:  { epic_id, title, description, tags[], depends_on[], priority?,
          workflow_slug?, estimated_tokens?,
          requirements?: { model?, tools[]?, trigger?, memory? } }
Output: { task_id, status: "pending"|"blocked" }
```

The `requirements` field declares capabilities needed for the workflow that executes this task. Used by `workflow_discover` for gap-analysis matching and by `workflow_create` for capability-based resource resolution. See `workflow_dsl_spec.md` for the full resolution pipeline.

### `task_list`

```
Input:  { epic_id?, status?, tags[]? }
Output: { tasks: [{ id, title, status, epic_id, depends_on, cost }] }
```

### `task_update`

```
Input:  { task_id, status?, notes?, result_summary?, error_message? }
Output: { task_id, status }
```

### `task_cancel`

```
Input:  { task_id, reason? }
Output: { task_id, status: "cancelled", execution_cancelled: bool }
Side effects: Cancels associated workflow execution if running
```

### `epic_update`

```
Input:  { epic_id, status?, result_summary?, budget_tokens?, budget_usd?, priority? }
Output: { epic_id, status }
Side effects: If cancelled → cancels all running child tasks
```

### `epic_search`

```
Input:  { query: "coverage analysis for auth", tags[]?, status? }
Output: { epics: [{ id, title, tags, status, completed_tasks, total_tasks,
                     success_rate, avg_cost_usd }] }
```

This is the key tool for the "neural link" concept — agent searches past epics to find reusable workflows.

---

## Pydantic Schemas

### Epic Schemas

```python
class EpicIn(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = []
    priority: int = 2
    budget_tokens: int | None = None
    budget_usd: float | None = None
    workflow_id: int | None = None

class EpicUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    status: Literal["planning", "active", "paused", "completed", "failed", "cancelled"] | None = None
    priority: int | None = None
    budget_tokens: int | None = None
    budget_usd: float | None = None
    result_summary: str | None = None

class EpicProgressOut(BaseModel):
    total: int
    completed: int
    running: int
    failed: int
    blocked: int
    pending: int

class EpicCostOut(BaseModel):
    spent_tokens: int
    spent_usd: float
    budget_tokens: int | None
    budget_usd: float | None
    agent_overhead_tokens: int
    agent_overhead_usd: float

class EpicOut(BaseModel):
    id: str
    title: str
    description: str
    tags: list[str]
    status: str
    priority: int
    progress: EpicProgressOut
    cost: EpicCostOut
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    result_summary: str | None

    model_config = {"from_attributes": True}
```

### Task Schemas

```python
class TaskRequirements(BaseModel):
    """Capabilities needed by the workflow executing this task."""
    model: str | None = None            # Model capability (e.g., "gpt-4")
    tools: list[str] = []               # Tool types needed (e.g., ["code", "web_search"])
    trigger: str | None = None          # Trigger type (e.g., "webhook")
    memory: bool = False                # Whether memory_read/write is needed

class TaskIn(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = []
    depends_on: list[str] = []
    priority: int | None = None      # Inherits from epic if None
    workflow_slug: str | None = None  # Pre-assigned workflow, or agent creates one later
    estimated_tokens: int | None = None
    max_retries: int = 2
    requirements: TaskRequirements | None = None  # Capability requirements for workflow matching

class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    status: Literal["pending", "blocked", "running", "completed", "failed", "cancelled"] | None = None
    priority: int | None = None
    workflow_slug: str | None = None
    execution_id: str | None = None
    result_summary: str | None = None
    error_message: str | None = None
    notes: list[dict] | None = None

class TaskCostOut(BaseModel):
    estimated_tokens: int | None
    actual_tokens: int
    actual_usd: float
    llm_calls: int
    tool_invocations: int
    duration_ms: int

class TaskOut(BaseModel):
    id: str
    epic_id: str
    title: str
    description: str
    tags: list[str]
    status: str
    priority: int
    depends_on: list[str]
    requirements: dict | None       # TaskRequirements as dict
    workflow_slug: str | None
    execution_id: str | None
    workflow_source: str
    cost: TaskCostOut
    retry_count: int
    max_retries: int
    notes: list[dict]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result_summary: str | None
    error_message: str | None

    model_config = {"from_attributes": True}

class TaskSearchIn(BaseModel):
    query: str = ""
    tags: list[str] = []
    status: str | None = None
    epic_id: str | None = None
```

---

## Integration Points

### 1. Orchestrator → Task cost sync

After a workflow execution completes, the orchestrator (or a post-execution hook) aggregates execution log metrics and writes them back to the associated task:

```python
async def sync_task_from_execution(task_id: str, execution: WorkflowExecution):
    """Called by orchestrator after execution completes."""
    task = db.query(Task).get(task_id)
    if not task:
        return
    
    logs = execution.logs
    task.actual_tokens = sum(log.metadata.get("tokens", 0) for log in logs)
    task.llm_calls = sum(1 for log in logs if log.metadata.get("is_llm_call"))
    task.tool_invocations = sum(1 for log in logs if log.metadata.get("is_tool_call"))
    task.duration_ms = (execution.completed_at - execution.started_at).total_seconds() * 1000
    # USD cost from credential pricing metadata: {"input_per_1k": 0.01, "output_per_1k": 0.03}
    task.actual_usd = compute_cost_from_credential(task.actual_tokens, credential_id)
    
    if execution.status == "completed":
        task.status = "completed"
        task.completed_at = execution.completed_at
    elif execution.status == "failed":
        task.retry_count += 1
        task.status = "failed" if task.retry_count >= task.max_retries else "pending"
        task.error_message = execution.error_message
    
    # Roll up to epic
    sync_epic_costs(task.epic)
    
    # Check if blocked tasks are now unblocked
    unblock_dependents(task)
```

### 2. Spawn-and-await tool → Task + Execution

`spawn_and_await` uses LangGraph's `interrupt()` primitive to pause the agent's ReAct loop without blocking any RQ workers. This reuses the existing `_subworkflow` orchestrator pattern.

**Flow:**

1. Agent calls `spawn_and_await` tool inside its ReAct loop
2. Tool calls `interrupt()` — saves full agent state (conversation + pending tool call) to checkpointer
3. Agent node returns `{"_subworkflow": {"child_execution_id": "..."}}` — existing orchestrator signal
4. Orchestrator creates child execution, sets `task.execution_id` and `task.status = "running"`
5. RQ worker releases (not blocked)
6. Child workflow executes on other RQ workers
7. On child completion: orchestrator injects result into `state["_subworkflow_results"]`, re-enqueues agent node
8. Agent resumes via `Command(resume=child_result)` — checkpointer restores full state, `interrupt()` returns child result
9. Tool returns result to LLM, ReAct loop continues
10. Calls `sync_task_from_execution` on completion

**Checkpointer requirement:** `spawn_and_await` requires a checkpointer. Two strategies:

| Scenario | Checkpointer | Thread ID | Lifecycle |
|---|---|---|---|
| `conversation_memory=ON` | `SqliteSaver` (SQLite) | `{user_id}:{chat_id}:{workflow_id}` | Permanent — interrupt state saved as part of conversation history |
| `conversation_memory=OFF` | Redis checkpointer | `exec:{execution_id}:{node_id}` | Ephemeral — auto-expires via Redis TTL (1h), no cleanup needed |

The Redis checkpointer (`langgraph-checkpoint-redis`) is used only when conversation memory is off. It provides just enough state persistence for interrupt/resume within a single execution, then auto-expires. No SQLite pollution from throwaway agent runs.

### 3. WebSocket events

New event types for the global WebSocket:

```
task_created      — { task_id, epic_id, title, status }
task_updated      — { task_id, status, cost? }
epic_updated      — { epic_id, status, progress }
```

Agents subscribed to `epic:<id>` receive real-time task status updates.

### 4. Discovery → Memory bridge

The `epic_search` tool queries the task registry, but results can also feed back into the memory system:

```python
# After epic completes successfully, store as procedural memory
memory_write(
    key=f"procedure:{epic.id}",
    value={
        "goal": epic.title,
        "tags": epic.tags,
        "workflow_ids": [t.workflow_id for t in epic.tasks],
        "success_rate": epic.completed_tasks / epic.total_tasks,
        "avg_cost_usd": epic.spent_usd / epic.total_tasks,
        "duration_ms": total_duration,
    },
    fact_type="procedure"
)
```

This creates the feedback loop: future agents discover successful patterns via both the registry (structured query) and memory (semantic search).

---

## Migration

Single Alembic migration adding `epics` and `tasks` tables. No changes to existing models — the linkage to `workflows` and `workflow_executions` is via foreign keys and soft references (`execution_id` as string, not FK, since executions may be cleaned up independently).

```python
def upgrade():
    op.create_table("epics", ...)
    op.create_table("tasks", ...)
    op.create_index("ix_epics_status", "epics", ["status"])
    op.create_index("ix_epics_user_profile_id", "epics", ["user_profile_id"])
    op.create_index("ix_tasks_epic_id", "tasks", ["epic_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_workflow_id", "tasks", ["workflow_id"])
```

---

## What This Enables

With this registry in place, the main agent can:

1. **"What am I working on?"** → `epic_status(epic_id)` — full picture of progress, cost, blockers
2. **"Which tasks are ready to run?"** → `GET /tasks/actionable/` — dependencies resolved, ready to spawn
3. **"Am I over budget?"** → `check_budget()` — before spawning, verify the epic can afford it
4. **"Has anyone solved this before?"** → `epic_search("coverage analysis auth")` — find past successful epics and reuse their workflows
5. **"This subtask failed, what now?"** → Check `retry_count < max_retries`, auto-retry or cancel dependents
6. **"User asked for a status update"** → Pull epic progress, format as natural language summary
7. **"I was interrupted, where was I?"** → Load active epics, check task statuses, resume

---

## Open Questions

1. **Should `execution_id` be a proper FK to `workflow_executions`?** Soft reference (string) is more resilient to execution cleanup, but loses referential integrity. Starting with soft reference.

2. **Tag-based search vs. full-text search on descriptions?** Tags are fast and explicit, but description search is more flexible. Starting with tags + LIKE queries, add proper FTS later.

3. **Should tasks support re-assignment to a different workflow mid-lifecycle?** Current design allows updating `workflow_slug`, but the semantics of switching workflows on a running task need thought.

4. ~~**Epic nesting?**~~ — **Deferred.** Starting flat (epics contain tasks). Add `parent_epic_id` later if agents decompose epics into sub-epics.

5. ~~**Garbage collection?**~~ — **RESOLVED.** Manual management via a Kanban-style task board UI. No automated GC policy needed initially.

---

## Resolved Design Decisions

1. **`spawn_and_await` execution model** — Non-blocking interrupt/resume via LangGraph's `interrupt()` primitive. Reuses existing `_subworkflow` orchestrator pattern. Zero blocked RQ workers. See Integration Points § 2.

2. **Dual checkpointer strategy** — `SqliteSaver` for agents with conversation memory (durable, permanent). Redis checkpointer for agents without conversation memory that need `spawn_and_await` (ephemeral, auto-expires via TTL). Agent factory selects backend based on configuration. New dependency: `langgraph-checkpoint-redis`.
