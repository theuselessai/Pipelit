# Tool Schemas & Component Specs — Multi-Agent Delegation

## Date: 2025-02-09
## Prerequisites: `multiagent_delegation_architecture.md`, `task_registry_design.md`

---

## Overview

11 new components across 3 categories. Each follows the existing pattern:

1. **Component file** (`platform/components/<name>.py`) — `@register("<type>")` factory returning a LangChain `@tool`
2. **Polymorphic identity** (`platform/models/node.py`) — `_<Name>Config` class + entry in `COMPONENT_TYPE_MAP`
3. **Node type registration** (`platform/schemas/node_type_defs.py`) — `register_node_type(NodeTypeSpec(...))` with ports and config_schema
4. **Import** (`platform/components/__init__.py`) — add to the import block

---

## 1. Task Registry Tools (7 components)

### 1.1 `epic_create`

**File:** `platform/components/epic_create.py`

```python
@register("epic_create")
def epic_create_factory(node):
    extra = node.component_config.extra_config or {}

    @tool
    def create_epic(
        title: str,
        description: str = "",
        tags: str = "[]",
        budget_tokens: int = 0,
        budget_usd: float = 0.0,
        priority: int = 2,
    ) -> str:
        """Create a tracked epic (top-level goal) in the task registry.

        An epic groups related tasks and tracks overall progress, cost, and budget.
        Use for multi-step goals that will involve multiple tool calls or subworkflows.

        Args:
            title: Short name for the goal (e.g., "Join Moltbook")
            description: Detailed goal, constraints, acceptance criteria
            tags: JSON array of tags for discovery (e.g., '["webhook", "onboarding"]')
            budget_tokens: Token ceiling (0 = unlimited)
            budget_usd: USD ceiling (0.0 = unlimited)
            priority: 1=critical, 2=high, 3=medium, 4=low

        Returns:
            JSON with epic_id and status.
        """
        # Creates Epic via SessionLocal, resolves user_profile_id from execution state
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="epic_create",
    display_name="Create Epic",
    description="Create a tracked epic (top-level goal) in the task registry",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON with epic_id and status")],
))
```

**Polymorphic identity:**

```python
class _EpicCreateConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "epic_create"}

# In COMPONENT_TYPE_MAP:
"epic_create": ToolComponentConfig,
```

---

### 1.2 `epic_status`

**File:** `platform/components/epic_status.py`

```python
@register("epic_status")
def epic_status_factory(node):

    @tool
    def epic_status(epic_id: str) -> str:
        """Get progress, cost, and task breakdown for an epic.

        Args:
            epic_id: The epic ID (e.g., "ep_01JKXYZ")

        Returns:
            JSON with epic details, progress counts, cost breakdown, and task list.
            {
                "epic_id": "ep_01JKXYZ",
                "title": "Join Moltbook",
                "status": "active",
                "priority": 2,
                "progress": {"total": 3, "completed": 1, "running": 1, "failed": 0, "blocked": 0, "pending": 1},
                "cost": {"spent_tokens": 15000, "spent_usd": 0.45, "budget_tokens": null, "budget_usd": null},
                "tasks": [{"id": "tk_01JKABC", "title": "...", "status": "completed", "duration_ms": 1200}]
            }
        """
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="epic_status",
    display_name="Epic Status",
    description="Get progress, cost, and task breakdown for an epic",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON with epic details and progress")],
))
```

**Polymorphic identity:**

```python
class _EpicStatusConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "epic_status"}

"epic_status": ToolComponentConfig,
```

---

### 1.3 `epic_search`

**File:** `platform/components/epic_search.py`

```python
@register("epic_search")
def epic_search_factory(node):

    @tool
    def search_epics(
        query: str = "",
        tags: str = "[]",
        status: str = "",
    ) -> str:
        """Search past epics by goal description and tags.

        Key tool for reuse — find what worked before instead of starting from scratch.

        Args:
            query: Natural language search (matched against title and description via LIKE)
            tags: JSON array of tags to filter by (e.g., '["webhook"]')
            status: Filter by status (planning, active, completed, failed, cancelled)

        Returns:
            JSON array of matching epics with success metrics:
            [{"id": "ep_...", "title": "...", "tags": [...], "status": "completed",
              "success_rate": 0.95, "avg_cost_usd": 0.12, "total_tasks": 5}]
        """
        # Query epics table with LIKE on title/description, tag overlap, status filter
        # Compute success_rate = completed_tasks / total_tasks per epic
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="epic_search",
    display_name="Search Epics",
    description="Search past epics by goal description and tags — find reusable patterns",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON array of matching epics with metrics")],
))
```

