# Multi-Agent Delegation — Implementation Phases

> Reference breakdown for implementing the multi-agent delegation feature in manageable chunks.
> See `multiagent_delegation_architecture.md` for full design spec.
>
> Created: 2026-02-10

---

## Phase 1: Task Registry (Models + API)

**Status:** Not started
**Branch:** `feature/delegation-phase1-task-registry`
**Scope:** Database foundation — no agent tools yet

### Deliverables

- [ ] `platform/models/epic.py` — Epic + Task SQLAlchemy models
  - Epic: id (ULID), title, description, tags, status lifecycle (planning→active→completed/failed/cancelled), priority, budget tracking (tokens/usd), progress counters, ownership (created_by_node_id, workflow_id, user_profile_id)
  - Task: id (ULID), epic_id (FK), title, description, tags, status lifecycle (pending→blocked→running→completed/failed/cancelled), priority, workflow linkage (workflow_id, workflow_slug, execution_id soft ref, workflow_source), depends_on (JSON list), requirements (JSON), cost tracking, retry logic, notes (JSON list)
- [ ] Export Epic/Task from `platform/models/__init__.py`
- [ ] Alembic migration creating `epics` and `tasks` tables
- [ ] `platform/schemas/epic.py` — Pydantic schemas
  - EpicCreate, EpicUpdate, EpicOut, EpicListOut (paginated)
  - TaskCreate, TaskUpdate, TaskOut, TaskListOut (paginated)
  - EpicProgressOut (progress + cost summary)
- [ ] `platform/api/epics.py` — REST endpoints
  - `GET/POST /api/v1/epics/`
  - `GET/PATCH/DELETE /api/v1/epics/{epic_id}/`
  - `GET /api/v1/epics/{epic_id}/progress/`
  - `POST /api/v1/epics/batch-delete/`
- [ ] `platform/api/tasks.py` — REST endpoints
  - `GET/POST /api/v1/tasks/` (filterable by epic_id, status, tags)
  - `GET/PATCH/DELETE /api/v1/tasks/{task_id}/`
  - `POST /api/v1/tasks/batch-delete/`
- [ ] Register routers in `platform/main.py`
- [ ] WebSocket broadcast events: `task_created`, `task_updated`, `epic_updated`
- [ ] Add `tags = Column(JSON, default=list)` to Workflow model + migration
- [ ] Tests for models, schemas, and API endpoints

### Notes

- Epic/Task IDs use ULID (string PKs), not auto-increment
- `execution_id` on Task is a soft reference (string), not a FK
- All list endpoints follow existing pagination pattern: `{"items": [...], "total": N}`
- Check for conflicting Alembic heads before creating migration

### Dependencies

None — this is the foundation.

---

## Phase 2: Registry Agent Tools

**Status:** Not started
**Branch:** `feature/delegation-phase2-registry-tools`
**Scope:** Let agents create/manage epics and tasks via tool calls

### Deliverables

- [ ] `platform/components/epic_create.py` — Create tracked epic, return epic_id
- [ ] `platform/components/epic_status.py` — Get progress, cost, task breakdown
- [ ] `platform/components/epic_update.py` — Update status/budget/result_summary; cancel cascades to tasks
- [ ] `platform/components/epic_search.py` — Search past epics by description + tags; returns success_rate, avg_cost
- [ ] `platform/components/task_create.py` — Create task under epic with optional dependencies
- [ ] `platform/components/task_list.py` — List tasks filtered by epic, status, tags
- [ ] `platform/components/task_update.py` — Update task status, notes, result_summary
- [ ] `platform/components/task_cancel.py` — Cancel task and its running execution
- [ ] Register all 8 in `SUB_COMPONENT_TYPES` (builder.py + topology.py)
- [ ] Register all 8 in `NODE_TYPE_REGISTRY` (node_type_defs.py)
- [ ] Add polymorphic_identity entries in ComponentConfig hierarchy if needed
- [ ] Frontend: add new tool node types to NodePalette and type definitions
- [ ] Tests for each tool component

