# Self-Improving Agent: Gap Analysis & Global Epics/Tasks Plan

## 1. Current Capabilities

### What works today

- **Task registry** (`platform/schemas/node_type_defs.py`) — 23 node types registered with port definitions
- **Agent tools** — epic_tools and task_tools components give agents CRUD over epics/tasks
- **spawn_and_await** (`platform/components/spawn_and_await.py`) — agent can spawn child workflow executions and await results
- **DSL compiler** (`platform/services/dsl_compiler.py`) — YAML DSL compiles to workflow graph (nodes + edges)
- **Workflow discovery** (`platform/components/workflow_discover.py`) — agent can list/inspect available workflows
- **Self-modification** — agents can create/update nodes and edges via API, effectively editing their own workflows
- **Memory** — conversation memory via SqliteSaver checkpointer, plus memory tools (facts, episodes, procedures)
- **Epics & tasks model** — full CRUD API for epics (goals) and tasks (units of work), with dependency tracking, progress sync, and WebSocket events

## 2. Bugs to Fix

### identify_user registration
The `identify_user` component may fail to register the user correctly when invoked from certain trigger contexts. Needs investigation into how `user_profile_id` is resolved for agent-created users.

### error_handler NotImplementedError
The error handler component raises `NotImplementedError` in some code paths. This should be replaced with a proper fallback that logs the error and marks the execution as failed gracefully.

### spawn failure stuck execution
When `spawn_and_await` spawns a child execution that fails, the parent execution can get stuck in "running" state indefinitely. Needs a timeout or failure-propagation mechanism so the parent detects child failure and transitions to failed/completed.

## 3. Missing Capabilities

| Capability | Description | Priority |
|---|---|---|
| **Cost tracking** | Track token usage and USD cost per execution/task/epic. Fields exist on the model but are never populated by the orchestrator. | High |
| **Timeout enforcement** | No per-node or per-execution timeout. Long-running LLM calls or tool invocations can hang forever. | High |
| **Scheduler** | No built-in cron/interval trigger. Agents cannot schedule recurring tasks or delayed executions. | Medium |
| **Safety guardrails** | No budget enforcement (budget_tokens/budget_usd fields are decorative). No rate limiting on agent-initiated executions. | High |
| **DSL switch/loop** | DSL compiler does not support `switch` or `loop` node types. Agents can only build linear/branching workflows via DSL. | Medium |
| **Semantic search** | No vector/embedding-based search over epics, tasks, or workflow outputs. Agents must use exact text matching. | Low |

## 4. Global Epics/Tasks Change

### Rationale

For a self-improving agent platform, any agent should be able to see and act on any epic or task. The current per-user scoping prevents cross-agent collaboration:
- Agent A creates an epic, Agent B cannot see or pick up tasks from it
- The orchestrator agent cannot inspect what other agents have done
- There is only one human user in practice; per-user isolation adds complexity without benefit

### Implementation

The `user_profile_id` column stays on `Epic` for audit (who created it) but **queries stop filtering by it**.

#### Files modified

**`platform/api/epics.py`** — Removed `Epic.user_profile_id == profile.id` from:
- `list_epics` query
- `get_epic` query
- `update_epic` query
- `delete_epic` query
- `batch_delete_epics` subquery and delete query
- `list_epic_tasks` epic ownership check

**`platform/api/tasks.py`** — Removed user-scoping + unnecessary Epic joins:
- `list_tasks` — query Task directly instead of joining Epic for user filter
- `create_task` — removed Epic ownership check (just verify epic exists)
- `get_task` — query Task directly by ID
- `update_task` — query Task directly by ID
- `delete_task` — query Task directly by ID
- `batch_delete_tasks` — removed Epic join and user filter

**`platform/components/epic_tools.py`** — Removed `Epic.user_profile_id == user_profile_id` from:
- `epic_status` query
- `update_epic` query
- `search_epics` query
- Kept `user_profile_id` on `create_epic` for audit trail

**`platform/components/task_tools.py`** — Removed `Epic.user_profile_id == user_profile_id` from:
- `create_task` epic lookup
- `list_tasks` epic lookup
- `update_task` task query (also removed unnecessary Epic join)
- `cancel_task` task query (also removed unnecessary Epic join)

### Tests
No test changes needed. All existing tests use a single user fixture and have no cross-user isolation assertions.

## 5. Bootstrap Path

Minimum steps to get a self-improving agent loop working:

1. **Fix spawn failure stuck execution** — without this, the orchestrator agent's child executions can silently hang
2. **Apply global epics/tasks** (this change) — so the orchestrator can see all work across agents
3. **Wire cost tracking** in the orchestrator — populate `spent_tokens`/`spent_usd` after each LLM call
4. **Add budget enforcement** — check `budget_tokens`/`budget_usd` before executing a task, fail early if exceeded
5. **Build an orchestrator workflow** — a meta-agent that:
   - Reads open epics/tasks
   - Picks the highest-priority unblocked task
   - Spawns a worker workflow to execute it
   - Records results and updates task status
6. **Add a scheduler trigger** — so the orchestrator runs on a cron (e.g., every 5 minutes) to check for new work
7. **DSL switch/loop support** — so agents can build more sophisticated workflows programmatically