**Polymorphic identity:**

```python
class _EpicSearchConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "epic_search"}

"epic_search": ToolComponentConfig,
```

---

### 1.4 `task_create`

**File:** `platform/components/task_create.py`

```python
@register("task_create")
def task_create_factory(node):

    @tool
    def create_task(
        epic_id: str,
        title: str,
        description: str = "",
        tags: str = "[]",
        depends_on: str = "[]",
        priority: int = 0,
        workflow_slug: str = "",
        estimated_tokens: int = 0,
        requirements: str = "{}",
    ) -> str:
        """Create a task under an epic with optional dependencies and requirements.

        Tasks are the unit of delegation. Each maps to one workflow execution
        (via spawn_and_await) or one inline tool call sequence.

        Args:
            epic_id: Parent epic ID
            title: What this task should accomplish
            description: Detailed instructions or constraints
            tags: JSON array of tags (e.g., '["api-call", "registration"]')
            depends_on: JSON array of task IDs that must complete first (e.g., '["tk_01JKDEF"]')
            priority: 1-4 (0 = inherit from epic)
            workflow_slug: Pre-assigned workflow to execute (empty = inline or create later)
            estimated_tokens: Token estimate for budget checking (0 = skip check)
            requirements: JSON object of capability requirements for the workflow:
                '{"model": "gpt-4", "tools": ["code", "web_search"],
                  "trigger": "webhook", "memory": true}'
                Used by workflow_discover for gap-analysis matching and
                by workflow_create for resource resolution.

        Returns:
            JSON with task_id and effective status ("pending" or "blocked").
        """
        # Creates Task, checks budget via check_budget(), resolves depends_on → blocked status
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="task_create",
    display_name="Create Task",
    description="Create a task under an epic with optional dependencies and workflow assignment",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON with task_id and status")],
))
```

**Polymorphic identity:**

```python
class _TaskCreateConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "task_create"}

"task_create": ToolComponentConfig,
```

---

### 1.5 `task_list`

**File:** `platform/components/task_list.py`

```python
@register("task_list")
def task_list_factory(node):

    @tool
    def list_tasks(
        epic_id: str = "",
        status: str = "",
        tags: str = "[]",
    ) -> str:
        """List tasks filtered by epic, status, or tags.

        Args:
            epic_id: Filter by parent epic (empty = all epics)
            status: Filter by status (pending, blocked, running, completed, failed, cancelled)
            tags: JSON array of tags to filter by

        Returns:
            JSON array of tasks:
            [{"id": "tk_...", "title": "...", "status": "running", "epic_id": "ep_...",
              "depends_on": [...], "workflow_slug": "...", "duration_ms": 0, "actual_usd": 0.0}]
        """
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="task_list",
    display_name="List Tasks",
    description="List tasks filtered by epic, status, or tags",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON array of tasks")],
))
```

**Polymorphic identity:**

```python
class _TaskListConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "task_list"}

"task_list": ToolComponentConfig,
```

---

### 1.6 `task_update`

**File:** `platform/components/task_update.py`

```python
@register("task_update")
def task_update_factory(node):

    @tool
    def update_task(
        task_id: str,
        status: str = "",
        result_summary: str = "",
        error_message: str = "",
        notes: str = "",
    ) -> str:
        """Update task status, result, or add notes.

        Call this after completing an inline task, or to record progress/errors.

        Args:
            task_id: The task ID to update
            status: New status (pending, running, completed, failed, cancelled). Empty = no change.
            result_summary: What the task produced (set on completion)
            error_message: Why the task failed (set on failure)
            notes: Append a note (e.g., "Switched to fallback API endpoint")

        Returns:
            JSON with task_id and updated status.
        """
        # Updates Task fields, appends to notes[] with timestamp, syncs epic costs
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="task_update",
    display_name="Update Task",
    description="Update task status, result summary, or add notes",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON with task_id and status")],
))
```