### Notes

- These are LangChain `@tool` factories, same pattern as existing tools (http_request, platform_api, etc.)
- Each tool component returns a factory function that the builder wires into the agent's tool list
- Tools interact with the DB directly (get_db session) — same pattern as platform_api tool

### Dependencies

- Phase 1 (Epic/Task models and API must exist)

---

## Phase 3: `spawn_and_await` Tool + Dual Checkpointer

**Status:** Not started
**Branch:** `feature/delegation-phase3-spawn-and-await`
**Scope:** The core delegation primitive — non-blocking subworkflow execution

### Deliverables

- [ ] Add `langgraph-checkpoint-redis` to dependencies
- [ ] Implement Redis checkpointer factory (lazy singleton, similar to existing SqliteSaver)
- [ ] Dual checkpointer selection logic in `platform/components/agent.py`:
  - conversation_memory=ON → SqliteSaver (permanent, thread_id = `{user_id}:{chat_id}:{workflow_id}`)
  - has spawn_and_await tool → Redis checkpointer (ephemeral, TTL 1h, thread_id = `exec:{execution_id}:{node_id}`)
  - Neither → None (one-shot)
- [ ] `platform/components/spawn_and_await.py` — Tool using LangGraph `interrupt()`:
  - Calls `interrupt({"action": "spawn_workflow", ...})`
  - Orchestrator detects `_subworkflow` signal, spawns child execution, releases RQ worker
  - On child completion, orchestrator resumes parent via `Command(resume=result)`
  - `interrupt()` returns child result to tool, LLM continues reasoning
- [ ] Orchestrator changes (if any needed beyond existing `_subworkflow` pattern)
- [ ] Cost sync hook: after execution completes, update linked Task with actual_tokens, actual_usd, duration_ms, llm_calls, tool_invocations
- [ ] Register spawn_and_await in SUB_COMPONENT_TYPES, NODE_TYPE_REGISTRY
- [ ] Tests (interrupt/resume flow, cost sync, checkpointer selection)

### Notes

- This reuses the existing `_subworkflow` / `_handle_child_completion` / `_subworkflow_results` orchestrator infrastructure
- Zero new orchestration code needed if existing pattern works — verify first
- The key innovation is using `interrupt()` so no RQ worker blocks while waiting
- Need to verify LangGraph version supports `interrupt()` primitive

### Dependencies

- Phase 2 (task_id linkage for cost sync)
- Verify LangGraph version compatibility

---

## Phase 4: `workflow_create` Tool (DSL Compiler)

**Status:** Not started
**Branch:** `feature/delegation-phase4-workflow-dsl`
**Scope:** Let agents create workflows programmatically via YAML DSL

### Deliverables

- [ ] `platform/services/dsl_compiler.py` — YAML DSL → platform API calls:
  - Parse YAML spec (name, description, tags, trigger, model, steps)
  - Create workflow via existing API/service
  - Create nodes for each step + trigger + model
  - Create edges (implicit linear flow from step order)
  - Inline tool declarations → create tool nodes + edges
- [ ] Fork+patch mode:
  - `based_on: <slug>` clones existing workflow
  - `patches` list applies mutations: add_step, remove_step, update_prompt, add_tool, remove_tool, update_config
- [ ] Capability-based model resolution:
  - `inherit` → use parent workflow's model
  - `capability: "gpt-4"` → find matching LLMProviderCredential
- [ ] `platform/components/workflow_create.py` — Tool wrapper around DSL compiler
- [ ] Register in SUB_COMPONENT_TYPES, NODE_TYPE_REGISTRY
- [ ] Tests (DSL parsing, compilation, fork+patch, error cases)

### Notes

- See `docs/workflow_dsl_spec.md` for full DSL specification
- The compiler should use existing workflow/node/edge creation services, not raw SQL
- Validation: compiled workflow should pass existing `POST /workflows/{slug}/validate/`

