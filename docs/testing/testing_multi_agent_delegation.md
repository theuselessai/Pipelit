# Manual Testing Plan — Multi-Agent Delegation (Phases 1-6)

Comprehensive testing plan for the full delegation feature: Task Registry, Agent Tools, spawn_and_await, workflow_create, workflow_discover, and Frontend UI.

## Prerequisites

```bash
# Terminal 1: Start Redis (required for RQ workers and WebSocket broadcast)
# IMPORTANT: spawn_and_await without conversation_memory uses RedisSaver, which
# requires redis-stack-server (not plain redis-server) for the RediSearch module.
# Plain redis-server will fail with "unknown command FT._LIST".
#   Install: https://redis.io/docs/getting-started/install-stack/
#   Or on Debian/Ubuntu: curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg && echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/redis.list && sudo apt-get update && sudo apt-get install redis-stack-server
#   Workaround: Enable conversation_memory=true on the agent node to use
#   SqliteSaver instead (works with plain redis-server).
redis-stack-server

# Terminal 2: Start RQ worker
cd platform
source ../.venv/bin/activate
python -m rq worker --with-scheduler

# Terminal 3: Start backend
cd platform
source ../.venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 4: Start frontend dev server
cd platform/frontend
npm run dev

# Terminal 5: Testing shell
export API_KEY="<your-api-key>"
export BASE="http://localhost:8000/api/v1"
```

Ensure you have at least one LLM credential configured (Settings > Credentials) for agent-based tests.

---

# Phase 1: Task Registry — Models & API

## 1.1 Epic CRUD

| # | Step | Expected |
|---|------|----------|
| 1.1.1 | Create epic | Returns 201 with `id` starting with `ep-`, status `planning` |
| 1.1.2 | Get epic by ID | Returns full epic object matching what was created |
| 1.1.3 | Update epic title | Returns updated epic, `updated_at` changed |
| 1.1.4 | Update epic status to `active` | Status changes to `active` |
| 1.1.5 | Get epic again | Confirms update persisted |
| 1.1.6 | List epics (no filters) | Returns `{"items": [...], "total": N}` |
| 1.1.7 | Delete epic | Returns 204 |
| 1.1.8 | Get deleted epic | Returns 404 |

```bash
# 1.1.1 Create
EPIC=$(curl -s -X POST "$BASE/epics/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Epic", "description": "Testing CRUD", "tags": ["test"], "priority": 2, "budget_usd": 10.00}')
echo "$EPIC" | jq .
EPIC_ID=$(echo "$EPIC" | jq -r .id)

# 1.1.2 Get
curl -s "$BASE/epics/$EPIC_ID/" -H "Authorization: Bearer $API_KEY" | jq .

# 1.1.3 Update title
curl -s -X PATCH "$BASE/epics/$EPIC_ID/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated Test Epic"}' | jq .title

# 1.1.4 Update status
curl -s -X PATCH "$BASE/epics/$EPIC_ID/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}' | jq .status

# 1.1.5 Get again
curl -s "$BASE/epics/$EPIC_ID/" -H "Authorization: Bearer $API_KEY" | jq '{title, status}'

# 1.1.6 List
curl -s "$BASE/epics/" -H "Authorization: Bearer $API_KEY" | jq '{total, count: (.items | length)}'
```

## 1.2 Task CRUD

| # | Step | Expected |
|---|------|----------|
| 1.2.1 | Create task (no dependencies) | Returns 201, status `pending`, `id` starts with `tk-` |
| 1.2.2 | Create task with `depends_on` referencing incomplete task | Status is `blocked` |
| 1.2.3 | Get task by ID | Returns full task object |
| 1.2.4 | Update task status to `completed` | Status changes to `completed` |
| 1.2.5 | Check blocked task | Previously blocked task may now be `pending` if all deps completed |
| 1.2.6 | List tasks filtered by epic | Returns only tasks for that epic |
| 1.2.7 | Delete task | Returns 204 |