**Polymorphic identity:**

```python
class _TaskUpdateConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "task_update"}

"task_update": ToolComponentConfig,
```

---

### 1.7 `task_cancel`

**File:** `platform/components/task_cancel.py`

```python
@register("task_cancel")
def task_cancel_factory(node):

    @tool
    def cancel_task(
        task_id: str,
        reason: str = "",
    ) -> str:
        """Cancel a task and its running workflow execution.

        Use when a sibling task failed and this task is no longer relevant,
        or when the epic is being abandoned.

        Args:
            task_id: The task to cancel
            reason: Why the task is being cancelled

        Returns:
            JSON with task_id, status "cancelled", and whether the execution was also cancelled.
        """
        # Sets task.status = "cancelled", appends reason to notes
        # If task.execution_id exists and execution is running: POST /executions/{id}/cancel/
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="task_cancel",
    display_name="Cancel Task",
    description="Cancel a task and its running workflow execution",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON with cancellation result")],
))
```

**Polymorphic identity:**

```python
class _TaskCancelConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "task_cancel"}

"task_cancel": ToolComponentConfig,
```

---

## 2. Workflow Management Tools (2 components)

### 2.1 `workflow_create_tool`

**File:** `platform/components/workflow_create_tool.py`

Accepts a **YAML-based Workflow DSL** and compiles it to Pipelit API calls. Supports two modes: create from scratch (full DSL) and fork+patch (`based_on` + `patches`). See `workflow_dsl_spec.md` for the full DSL specification.

```python
@register("workflow_create_tool")
def workflow_create_tool_factory(node):
    extra = node.component_config.extra_config or {}
    api_base_url = extra.get("api_base_url", "http://localhost:8000")

    # Capture workflow context for credential inheritance
    tool_workflow_id = node.workflow_id
    tool_node_id = node.node_id

    @tool
    def create_workflow(
        dsl: str,
        tags: str = "",
    ) -> str:
        """Create a new workflow from a YAML DSL specification.

        Two modes:
        1. Create from scratch — provide full DSL with trigger, steps, model, tools
        2. Fork and patch — provide `based_on: <slug>` + `patches` to modify an existing workflow

        The DSL handles resource resolution automatically:
        - `model: {inherit: true}` copies the parent agent's model/credential
        - `model: {capability: "gpt-4"}` finds a credential providing that model
        - Tool configs with `inherit` copy from the parent agent's matching tool

        Args:
            dsl: YAML workflow definition. Examples:

                Create from scratch:
                ```yaml
                name: "Webhook Handler"
                trigger:
                  type: webhook
                steps:
                  - id: process
                    type: code
                    snippet: |
                      return {"status": "ok"}
                ```

                Fork and patch:
                ```yaml
                based_on: "moltbook-verify"
                name: "ServiceX Verification"
                patches:
                  - action: update_prompt
                    step_id: "code_1"
                    snippet: |
                      return {"token": payload["sx_token"]}
                ```

            tags: JSON array of extra tags to add (merged with DSL tags)

        Returns:
            JSON with workflow_id, slug, node_count, edge_count, mode ("created"|"forked"),
            and webhook_url (if trigger_webhook present).
        """
        # 1. Parse YAML DSL
        # 2. If based_on: clone source workflow, apply patches (fork mode)
        # 3. Else: resolve resources (model capability → credential, inherit → parent config)
        # 4. Compile steps → nodes[] + edges[] (implicit linear flow, explicit branching)
        # 5. Create inline tool nodes + tool edges for agent steps
        # 6. POST /api/v1/workflows/ → POST /nodes/ → POST /edges/
        # 7. POST /api/v1/workflows/{slug}/validate/
        # 8. On error: delete workflow (rollback). Return summary.
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="workflow_create_tool",
    display_name="Create Workflow",
    description="Create a new workflow from a YAML DSL (create from scratch or fork+patch)",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON with workflow_id, slug, counts, mode")],
    config_schema={
        "type": "object",
        "properties": {
            "api_base_url": {
                "type": "string",
                "default": "http://localhost:8000",
                "description": "Base URL for platform API",
            },
        },
    },
))
```