### Dependencies

- Phase 1 (Workflow.tags column needed for tagging created workflows)
- Independent of Phase 3

---

## Phase 5: `workflow_discover` Tool

**Status:** Not started
**Branch:** `feature/delegation-phase5-workflow-discover`
**Scope:** Let agents find and reuse existing workflows via gap-analysis scoring

### Deliverables

- [ ] `platform/services/workflow_discovery.py` — Search + scoring logic:
  - Query workflows by description (text similarity), tags (overlap), requirements (capability matching)
  - Gap-analysis scoring: `match_score = capability_match * 0.6 + tag_overlap * 0.2 + success_rate * 0.2`
  - Return: workflow slug, match_score, has/missing/extra capabilities
  - Three-tier decision output: reuse (>=0.95), fork+patch (>=0.50), create new (<0.50)
- [ ] `platform/components/workflow_discover.py` — Tool wrapper
- [ ] Register in SUB_COMPONENT_TYPES, NODE_TYPE_REGISTRY
- [ ] Tests (scoring logic, search, edge cases)

### Notes

- Success rate comes from completed executions of that workflow
- Tag matching uses Workflow.tags (added in Phase 1)
- Text similarity can start simple (keyword overlap) — no need for embeddings initially

### Dependencies

- Phase 4 (agents need workflow_create to act on discovery results)
- Phase 1 (Workflow.tags)

---

## Phase 6: Frontend — Task Registry UI

**Status:** Not started
**Branch:** `feature/delegation-phase6-frontend`
**Scope:** Visibility into agent-managed epics and tasks

### Deliverables

- [ ] `platform/frontend/src/api/epics.ts` — TanStack Query hooks:
  - useEpics(), useEpic(id), useCreateEpic(), useUpdateEpic(), useDeleteEpic(), useBatchDeleteEpics()
  - useTasks(epicId?), useTask(id), useCreateTask(), useUpdateTask(), useDeleteTask(), useBatchDeleteTasks()
- [ ] `platform/frontend/src/features/epics/EpicsPage.tsx` — Epic list (table with status, progress bar, cost)
- [ ] `platform/frontend/src/features/epics/EpicDetailPage.tsx` — Epic detail with task list
- [ ] `platform/frontend/src/types/models.ts` — Epic/Task TypeScript interfaces
- [ ] WebSocket subscriptions to `epic:<id>` channels for live task updates
- [ ] Update `platform/frontend/src/lib/wsManager.ts` for new event types
- [ ] Sidebar navigation entry for Epics
- [ ] Routes: `/epics`, `/epics/:id`

### Notes

- Follow existing patterns from ExecutionsPage / CredentialsPage for table layout
- Pagination follows existing `{"items": [...], "total": N}` pattern
- Consider Kanban-style view as future enhancement (table first)

### Dependencies

- Phase 1 (API endpoints must exist)
- Independent of Phases 3-5

---

## Dependency Graph

```
Phase 1 (Task Registry)
  │
  ├──→ Phase 2 (Registry Tools)
  │      │
  │      ├──→ Phase 3 (spawn_and_await + Checkpointer)
  │      │
  │      ├──→ Phase 4 (workflow_create DSL) ──→ Phase 5 (workflow_discover)
  │      │
  │      └──→ Phase 6 (Frontend UI)
  │
  └──→ Phase 6 (Frontend UI)  ← can start after Phase 1 for basic epic/task views
```

Phases 3, 4, and 6 can proceed in parallel after Phase 2 is complete.

---

## Context Management Tips

- Each phase should be implementable in 1-2 Claude Code sessions
- Start each session by referencing this doc and the relevant phase
- After completing a phase, commit to its feature branch and merge to master before starting the next
- If context gets tight mid-phase, commit progress and start a fresh session referencing the phase checklist
- The full design spec lives in `docs/multiagent_delegation_architecture.md` — reference it for detailed schemas and behavior
