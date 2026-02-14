# Multi-Agent Delegation — Implementation Phases

> Reference breakdown for implementing the multi-agent delegation feature in manageable chunks.
> See `multiagent_delegation_architecture.md` for full design spec.
>
> Created: 2026-02-10

---

## Phase 1: Task Registry (Models + API)

**Status:** Complete
**Branch:** `feature/delegation-phase1-task-registry`
**Scope:** Database foundation — no agent tools yet

### Deliverables

- [x] `platform/models/epic.py` — Epic + Task SQLAlchemy models
  - Epic: id (ULID), title, description, tags, status lifecycle (planning→active→completed/failed/cancelled), priority, budget tracking (tokens/usd), progress counters, ownership (created_by_node_id, workflow_id, user_profile_id)
  - Task: id (ULID), epic_id (FK), title, description, tags, status lifecycle (pending→blocked→running→completed/failed/cancelled), priority, workflow linkage (workflow_id, workflow_slug, execution_id soft ref, workflow_source), depends_on (JSON list), requirements (JSON), cost tracking, retry logic, notes (JSON list)
- [x] Export Epic/Task from `platform/models/__init__.py`
- [x] Alembic migration creating `epics` and `tasks` tables
- [x] `platform/schemas/epic.py` — Pydantic schemas
  - EpicCreate, EpicUpdate, EpicOut, TaskCreate, TaskUpdate, TaskOut, BatchDeleteEpicsIn, BatchDeleteTasksIn
  - ~~EpicListOut, TaskListOut~~ (not needed — list endpoints use standard `{"items": [...], "total": N}` pattern)
  - ~~EpicProgressOut~~ (not needed — epic fields already include progress counters)
- [x] `platform/api/epics.py` — REST endpoints
  - `GET/POST /api/v1/epics/`
  - `GET/PATCH/DELETE /api/v1/epics/{epic_id}/`
  - `GET /api/v1/epics/{epic_id}/tasks/` (lists tasks for an epic)
  - `POST /api/v1/epics/batch-delete/`
  - ~~`GET /api/v1/epics/{epic_id}/progress/`~~ (not needed — GET epic already returns progress counters)
- [x] `platform/api/tasks.py` — REST endpoints
  - `GET/POST /api/v1/tasks/` (filterable by epic_id, status, tags)
  - `GET/PATCH/DELETE /api/v1/tasks/{task_id}/`
  - `POST /api/v1/tasks/batch-delete/`
- [x] Register routers in `platform/api/__init__.py` (follows existing pattern)
- [x] WebSocket broadcast events: `epic_created`, `epic_updated`, `epic_deleted`, `task_created`, `task_updated`, `task_deleted`, `tasks_deleted`
- [x] Add `tags = Column(JSON, default=list)` to Workflow model + migration
- [x] Tests for models, schemas, and API endpoints (`test_epics_tasks.py`)

### Notes

- Epic/Task IDs use ULID (string PKs), not auto-increment
- `execution_id` on Task is a soft reference (string), not a FK
- All list endpoints follow existing pagination pattern: `{"items": [...], "total": N}`
- Check for conflicting Alembic heads before creating migration

### Dependencies

None — this is the foundation.

---

## Phase 2: Registry Agent Tools

**Status:** Complete
**Branch:** `feat/registry-agent-tools`
**Scope:** Let agents create/manage epics and tasks via tool calls

### Deliverables

Consolidated into 2 files (instead of 8 separate) following the compound tool factory pattern:

- [x] `platform/components/epic_tools.py` — Factory returning 4 LangChain tools:
  - `create_epic` — Create tracked epic, return epic_id
  - `epic_status` — Get progress, cost, task breakdown
  - `update_epic` — Update status/budget/result_summary; cancel cascades to tasks
  - `search_epics` — Search past epics by description + tags; returns success_rate, avg_cost
- [x] `platform/components/task_tools.py` — Factory returning 4 LangChain tools:
  - `create_task` — Create task under epic with optional dependencies
  - `list_tasks` — List tasks filtered by epic, status, tags
  - `update_task` — Update task status, notes, result_summary
  - `cancel_task` — Cancel task and its running execution