**Polymorphic identity:**

```python
class _WorkflowCreateToolConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "workflow_create_tool"}

"workflow_create_tool": ToolComponentConfig,
```

---

### 2.2 `workflow_discover`

**File:** `platform/components/workflow_discover.py`

Searches existing workflows with **gap-analysis scoring** against declared requirements. Returns match scores and capability breakdowns to support three-tier reuse decisions: full match → reuse, partial match → fork+patch, no match → create from scratch.

```python
@register("workflow_discover")
def workflow_discover_factory(node):

    @tool
    def discover_workflows(
        query: str = "",
        tags: str = "[]",
        requirements: str = "{}",
    ) -> str:
        """Search existing workflows by description, tags, or capability requirements.

        Returns workflows ranked by match score with gap analysis showing what
        each workflow has vs. what's missing. Use this to decide whether to
        reuse, fork+patch, or create from scratch.

        Three-tier reuse:
        - match_score >= 0.95: Reuse as-is (spawn_and_await directly)
        - match_score >= 0.50: Fork and patch (workflow_create with based_on)
        - match_score < 0.50: Create from scratch (workflow_create with full DSL)

        Args:
            query: Search text (matched against name and description via LIKE)
            tags: JSON array of tags to filter by (e.g., '["webhook"]')
            requirements: JSON object of capability requirements:
                '{"model": "gpt-4", "tools": ["code", "web_search"],
                  "trigger": "webhook", "memory": true}'

        Returns:
            JSON array of matching workflows with gap analysis and metrics:
            [{"slug": "moltbook-verify", "name": "...", "description": "...",
              "tags": ["webhook", "verification"],
              "trigger_types": ["trigger_webhook"],
              "tool_types": ["code"],
              "model_name": "gpt-4o",
              "has_memory": false,
              "match_score": 0.85,
              "has": ["code", "webhook"],
              "missing": ["web_search"],
              "extra": ["http_request"],
              "execution_count": 12,
              "success_rate": 0.92,
              "avg_duration_ms": 4500,
              "avg_cost_usd": 0.03}]
        """
        # 1. Query workflows with LIKE on name/description
        # 2. Filter by tags (JSON overlap)
        # 3. Join WorkflowNode to inventory: trigger_types, tool_types, model, memory
        # 4. If requirements provided: compute gap analysis per workflow
        #    - has: intersection of requirements and capabilities
        #    - missing: requirements not in capabilities
        #    - extra: capabilities not in requirements
        #    - match_score: weighted(capability_match, tag_overlap, success_rate)
        # 5. Join WorkflowExecution to compute execution_count, success_rate, avg_duration, avg_cost
        # 6. Sort by match_score descending
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="workflow_discover",
    display_name="Discover Workflows",
    description="Search workflows by requirements with gap-analysis scoring for reuse decisions",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON array of workflows with match scores and gap analysis")],
))
```

**Polymorphic identity:**

```python
class _WorkflowDiscoverConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "workflow_discover"}

"workflow_discover": ToolComponentConfig,
```

---

## 3. Execution Tool (1 component)

### 3.1 `spawn_and_await`

**File:** `platform/components/spawn_and_await.py`