```bash
# 1.2.1 Create task
TASK1=$(curl -s -X POST "$BASE/tasks/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"epic_id\": \"$EPIC_ID\", \"title\": \"First task\", \"description\": \"Do something\", \"priority\": 1}")
echo "$TASK1" | jq '{id, status}'
TASK1_ID=$(echo "$TASK1" | jq -r .id)

# 1.2.2 Create dependent task
TASK2=$(curl -s -X POST "$BASE/tasks/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"epic_id\": \"$EPIC_ID\", \"title\": \"Second task (depends on first)\", \"depends_on\": [\"$TASK1_ID\"]}")
echo "$TASK2" | jq '{id, status, depends_on}'
TASK2_ID=$(echo "$TASK2" | jq -r .id)
# Expected: status = "blocked"

# 1.2.3 Get task
curl -s "$BASE/tasks/$TASK1_ID/" -H "Authorization: Bearer $API_KEY" | jq .

# 1.2.4 Complete first task
curl -s -X PATCH "$BASE/tasks/$TASK1_ID/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed", "result_summary": "Done"}' | jq .status

# 1.2.5 Check if blocked task is now pending
curl -s "$BASE/tasks/$TASK2_ID/" -H "Authorization: Bearer $API_KEY" | jq .status
# Expected: "pending" (auto-unblocked when all dependencies are completed)

# 1.2.6 List tasks for epic
curl -s "$BASE/epics/$EPIC_ID/tasks/" -H "Authorization: Bearer $API_KEY" | jq '{total, items: [.items[] | {id, title, status}]}'
```

## 1.3 Epic Progress Sync

| # | Step | Expected |
|---|------|----------|
| 1.3.1 | Check epic after task completion | `completed_tasks` incremented, `total_tasks` correct |
| 1.3.2 | Fail a task, check epic | `failed_tasks` incremented |
| 1.3.3 | Delete a task, check epic | `total_tasks` decremented |

```bash
# 1.3.1 Check epic progress
curl -s "$BASE/epics/$EPIC_ID/" -H "Authorization: Bearer $API_KEY" | jq '{total_tasks, completed_tasks, failed_tasks}'
```

## 1.4 Pagination & Filtering

| # | Step | Expected |
|---|------|----------|
| 1.4.1 | `GET /epics/?limit=1` | Returns 1 item, `total` shows full count |
| 1.4.2 | `GET /epics/?offset=1&limit=1` | Returns second item |
| 1.4.3 | `GET /epics/?status=active` | Only active epics |
| 1.4.4 | `GET /epics/?tags=test` | Only epics with "test" tag |
| 1.4.5 | `GET /tasks/?epic_id=<id>` | Only tasks for that epic |
| 1.4.6 | `GET /tasks/?status=pending` | Only pending tasks |

```bash
# 1.4.1
curl -s "$BASE/epics/?limit=1" -H "Authorization: Bearer $API_KEY" | jq '{total, count: (.items | length)}'

# 1.4.3
curl -s "$BASE/epics/?status=active" -H "Authorization: Bearer $API_KEY" | jq '.items | length'

# 1.4.4
curl -s "$BASE/epics/?tags=test" -H "Authorization: Bearer $API_KEY" | jq '.items | length'
```

## 1.5 Batch Delete

| # | Step | Expected |
|---|------|----------|
| 1.5.1 | Create 3 throwaway epics | All return 201 |
| 1.5.2 | Batch delete 2 of them | Returns 204, only 1 remains |
| 1.5.3 | Batch delete tasks | Returns 204, epic progress updated |

```bash
# Create throwaway epics
E1=$(curl -s -X POST "$BASE/epics/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"title":"Throwaway 1"}' | jq -r .id)
E2=$(curl -s -X POST "$BASE/epics/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"title":"Throwaway 2"}' | jq -r .id)
E3=$(curl -s -X POST "$BASE/epics/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"title":"Throwaway 3"}' | jq -r .id)

# Batch delete
curl -s -X POST "$BASE/epics/batch-delete/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"epic_ids\": [\"$E1\", \"$E2\"]}" -w "\nHTTP %{http_code}\n"

# Verify E3 still exists
curl -s "$BASE/epics/$E3/" -H "Authorization: Bearer $API_KEY" | jq .title
```

## 1.6 Epic Cancellation Cascade

| # | Step | Expected |
|---|------|----------|
| 1.6.1 | Create epic with pending/blocked tasks | Tasks created normally |
| 1.6.2 | Cancel the epic | Epic status = `cancelled` |
| 1.6.3 | Check all tasks | Pending/blocked tasks also cancelled, completed tasks unchanged |