- [x] Register `epic_tools` and `task_tools` in `SUB_COMPONENT_TYPES` (builder.py + topology.py)
- [x] Register in `NODE_TYPE_REGISTRY` (node_type_defs.py)
- [x] Add polymorphic_identity entries (`_EpicToolsConfig`, `_TaskToolsConfig`) in models/node.py
- [x] Frontend: NodePalette (ClipboardList/ListChecks icons), type definitions, NodeDetailsPanel
- [x] Tests: `test_epic_task_tools.py` (60+ tests, 1383 lines)
- [x] Helper module: `api/epic_helpers.py` (sync_epic_progress, serialize_epic/task)

### Notes

- These are LangChain `@tool` factories, same pattern as existing tools (http_request, platform_api, etc.)
- Each tool component returns a factory function that the builder wires into the agent's tool list
- Tools interact with the DB directly (SessionLocal) — same pattern as platform_api tool
- All operations scoped to user_profile_id from workflow owner for security

### Dependencies

- Phase 1 (Epic/Task models and API must exist)

---

## Phase 3: `spawn_and_await` Tool + Dual Checkpointer

**Status:** Complete
**Branch:** `feat/spawn-and-await`
**Scope:** The core delegation primitive — non-blocking subworkflow execution

### Deliverables

- [x] Add `langgraph-checkpoint-redis>=0.3` to `platform/requirements.txt`
- [x] `platform/components/spawn_and_await.py` — Tool factory using `@register("spawn_and_await")`:
  - Returns a single `@tool` function: `spawn_and_await(workflow_slug, input_text, task_id, input_data)`
  - Calls `interrupt({"action": "spawn_workflow", ...})` from `langgraph.types`
  - On resume, `interrupt()` returns the child's output → tool returns it as JSON string to LLM
- [x] `_get_redis_checkpointer()` lazy singleton in `platform/components/agent.py`:
  - Uses `RedisSaver(redis_url=settings.REDIS_URL)` from `langgraph.checkpoint.redis`
- [x] Dual checkpointer selection logic in `platform/components/agent.py`:
  - conversation_memory=ON → SqliteSaver (permanent, thread_id = `{user_id}:{chat_id}:{workflow_id}`)
  - has spawn_and_await tool → RedisSaver (ephemeral, thread_id = `exec:{execution_id}:{node_id}`)
  - Neither → None (one-shot, no checkpointer)
- [x] Interrupt/resume flow in agent_node():
  - On `GraphInterrupt`: extracts interrupt payload, calls `_create_child_from_interrupt()`, returns `{"_subworkflow": {"child_execution_id": id}}`
  - On resume (child result in `_subworkflow_results[node_id]`): calls `agent.invoke(Command(resume=child_result), config)`
  - Reuses existing orchestrator `_subworkflow` / `_resume_from_child` infrastructure — no orchestrator changes needed
- [x] `_create_child_from_interrupt()` helper in `platform/components/agent.py`:
  - Resolves target workflow by slug, creates `WorkflowExecution` with parent linkage
  - Links Task record when `task_id` provided (sets `task.execution_id`, `task.status = "running"`)
  - Enqueues child on RQ
- [x] `_sync_task_costs()` in `platform/services/orchestrator.py`:
  - After execution completes/fails, syncs linked Task: `status`, `duration_ms`, `result_summary`/`error_message`, `completed_at`
  - Calls `sync_epic_progress()` to update epic counters
  - Called in `_finalize()` and both failure paths
  - Token fields (`actual_tokens`, `actual_usd`, `llm_calls`, `tool_invocations`) left at 0 — future work
- [x] Registration in all required places:
  - `_SpawnAndAwaitConfig` polymorphic identity + `COMPONENT_TYPE_TO_CONFIG` entry in `models/node.py`
  - `SUB_COMPONENT_TYPES` in `services/builder.py` and `services/topology.py`
  - `COMPONENT_REGISTRY` via import in `components/__init__.py`
  - `NodeTypeSpec` in `schemas/node_type_defs.py` (category="agent", single string output port)
- [x] Frontend: `ComponentType` union, NodePalette (Rocket icon, Agent category), WorkflowCanvas (color + FA icon + tool/sub-component lists), NodeDetailsPanel SUB_TYPES
- [x] Tests: `platform/tests/test_spawn_and_await.py` (18 tests):
  - Tool factory, checkpointer selection, interrupt flow, child creation, task linkage, cost sync, registration

### Notes

