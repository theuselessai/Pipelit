# Plan: Remove Epics & Tasks System

## Context
Remove the entire Epic/Task subsystem (models, API, components, frontend pages, orchestrator integration) while preserving the memory system, checkpoints, identify_user, and migration files. Branch: `fix/remove-epics` from `master`.

## Task Dependency Graph
```
Wave 1 (backend deletions) → Wave 2 (backend edits)
Wave 1 → Wave 3 (frontend deletions + edits)
Wave 2 + Wave 3 → Wave 4 (fixture cleanup + verification)
```

## Execution Waves

### Wave 1: Backend File Deletions (parallel, safe — no other files import these directly)

- **Task 1.1**: Delete `platform/models/epic.py` — Agent: sisyphus-junior
- **Task 1.2**: Delete `platform/schemas/epic.py` — Agent: sisyphus-junior
- **Task 1.3**: Delete `platform/api/epics.py` — Agent: sisyphus-junior
- **Task 1.4**: Delete `platform/api/tasks.py` — Agent: sisyphus-junior
- **Task 1.5**: Delete `platform/api/epic_helpers.py` — Agent: sisyphus-junior
- **Task 1.6**: Delete `platform/components/epic_tools.py` — Agent: sisyphus-junior
- **Task 1.7**: Delete `platform/components/task_tools.py` — Agent: sisyphus-junior
- **Task 1.8**: Delete `platform/tests/test_epics_tasks.py` — Agent: sisyphus-junior
- **Task 1.9**: Delete `platform/tests/test_epic_task_tools.py` — Agent: sisyphus-junior

> All 9 deletions can be done in a single sisyphus-junior task (just `git rm` them all).

---

### Wave 2: Backend File Edits (parallel within wave, depends on Wave 1)

- **Task 2.1**: Edit `platform/models/__init__.py` — Agent: sisyphus-junior
  - Remove line 29: `from models.epic import Epic, Task  # noqa: F401`

- **Task 2.2**: Edit `platform/models/node.py` — Agent: sisyphus-junior
  - Remove lines 171-176 (the `_EpicToolsConfig` and `_TaskToolsConfig` classes)
  - Remove from `COMPONENT_CONFIG_MAP` (lines 287-288): `"epic_tools": _EpicToolsConfig,` and `"task_tools": _TaskToolsConfig,`

- **Task 2.3**: Edit `platform/api/__init__.py` — Agent: sisyphus-junior
  - Remove line 11: `from api.epics import router as epics_router`
  - Remove line 12: `from api.tasks import router as tasks_router`
  - Remove line 27: `api_router.include_router(epics_router, prefix="/epics", tags=["epics"])`
  - Remove line 28: `api_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])`

- **Task 2.4**: Edit `platform/components/__init__.py` — Agent: sisyphus-junior
  - Remove line 40: `epic_tools,`
  - Remove line 56: `task_tools,`

- **Task 2.5**: Edit `platform/schemas/node.py` — Agent: sisyphus-junior
  - Remove `"epic_tools",` and `"task_tools",` from the `ComponentTypeStr` Literal (lines 21-22)

- **Task 2.6**: Edit `platform/schemas/node_type_defs.py` — Agent: sisyphus-junior
  - Remove lines 281-295: both `register_node_type()` calls for `epic_tools` and `task_tools`

- **Task 2.7**: Edit `platform/services/dsl_compiler.py` — Agent: sisyphus-junior
  - Remove lines 76-77 from `TOOL_TYPE_MAP`: `"epic_tools": "epic_tools"` and `"task_tools": "task_tools"`

- **Task 2.8**: Edit `platform/services/builder.py` — Agent: sisyphus-junior
  - Remove `"epic_tools"` and `"task_tools"` from `SUB_COMPONENT_TYPES` set (line 17)

- **Task 2.9**: Edit `platform/services/topology.py` — Agent: sisyphus-junior
  - Remove `"epic_tools"` and `"task_tools"` from `SUB_COMPONENT_TYPES` set (line 13)