```python
from langgraph.types import interrupt

@register("spawn_and_await")
def spawn_and_await_factory(node):
    extra = node.component_config.extra_config or {}
    default_timeout = extra.get("timeout_seconds", 300)

    @tool
    def spawn_and_await(
        task_id: str,
        workflow_slug: str,
        payload: str = "{}",
        timeout_seconds: int = 0,
    ) -> str:
        """Execute a subworkflow and wait for results, linked to the task registry.

        Uses LangGraph interrupt/resume — does NOT block any workers. The agent
        pauses, the subworkflow runs, and the agent resumes with the result.

        IMPORTANT: This tool requires a checkpointer on the agent. If conversation
        memory is off, the platform automatically uses a Redis ephemeral checkpointer.

        Args:
            task_id: Task registry ID to link this execution to (required)
            workflow_slug: Which workflow to execute
            payload: JSON payload passed to the child workflow's trigger
            timeout_seconds: Max wait time (0 = use default from config)

        Returns:
            JSON with execution results:
            {"execution_id": "exec_xyz", "status": "completed",
             "final_output": {...}, "duration_ms": 2340, "tokens_used": 8500}
        """
        timeout = timeout_seconds or default_timeout
        payload_dict = json.loads(payload) if isinstance(payload, str) else payload

        # 1. Update task: set status="running"
        # 2. Create child WorkflowExecution (reuse _create_child_execution from subworkflow.py)
        # 3. Link task.execution_id = child_execution_id
        # 4. Call interrupt() — pauses the ReAct loop, saves state to checkpointer
        result = interrupt({
            "action": "spawn_workflow",
            "task_id": task_id,
            "workflow_slug": workflow_slug,
            "payload": payload_dict,
            "timeout_seconds": timeout,
            "child_execution_id": child_execution_id,
        })
        # 5. When resumed: interrupt() returns child output
        # 6. Call sync_task_from_execution(task_id, execution)
        # 7. Return formatted result
        return json.dumps(result, default=str)
```

**Agent component integration:**

The `agent_node` function in `platform/components/agent.py` needs to detect interrupt signals and translate them to `_subworkflow` returns:

```python
def agent_node(state: dict) -> dict:
    # Check if resuming from a spawn_and_await interrupt
    child_result = state.get("_subworkflow_results", {}).get(node_id)
    if child_result is not None:
        # Resume: pass child result back into the agent via Command
        from langgraph.types import Command
        result = agent.invoke(Command(resume=child_result), config=config)
    else:
        # Normal invocation
        result = agent.invoke({"messages": messages}, config=config)

    # Check if agent was interrupted (spawn_and_await called interrupt())
    if hasattr(result, "__interrupt__") or _is_interrupted(result):
        interrupt_data = _extract_interrupt_data(result)
        return {"_subworkflow": {
            "child_execution_id": interrupt_data["child_execution_id"],
            "task_id": interrupt_data.get("task_id"),
        }}

    # Normal completion
    # ... existing message extraction logic ...
```

**Node type registration:**

```python
register_node_type(NodeTypeSpec(
    component_type="spawn_and_await",
    display_name="Spawn & Await",
    description="Execute a subworkflow and wait for results — non-blocking via interrupt/resume",
    category="agent",
    outputs=[PortDefinition(name="result", data_type=DataType.STRING, description="JSON with execution results")],
    config_schema={
        "type": "object",
        "properties": {
            "timeout_seconds": {
                "type": "integer",
                "default": 300,
                "minimum": 10,
                "maximum": 3600,
                "description": "Default max wait time in seconds",
            },
        },
    },
))
```

**Polymorphic identity:**

```python
class _SpawnAndAwaitConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "spawn_and_await"}

"spawn_and_await": ToolComponentConfig,
```

---

## 4. Agent Component Modifications

### 4.1 Dual checkpointer in `agent_factory`

```python
# In platform/components/agent.py

_redis_checkpointer = None
_redis_checkpointer_lock = threading.Lock()

def _get_redis_checkpointer():
    """Lazy singleton for ephemeral Redis checkpointer."""
    global _redis_checkpointer
    if _redis_checkpointer is None:
        with _redis_checkpointer_lock:
            if _redis_checkpointer is None:
                from langgraph.checkpoint.redis import RedisSaver
                from config import settings
                _redis_checkpointer = RedisSaver.from_url(settings.REDIS_URL)
                _redis_checkpointer.setup()
    return _redis_checkpointer


def _has_spawn_and_await_tool(node) -> bool:
    """Check if any tool connected to this agent is spawn_and_await."""
    db = SessionLocal()
    try:
        tool_edges = (
            db.query(WorkflowEdge)
            .filter(
                WorkflowEdge.workflow_id == node.workflow_id,
                WorkflowEdge.target_node_id == node.node_id,
                WorkflowEdge.edge_label == "tool",
            )
            .all()
        )
        for edge in tool_edges:
            tool_node = (
                db.query(WorkflowNode)
                .filter_by(workflow_id=node.workflow_id, node_id=edge.source_node_id)
                .first()
            )
            if tool_node and tool_node.component_type == "spawn_and_await":
                return True
        return False
    finally:
        db.close()


@register("agent")
def agent_factory(node):
    # ... existing setup ...

    has_spawn = _has_spawn_and_await_tool(node)
    needs_checkpointer = conversation_memory or has_spawn

    if conversation_memory:
        checkpointer = _get_checkpointer()          # SqliteSaver — durable
    elif has_spawn:
        checkpointer = _get_redis_checkpointer()     # Redis — ephemeral
    else:
        checkpointer = None

    agent_kwargs = dict(model=llm, tools=tools, checkpointer=checkpointer, ...)
```