- Confirmed: LangGraph 1.0.8 installed — `interrupt()`, `Command`, `GraphInterrupt` all available
- Reuses existing orchestrator `_subworkflow` / `_resume_from_child` / `_subworkflow_results` infrastructure with zero orchestrator routing changes
- The key difference from the standalone `subworkflow` component: `spawn_and_await` runs *inside* an agent's `create_react_agent` execution — the agent's full internal state (messages, pending tool calls) is checkpointed via LangGraph's `interrupt()` so the LLM can continue reasoning after the child returns
- No migration needed — uses existing `component_configs` STI table (polymorphic_identity is just a discriminator value)

### Dependencies

- Phase 2 (task_id linkage for cost sync) ✓

---

## Phase 4: `workflow_create` Tool (DSL Compiler)

**Status:** Complete
**Branch:** `feat/workflow-create-dsl`
**Scope:** Let agents create workflows programmatically via YAML DSL

### Deliverables

- [x] `platform/services/dsl_compiler.py` — YAML DSL → DB objects (4-stage pipeline):
  - `_parse_dsl()` — parse YAML, validate top-level keys, step types, trigger types
  - `_resolve_model()` — `inherit` (from parent agent), `capability` (substring match), `credential_id` (direct)
  - `_build_graph()` — convert steps to node/edge dicts with trigger, linear edges, sub-components
  - `_persist_workflow()` — create Workflow + WorkflowNode + BaseComponentConfig + WorkflowEdge in single transaction
  - Step type mapping: `code` → `code`, `agent` → `agent`, `http` → `http_request`
  - Trigger mapping: `webhook/telegram/chat/none/manual` → `trigger_*`
  - Inline tool mapping: `code/http_request/web_search/calculator/datetime` → tool nodes + `tool` edges
  - Agent sub-components: `ai_model` node + `llm` edge, conversation memory via `extra_config`
- [x] Fork+patch mode (`_compile_fork`):
  - `based_on: <slug>` clones existing workflow (deep copy configs)
  - `patches` list applies mutations: `update_prompt`, `add_step`, `remove_step`, `add_tool`, `remove_tool`, `update_config`
  - Edge reconnection on add/remove steps
  - `forked_from_id` linkage preserved
- [x] Capability-based model resolution:
  - `inherit: true` → copy from parent agent's linked ai_model config (via `llm` edge)
  - `capability: "gpt-4"` → query LLMProviderCredential, first-available match
  - `credential_id: N` → direct pass-through
- [x] `platform/components/workflow_create.py` — LangChain `@tool` factory:
  - Single `workflow_create(dsl, tags)` tool
  - Resolves parent node for `inherit` model resolution
  - Appends comma-separated tags to created workflow
- [x] Registration in all required places:
  - `_WorkflowCreateConfig` polymorphic identity + `COMPONENT_TYPE_TO_CONFIG` entry in `models/node.py`
  - `"workflow_create"` + `"spawn_and_await"` added to `ComponentTypeStr` in `schemas/node.py`
  - `SUB_COMPONENT_TYPES` in `services/builder.py` and `services/topology.py`
  - `COMPONENT_REGISTRY` via import in `components/__init__.py`
  - `NodeTypeSpec` in `schemas/node_type_defs.py` (category="agent", single string output port)
  - Frontend: `ComponentType` union, NodePalette (PencilRuler icon, Agent category), WorkflowCanvas (teal color + faPenRuler icon + tool/sub-component lists)
- [x] Tests:
  - `platform/tests/test_dsl_compiler.py` (54 tests): parse, build graph, model resolution, slugify, fork patches, error cases
  - `platform/tests/test_workflow_create.py` (23 tests): tool factory, registration, end-to-end DB compilation, fork DB, model resolution DB, tool invocation

### Notes

- Compiler uses `BaseComponentConfig` directly (same as API `nodes.py`) — STI discriminator set via `component_type` kwarg
- Slug auto-generation: `_slugify(name)` + uniqueness check with `-2`, `-3` suffix
- WS broadcast of `workflow_created` event is best-effort (non-blocking)
- Deferred: switch/loop/subworkflow step types, `discover: true` model resolution, tool config inheritance, DSL validation endpoint

### Dependencies

- Phase 1 (Workflow.tags column needed for tagging created workflows) ✓
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