```bash
# Create epic + tasks
CANCEL_EPIC=$(curl -s -X POST "$BASE/epics/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"title":"Cancel Test"}' | jq -r .id)
curl -s -X PATCH "$BASE/epics/$CANCEL_EPIC/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"status":"active"}' > /dev/null

CT1=$(curl -s -X POST "$BASE/tasks/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "{\"epic_id\":\"$CANCEL_EPIC\",\"title\":\"Will be cancelled\"}" | jq -r .id)
CT2=$(curl -s -X POST "$BASE/tasks/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "{\"epic_id\":\"$CANCEL_EPIC\",\"title\":\"Already done\"}" | jq -r .id)

# Complete one task first
curl -s -X PATCH "$BASE/tasks/$CT2/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"status":"completed"}' > /dev/null

# Cancel the epic
curl -s -X PATCH "$BASE/epics/$CANCEL_EPIC/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"status":"cancelled"}' | jq .status

# Check tasks
curl -s "$BASE/epics/$CANCEL_EPIC/tasks/" -H "Authorization: Bearer $API_KEY" | jq '.items[] | {title, status}'
# Expected: "Will be cancelled" → cancelled, "Already done" → completed
```

## 1.7 Auth & Security

| # | Step | Expected |
|---|------|----------|
| 1.7.1 | Request without auth header | 403 Forbidden |
| 1.7.2 | Request with invalid token | 401 Unauthorized |
| 1.7.3 | Create epic as user A, access as user B | Should only see own epics (scoped to `user_profile_id`) |

```bash
# No auth
curl -s "$BASE/epics/" -w "\nHTTP %{http_code}\n"

# Invalid token
curl -s "$BASE/epics/" -H "Authorization: Bearer invalid-token" -w "\nHTTP %{http_code}\n"
```

---

# Phase 2: Registry Agent Tools

These tests require a workflow with an agent node that has `epic_tools` and/or `task_tools` connected as tool sub-components. Build the workflow in the UI first, then trigger it.

## 2.1 Setup: Create a Delegation Agent Workflow

1. Create a new workflow (e.g., slug: `delegation-test`)
2. Add a `trigger_chat` node
3. Add an `agent` node, connect trigger → agent
4. Add an `ai_model` node, connect to agent's model handle
5. Configure the ai_model with a working LLM credential
6. Add an `epic_tools` node, connect to agent's tools handle
7. Add a `task_tools` node, connect to agent's tools handle
8. Set the agent's system prompt:
```
You are a project manager. Use your epic and task tools to help the user manage work.
When asked to create an epic, use create_epic. When asked about status, use epic_status.
When asked to create tasks, use create_task. Always confirm what you did.
```

## 2.2 Epic Tools via Agent

Test via the chat interface (`/workflows/delegation-test` → Chat panel):

| # | Prompt | Expected |
|---|--------|----------|
| 2.2.1 | "Create an epic called 'API Redesign' with priority 1 and description 'Redesign REST API'" | Agent calls `create_epic`, responds with epic ID and confirmation |
| 2.2.2 | "What's the status of that epic?" | Agent calls `epic_status`, shows planning status, 0 tasks |
| 2.2.3 | "Update its priority to 3" | Agent calls `update_epic`, confirms change |
| 2.2.4 | "Search for epics about API" | Agent calls `search_epics`, returns matching results |

Verify via API after each step:
```bash
curl -s "$BASE/epics/" -H "Authorization: Bearer $API_KEY" | jq '.items[] | select(.title | test("API")) | {id, title, status, priority}'
```

## 2.3 Task Tools via Agent

| # | Prompt | Expected |
|---|--------|----------|
| 2.3.1 | "Create a task in that epic: 'Design new endpoints'" | Agent calls `create_task`, returns task ID, status pending |
| 2.3.2 | "Create another task 'Implement endpoints' that depends on the first" | Agent calls `create_task` with `depends_on`, status should be blocked |
| 2.3.3 | "List all tasks in the epic" | Agent calls `list_tasks`, shows both tasks with statuses |
| 2.3.4 | "Mark the design task as completed" | Agent calls `update_task`, status changes |
| 2.3.5 | "Cancel the implementation task" | Agent calls `cancel_task`, confirms cancellation |

## 2.4 Tool Error Handling

| # | Prompt | Expected |
|---|--------|----------|
| 2.4.1 | "Get status of epic ep-nonexistent" | Agent gets error from `epic_status`, communicates "not found" |
| 2.4.2 | "Create a task in epic ep-nonexistent" | Agent gets error from `create_task`, communicates failure |