### 4.2 Thread ID selection in `agent_node`

```python
def agent_node(state: dict) -> dict:
    # ... existing message prep ...

    config = None
    if conversation_memory:
        # Stable thread — conversation persists across executions
        thread_id = f"{user_id}:{chat_id}:{workflow_id}" if chat_id else f"{user_id}:{workflow_id}"
        config = {"configurable": {"thread_id": thread_id}}
    elif has_spawn:
        # Ephemeral thread — scoped to this execution only
        execution_id = state.get("execution_id", "unknown")
        thread_id = f"exec:{execution_id}:{node_id}"
        config = {"configurable": {"thread_id": thread_id}}
```

---

## 5. Registration Summary

### Files to create

| File | Component type | Tool name (LLM sees) |
|---|---|---|
| `platform/components/epic_create.py` | `epic_create` | `create_epic` |
| `platform/components/epic_status.py` | `epic_status` | `epic_status` |
| `platform/components/epic_search.py` | `epic_search` | `search_epics` |
| `platform/components/task_create.py` | `task_create` | `create_task` |
| `platform/components/task_list.py` | `task_list` | `list_tasks` |
| `platform/components/task_update.py` | `task_update` | `update_task` |
| `platform/components/task_cancel.py` | `task_cancel` | `cancel_task` |
| `platform/components/workflow_create_tool.py` | `workflow_create_tool` | `create_workflow` |
| `platform/components/workflow_discover.py` | `workflow_discover` | `discover_workflows` |
| `platform/components/spawn_and_await.py` | `spawn_and_await` | `spawn_and_await` |

### Files to modify

| File | Changes |
|---|---|
| `platform/components/__init__.py` | Add 10 imports to the import block |
| `platform/models/node.py` | Add 10 `_*Config` classes + 10 entries in `COMPONENT_TYPE_MAP` |
| `platform/schemas/node_type_defs.py` | Add 10 `register_node_type()` calls |
| `platform/components/agent.py` | Dual checkpointer, interrupt detection, Command resume |

### New dependency

```
langgraph-checkpoint-redis
```

---

## 6. Design Notes

### Tool naming convention

The `component_type` (used in DB, node registry, canvas) differs from the `@tool` function name (what the LLM sees in function calling). The function name should be natural language — `create_epic` not `epic_create`. The component type follows the existing `{noun}_{verb}` pattern for consistency with `memory_read`, `memory_write`.

### All tools return JSON strings

Following existing convention (`memory_read`, `platform_api`, `create_agent_user`). The LLM receives and parses JSON. Errors return `{"error": "...", "success": false}`.

### DB access pattern

All registry tools use `SessionLocal()` directly (same as `memory_read`, `create_agent_user`). No HTTP calls to the platform API — direct DB access is faster and avoids authentication overhead for internal tools.

Exception: `workflow_create_tool` uses HTTP calls to the platform API (via `httpx`) to reuse the full validation pipeline. It needs agent API credentials (via `create_agent_user` pattern).

### User context resolution

Registry tools need `user_profile_id` to create epics. This is resolved from the execution state's `user_context` dict, following the pattern in `create_agent_user`. The tool captures it from the state at factory time or resolves it lazily from the execution.

### Tag parameters as JSON strings

LangChain tool parameters must be primitives (str, int, float, bool). Lists are passed as JSON strings (e.g., `tags='["webhook", "api"]'`) and parsed inside the tool. This matches the existing pattern where complex parameters are stringified.