- **Task 2.10**: Edit `platform/services/orchestrator.py` — Agent: hephaestus — **CRITICAL, highest risk**
  - Remove the `_check_budget()` function (lines 1471-1507) entirely
  - Remove the `_sync_task_costs()` function (lines 1651-1737) entirely
  - Remove call sites:
    - Line 452-453: `budget_error = _check_budget(execution_id, state, db)` and the conditional block following it
    - Line 460: `_sync_task_costs(execution_id, db)` call
    - Line 630: `_sync_task_costs(execution_id, db)` call
    - Line 813: `_sync_task_costs(execution_id, db)` call
    - Line 1308: `_sync_task_costs(execution_id, db)` call
  - **Caution**: Read surrounding context carefully. The budget check is inside a larger execution flow — removing it must not break the control flow (e.g., check for `if budget_error:` blocks that may short-circuit). The `_sync_task_costs` calls are in `try/except` or `finally` blocks — ensure the block structure stays valid.

- **Task 2.11**: Edit `platform/components/agent.py` — Agent: sisyphus-junior
  - Remove lines 461-473: the `if task_id:` block that imports `Task` from `models.epic` and links task to child execution
  - Keep the rest of `_create_child_from_interrupt()` intact

> Tasks 2.1-2.9 and 2.11 are simple string removals — can be batched into one or two sisyphus-junior tasks. Task 2.10 (orchestrator) needs hephaestus due to complexity and risk.

---

### Wave 3: Frontend Deletions + Edits (parallel within wave, depends on Wave 1)

- **Task 3.1**: Delete frontend files — Agent: sisyphus-junior
  - Delete `platform/frontend/src/api/epics.ts`
  - Delete `platform/frontend/src/api/tasks.ts`
  - Delete `platform/frontend/src/features/epics/` directory (EpicsPage.tsx, EpicDetailPage.tsx)

- **Task 3.2**: Edit `platform/frontend/src/App.tsx` — Agent: sisyphus-junior
  - Remove lines 15-16: imports of `EpicsPage` and `EpicDetailPage`
  - Remove lines 40-41: routes for `/epics` and `/epics/:epicId`

- **Task 3.3**: Edit `platform/frontend/src/components/layout/AppLayout.tsx` — Agent: sisyphus-junior
  - Remove line 14: `ListTodo` icon import (or just the `ListTodo` from the import)
  - Remove line 28: `{ to: "/epics", icon: ListTodo, label: "Epics" }` nav item

- **Task 3.4**: Edit `platform/frontend/src/types/models.ts` — Agent: sisyphus-junior
  - Remove `epic_tools` and `task_tools` from `ComponentType` union (lines 15-16)
  - Remove `EpicStatus` type (line 127)
  - Remove `TaskStatus` type (line 128)
  - Remove `Epic` interface (lines 130-140)
  - Remove `Task` interface (lines 142-154)
  - Remove `EpicCreate`, `EpicUpdate`, `TaskCreate`, `TaskUpdate` types (lines 156-159)

- **Task 3.5**: Edit `platform/frontend/src/features/workflows/components/WorkflowCanvas.tsx` — Agent: sisyphus-junior
  - Remove from `COMPONENT_COLORS` (lines 72-73): `epic_tools: "#14b8a6"` and `task_tools: "#14b8a6"`
  - Remove from `COMPONENT_ICONS` (line 108 area): `epic_tools: faClipboardList` and `task_tools: faListCheck`
  - Remove from `isTool` set (line 136): `epic_tools`, `task_tools`
  - Remove from `isSubComponent` set (line 137): `epic_tools`, `task_tools`
  - Remove icon imports (`faClipboardList`, `faListCheck`) if no longer used elsewhere

- **Task 3.6**: Edit `platform/frontend/src/features/workflows/components/NodePalette.tsx` — Agent: sisyphus-junior
  - Remove from `ICONS` (lines 36-37): `epic_tools: ClipboardList` and `task_tools: ListChecks`
  - Remove from `NODE_CATEGORIES` "Agent" array (line 67): `epic_tools`, `task_tools`
  - Remove icon imports (`ClipboardList`, `ListChecks`) if no longer used elsewhere