## 2.5 Verify on Canvas

| # | Step | Expected |
|---|------|----------|
| 2.5.1 | Execute workflow, watch canvas | `epic_tools` / `task_tools` nodes show running/success badges when agent invokes them |
| 2.5.2 | Check execution logs | Logs show tool invocations with inputs/outputs |

---

# Phase 3: spawn_and_await

Requires two workflows: a parent (with agent + spawn_and_await tool) and a child (with trigger_workflow).

## 3.1 Setup: Create Child Workflow

1. Create workflow slug: `child-worker`
2. Add `trigger_workflow` node
3. Add an `agent` or `code` node that processes the input and returns output
4. Connect trigger → processing node
5. Validate the workflow works standalone:

```bash
# Test child directly
curl -s -X POST "$BASE/workflows/child-worker/execute/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "test input", "trigger_node_id": "<trigger_node_id>"}' | jq .
```

## 3.2 Setup: Create Parent Workflow

1. Create workflow slug: `parent-delegator`
2. Add `trigger_chat` node
3. Add `agent` node, connect trigger → agent
4. Add `ai_model` node, connect to agent's model handle
5. Add `spawn_and_await` node, connect to agent's tools handle
6. Set agent system prompt:
```
You can delegate work to child workflows using the spawn_and_await tool.
When asked to delegate, call spawn_and_await with workflow_slug="child-worker" and appropriate input_text.
Report the result back to the user.
```

## 3.3 Spawn & Await Execution

| # | Step | Expected |
|---|------|----------|
| 3.3.1 | Chat: "Delegate 'analyze this data' to the child worker" | Agent calls `spawn_and_await` |
| 3.3.2 | Watch execution list | Parent execution shows `running`, child execution appears as separate entry |
| 3.3.3 | Watch child complete | Child execution completes with result |
| 3.3.4 | Check parent resume | Parent agent receives child result, responds to user with it |
| 3.3.5 | Check parent execution | Status = `completed`, logs show interrupt + resume |

## 3.4 Spawn with Task Linking

| # | Step | Expected |
|---|------|----------|
| 3.4.1 | Create an epic and task via API first | Task created with status `pending` |
| 3.4.2 | Call spawn_and_await with `task_id` param | Child spawned |
| 3.4.3 | Check task during child execution | `task.execution_id` set, `task.status` = `running` |
| 3.4.4 | After child completes | `task.status` = `completed`, `task.duration_ms` > 0, `task.result_summary` set |

## 3.5 Spawn Failure Handling

| # | Step | Expected |
|---|------|----------|
| 3.5.1 | Call spawn_and_await with invalid workflow slug | Agent receives error, communicates failure |
| 3.5.2 | Child workflow that fails | Parent agent receives error result, can react |

## 3.6 Checkpointer Verification

| # | Step | Expected |
|---|------|----------|
| 3.6.1 | Agent with `conversation_memory=ON` using spawn_and_await | Uses SqliteSaver, conversation persists after restart |
| 3.6.2 | Agent with `conversation_memory=OFF` using spawn_and_await | Uses Redis checkpointer, interrupt/resume works but no conversation persistence |
| 3.6.3 | Agent without spawn_and_await or conversation_memory | No checkpointer, one-shot execution |

---

# Phase 4: workflow_create (DSL Compiler)

Requires a workflow with an agent node that has `workflow_create` connected as a tool.

## 4.1 Setup: Create a Builder Agent Workflow

1. Create workflow slug: `workflow-builder`
2. Add `trigger_chat`, `agent`, `ai_model`, `workflow_create` nodes
3. Wire: trigger → agent, ai_model → agent (model handle), workflow_create → agent (tools handle)
4. System prompt:
```
You create workflows from YAML DSL specifications.
When asked to create a workflow, generate the YAML and call workflow_create.
Always use trigger type "webhook" unless told otherwise.
```

## 4.2 Create Mode — Simple Workflow

| # | Prompt | Expected |
|---|--------|----------|
| 4.2.1 | "Create a simple workflow called 'hello-world' with a code step that returns 'Hello World'" | Agent generates YAML DSL, calls `workflow_create` |
| 4.2.2 | Check response | Returns `workflow_id`, `slug`, `node_count`, `edge_count`, `mode: "create"` |
| 4.2.3 | Navigate to created workflow in UI | Workflow visible on dashboard, nodes on canvas |

Verify via API:
```bash
curl -s "$BASE/workflows/hello-world/" -H "Authorization: Bearer $API_KEY" | jq '{name, slug, node_count, edge_count}'
```

## 4.3 Create Mode — Agent Workflow with Tools

| # | Step | Expected |
|---|------|----------|
| 4.3.1 | Ask agent to create a workflow with an agent step that has http_request and calculator tools | YAML has agent step with inline tools |
| 4.3.2 | Check created workflow | Agent node exists with tool nodes connected via tool edges |
| 4.3.3 | Check ai_model resolution | ai_model node created with correct credential |

## 4.4 Create Mode — DSL via curl

Test the DSL compiler directly by providing YAML to the tool:

```bash
# Create a workflow with a workflow_create-equipped agent
# Or test the compiler service directly by creating a workflow via agent chat
# Example YAML the agent should generate:

# name: data-processor
# trigger: webhook
# steps:
#   - id: extract
#     type: code
#     config:
#       code: |
#         output = {"data": trigger.text.upper()}
#   - id: respond
#     type: code
#     config:
#       code: |
#         output = {"result": f"Processed: {extract.output}"}
```

## 4.5 Fork & Patch Mode

| # | Step | Expected |
|---|------|----------|
| 4.5.1 | Ask: "Fork the hello-world workflow, change the code to return 'Goodbye World'" | Agent generates fork YAML with `based_on: hello-world` and `update_prompt` patch |
| 4.5.2 | Check response | Returns new slug, `mode: "fork"` |
| 4.5.3 | Check forked workflow | New workflow exists with modified code step |
| 4.5.4 | Original unchanged | `hello-world` still has original code |

## 4.6 DSL Validation Errors

| # | Step | Expected |
|---|------|----------|
| 4.6.1 | YAML missing `name` field | Error: validation failure |
| 4.6.2 | YAML missing `steps` field | Error: validation failure |
| 4.6.3 | Step with unknown `type` | Error: unknown step type |
| 4.6.4 | Fork with nonexistent `based_on` slug | Error: workflow not found |

## 4.7 Model Resolution

| # | Step | Expected |
|---|------|----------|
| 4.7.1 | Agent step with `model.inherit: true` | Created agent inherits parent's LLM config |
| 4.7.2 | Agent step with `model.discover: true` | Auto-selects best available model |
| 4.7.3 | Agent step with `model.capability: "gpt-4"` | Matches credential with gpt-4 substring |
| 4.7.4 | Agent step with `model.credential_id: <N>` | Uses that exact credential |

---

# Phase 5: workflow_discover

Requires a workflow with an agent node that has `workflow_discover` connected as a tool.

## 5.1 Setup

1. Ensure multiple workflows exist with different capabilities (triggers, tools, node types)
2. Create workflow slug: `discovery-agent`
3. Add `trigger_chat`, `agent`, `ai_model`, `workflow_discover` nodes
4. Wire them up
5. System prompt:
```
You help find existing workflows. Use workflow_discover to search by requirements.
Present the results clearly, including match scores and recommendations.
```

## 5.2 Discovery by Requirements

| # | Prompt | Expected |
|---|--------|----------|
| 5.2.1 | "Find workflows that use webhooks and HTTP requests" | Agent calls `workflow_discover` with `{"triggers": ["webhook"], "tools": ["http_request"]}` |
| 5.2.2 | Check results | Returns matches with `match_score`, `recommendation`, `has_capabilities`, `missing_capabilities` |
| 5.2.3 | "Find workflows tagged 'test'" | Searches by tags |

## 5.3 Recommendation Tiers

| # | Step | Expected |
|---|------|----------|
| 5.3.1 | Search for capabilities matching an existing workflow exactly | `recommendation: "reuse"`, score >= 0.95 |
| 5.3.2 | Search for capabilities partially matching | `recommendation: "fork_and_patch"`, score 0.50-0.95 |
| 5.3.3 | Search for capabilities no workflow has | `recommendation: "create_new"`, score < 0.50 or no results |

## 5.4 Gap Analysis