- **Task 3.7**: Edit `platform/frontend/src/lib/wsManager.ts` — Agent: sisyphus-junior
  - Remove line 2: `Epic` from the import type statement
  - Remove lines 180-201: the `case "epic_updated"` and `case "epic_deleted"` and task-related epic handlers

> All frontend tasks can be batched into one sisyphus-junior task since they're straightforward removals.

---

### Wave 4: Fixture/Prompt Cleanup + Verification (depends on Waves 2 & 3)

- **Task 4.1**: Edit `platform/tests/dsl_fixtures/06_error_routing/Step1/topology.yaml` — Agent: sisyphus-junior
  - Remove lines 35-36: `- type: epic_tools` and `- type: task_tools`

- **Task 4.2**: Edit `platform/tests/dsl_fixtures/workflow_generator/fixture.json` — Agent: sisyphus-junior
  - Remove `epic_tools` and `task_tools` from the Scribe and Topology Agent system prompt node catalogs
  - Be careful with JSON syntax (trailing commas, etc.)

- **Task 4.3**: Verification — Agent: sisyphus-junior
  - Run `cd platform && grep -rn "epic_tools\|task_tools\|EpicTools\|TaskTools\|_check_budget\|_sync_task_costs\|epic_helpers" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.json" --include="*.yaml" --exclude-dir=node_modules --exclude-dir=alembic --exclude-dir=.git` — should return zero results
  - Run `grep -rn "from models.epic\|from schemas.epic\|from api.epics\|from api.tasks\|from api.epic_helpers" --include="*.py" --exclude-dir=alembic` — should return zero results

- **Task 4.4**: Run tests — Agent: sisyphus-junior
  - `cd platform && python -m pytest tests/ -v --ignore=tests/test_epics_tasks.py --ignore=tests/test_epic_task_tools.py -x`
  - Verify no import errors or test failures from the removal

- **Task 4.5**: Frontend build check — Agent: sisyphus-junior
  - `cd platform/frontend && npx tsc --noEmit` — verify no TypeScript errors
  - `npm run build` — verify production build succeeds

---

## Recommended Execution Batching

Given the simplicity of most tasks, the actual execution can be compressed:

| Batch | Agent | Tasks |
|---|---|---|
| A (parallel) | sisyphus-junior | Wave 1 (all deletions) + Wave 2 tasks 2.1-2.9, 2.11 (simple edits) + Wave 3 (all frontend) |
| B (parallel with A) | hephaestus | Task 2.10 (orchestrator — complex) |
| C (after A+B) | sisyphus-junior | Wave 4 (fixtures + verification) |

## Risk Flags

1. **Orchestrator surgery (Task 2.10)**: The `_check_budget` and `_sync_task_costs` functions are called from multiple places in the execution flow. Incorrect removal could break the `try/except/finally` block structure or leave dangling references. Must read full context around each call site.
2. **JSON fixture editing (Task 4.2)**: The workflow_generator fixture.json contains long lines with embedded system prompts. Removing `epic_tools`/`task_tools` from comma-separated lists requires care with JSON syntax.
3. **Polymorphic identity orphans**: Existing DB rows with `component_type="epic_tools"` or `"task_tools"` will have no Python class. This is acceptable since we're keeping migration files and these nodes simply won't load. But if any workflow references them, it could cause runtime errors on load. Consider: should we add a data migration or just accept this?
4. **`task_id` parameter in `_create_child_from_interrupt`**: After removing the `if task_id:` block, the `task_id` variable may still be referenced elsewhere in the function. Verify that `task_id` is only used in the removed block.

## QA Scenarios
- [ ] All Python tests pass (excluding deleted test files)
- [ ] `grep` for epic/task references returns zero hits (excluding alembic)
- [ ] TypeScript compilation succeeds (`tsc --noEmit`)
- [ ] Frontend production build succeeds (`npm run build`)
- [ ] App starts without import errors (`python -c "from api import api_router; from components import *; from models import *"`)
- [ ] Workflow editor canvas loads without console errors (manual check)
- [ ] Sidebar no longer shows "Epics" link (manual check)
- [ ] `/api/v1/epics` returns 404 (manual check)