| # | Step | Expected |
|---|------|----------|
| 5.4.1 | Check `has_capabilities` in result | Lists what the workflow CAN do |
| 5.4.2 | Check `missing_capabilities` | Lists what's required but missing |
| 5.4.3 | Check `extra_capabilities` | Lists what's present but not required |

## 5.5 Edge Cases

| # | Step | Expected |
|---|------|----------|
| 5.5.1 | Search with empty requirements `{}` | Returns workflows sorted by general score |
| 5.5.2 | Search with `limit: 1` | Returns only 1 result |
| 5.5.3 | Discover from within a workflow | That workflow excluded from results (no self-match) |

---

# Phase 6: Frontend UI

## 6.1 Sidebar Navigation

| # | Step | Expected |
|---|------|----------|
| 6.1.1 | Open the app, look at sidebar | "Epics" nav item with ListTodo icon, between "Executions" and "Memories" |
| 6.1.2 | Collapse sidebar | Epics icon visible, label hidden |
| 6.1.3 | Click Epics | Navigates to `/epics`, nav item highlighted |

## 6.2 Epics Page — Empty State

| # | Step | Expected |
|---|------|----------|
| 6.2.1 | Navigate to `/epics` with no epics | "No epics found." message, status filter shows "All" |

## 6.3 Epics Page — With Data

Use the epics/tasks created in Phase 1 tests, or seed data:

```bash
# Quick seed: planning + active + completed + failed epics
SEED_EP1=$(curl -s -X POST "$BASE/epics/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"title":"Planning Epic","tags":["seed"],"priority":1}' | jq -r .id)

SEED_EP2=$(curl -s -X POST "$BASE/epics/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"title":"Active Epic","tags":["seed"],"priority":2}' | jq -r .id)
curl -s -X PATCH "$BASE/epics/$SEED_EP2/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"status":"active"}' > /dev/null

# Add tasks to active epic
curl -s -X POST "$BASE/tasks/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "{\"epic_id\":\"$SEED_EP2\",\"title\":\"Task A\",\"description\":\"First task\"}" > /dev/null
curl -s -X POST "$BASE/tasks/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "{\"epic_id\":\"$SEED_EP2\",\"title\":\"Task B\",\"description\":\"Second task\"}" > /dev/null

SEED_EP3=$(curl -s -X POST "$BASE/epics/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"title":"Completed Epic","tags":["seed"],"priority":3}' | jq -r .id)
curl -s -X PATCH "$BASE/epics/$SEED_EP3/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"status":"completed","result_summary":"All done successfully"}' > /dev/null

SEED_EP4=$(curl -s -X POST "$BASE/epics/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"title":"Failed Epic","tags":["seed"],"priority":1,"budget_usd":5.00}' | jq -r .id)
curl -s -X PATCH "$BASE/epics/$SEED_EP4/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d '{"status":"failed","result_summary":"Out of budget"}' > /dev/null
```

| # | Step | Expected |
|---|------|----------|
| 6.3.1 | Navigate to `/epics` | Table shows all epics |
| 6.3.2 | Check columns | Title, Status (colored badge), Progress (X/Y tasks), Priority, Created |
| 6.3.3 | Status badge colors | planning=yellow, active=blue, completed=green, failed=red, paused=orange, cancelled=gray |
| 6.3.4 | Progress column | Epic with tasks shows "2/2 tasks", empty epic shows "0/0 tasks" |

## 6.4 Epics Page — Status Filter

| # | Step | Expected |
|---|------|----------|
| 6.4.1 | Select "active" | Only active epics shown, page resets to 1, selection cleared |
| 6.4.2 | Select "completed" | Only completed epics |
| 6.4.3 | Select "All" | All epics visible again |

## 6.5 Epics Page — Selection & Batch Delete

| # | Step | Expected |
|---|------|----------|
| 6.5.1 | Click checkbox on one row | "Delete Selected (1)" button appears |
| 6.5.2 | Click header checkbox | All visible epics selected |
| 6.5.3 | Change status filter while selected | Selection cleared |
| 6.5.4 | Select one, click Delete Selected | Confirmation dialog with Cancel/Delete |
| 6.5.5 | Click Cancel | Dialog closes, selection preserved |
| 6.5.6 | Click Delete | Epic deleted, table refreshes, selection cleared |

## 6.6 Epic Detail Page

| # | Step | Expected |
|---|------|----------|
| 6.6.1 | Click an epic row | Navigates to `/epics/{id}`, title and ID shown |
| 6.6.2 | Summary cards | Status (badge), Progress (X/Y tasks), Budget, Cost |
| 6.6.3 | Description | Visible if non-empty |
| 6.6.4 | Completed epic | "Result Summary" card shown |
| 6.6.5 | Failed epic | "Error" card with red border |

## 6.7 Task Table on Epic Detail

| # | Step | Expected |
|---|------|----------|
| 6.7.1 | View epic with tasks | Columns: chevron, checkbox, Title, Status, Workflow, Duration, Created |
| 6.7.2 | Task badge colors | pending=yellow, blocked=orange, running=blue, completed=green, failed=red, cancelled=gray |
| 6.7.3 | Click task with description | Row expands showing description, dependencies, result/error |
| 6.7.4 | Click expanded row again | Collapses |
| 6.7.5 | Task without details | No chevron, not expandable |

## 6.8 WebSocket Live Updates

Open epic detail in browser, mutate via curl in terminal:

| # | Step | Expected |
|---|------|----------|
| 6.8.1 | Create task via curl | Task appears in table without refresh |
| 6.8.2 | Update epic status via curl | Status badge updates live |
| 6.8.3 | Delete task via curl | Task disappears, progress updates |
| 6.8.4 | Update task status via curl | Badge color changes live |

```bash
# While viewing epic detail for $SEED_EP2:
curl -s -X POST "$BASE/tasks/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d "{\"epic_id\":\"$SEED_EP2\",\"title\":\"WS test task\"}" | jq .id

curl -s -X PATCH "$BASE/epics/$SEED_EP2/" -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"status":"paused"}' | jq .status
```

## 6.9 Edge Cases

| # | Step | Expected |
|---|------|----------|
| 6.9.1 | Navigate to `/epics/nonexistent-id` | Shows loading, then empty/error state |
| 6.9.2 | Logout, navigate to `/epics` | Redirected to login |
| 6.9.3 | Rapid pagination clicks | No crashes, selections clear |

---

# End-to-End Integration

## E2E.1 Full Delegation Cycle

This tests the complete flow: agent creates epic/tasks, discovers workflows, creates child workflows, delegates work, and tracks progress.

**Setup:** Create a workflow with ALL delegation tools:
- `trigger_chat`, `agent`, `ai_model`
- `epic_tools`, `task_tools`, `spawn_and_await`, `workflow_create`, `workflow_discover`
- System prompt explaining all capabilities

| # | Step | Expected |
|---|------|----------|
| E2E.1.1 | "Create an epic called 'Data Pipeline' with 2 tasks: 'fetch data' and 'process data'" | Agent creates epic + 2 tasks, reports IDs |
| E2E.1.2 | "Check if there's a workflow that can fetch data via HTTP" | Agent calls `workflow_discover`, reports findings |
| E2E.1.3 | "Create a simple workflow to fetch data from a URL" | Agent calls `workflow_create` with DSL |
| E2E.1.4 | "Run the fetch workflow for the first task" | Agent calls `spawn_and_await`, child executes |
| E2E.1.5 | "What's the epic status now?" | Agent calls `epic_status`, shows updated progress |
| E2E.1.6 | Check `/epics` in UI | Epic visible with updated task counts |
| E2E.1.7 | Check execution list | Both parent and child executions visible |

## E2E.2 Cost Tracking

| # | Step | Expected |
|---|------|----------|
| E2E.2.1 | After spawn_and_await completes | Task's `duration_ms` > 0 |
| E2E.2.2 | Check epic progress | `completed_tasks` incremented |
| E2E.2.3 | Check task result | `result_summary` populated from child output |

---

# Cleanup

```bash
# Delete all seed epics
EPIC_IDS_JSON=$(curl -s "$BASE/epics/?tags=seed" -H "Authorization: Bearer $API_KEY" | jq '[.items[].id]')
curl -s -X POST "$BASE/epics/batch-delete/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"epic_ids\": $EPIC_IDS_JSON}" -w "\nHTTP %{http_code}\n"

# Delete test workflows
for slug in hello-world child-worker parent-delegator workflow-builder discovery-agent delegation-test; do
  curl -s -X DELETE "$BASE/workflows/$slug/" -H "Authorization: Bearer $API_KEY" -w "$slug: HTTP %{http_code}\n"
done
```
