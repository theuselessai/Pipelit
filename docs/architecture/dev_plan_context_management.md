# Architecture: Context Management for Workflow Platform

## Current State (Problems)

### Problem 1: Unbounded messages within a single execution
All nodes share `state["messages"]`. Each node appends. Agent components dump ALL intermediate ReAct messages (tool_call, tool_result, reasoning steps) into shared state. A 5-node workflow with 2 agents can accumulate 50+ messages before hitting the final node.

**Where it happens:** `platform/services/state.py:merge_state_update()` blindly appends. `platform/components/agent.py:agent_node()` returns `out_messages` (all ReAct loop messages).

### Problem 2: No conversation continuity across executions
Each chat message creates a new `WorkflowExecution` with a random `thread_id`. Initial state contains only the current message — no history. Redis state is deleted after execution completes (`_cleanup_redis`). The `Conversation` model exists but is never populated.

**Where it happens:** `platform/api/executions.py:send_chat_message()` creates fresh execution. `platform/services/orchestrator.py:_build_initial_state()` only includes current trigger text.

### Problem 3: Sub-workflows are unimplemented
`platform/components/subworkflow.py` raises `NotImplementedError`. No mechanism for parent→child context passing or result aggregation.

### Problem 4: No token counting anywhere in platform/ — PARTIALLY RESOLVED
The old `app/services/tokens.py` has tiktoken-based counting, but nothing in `platform/` uses it. `max_tokens` on ai_model config controls output limit only.

**Update (2026-02-13):** `platform/services/token_usage.py` now tracks token usage from LangChain `usage_metadata` (actual provider-reported tokens, not estimated via tiktoken). This covers cost tracking and budget enforcement but does NOT solve pre-call context trimming — the Layer 1 work below is still needed for preventing context overflow before LLM calls.

---

## Proposed Architecture — 3 Layers

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Sub-workflow Context Isolation                 │
│  Parent scopes context → Child has own state → Result   │
│  flows back as structured data                          │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Conversation Continuity (cross-execution)     │
│  Thread grouping → History loading → Sliding window     │
│  + compression for long conversations                   │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Intra-workflow Context Management              │
│  Token counting → Pre-call trimming → Agent output      │
│  isolation → Per-node context budgets                   │
└─────────────────────────────────────────────────────────┘
```

---

## Layer 1: Intra-workflow Context Management

**Goal:** Prevent context overflow within a single execution. Smallest scope, highest impact, zero schema changes.

### 1a. Token counting service

New `platform/services/context.py`:
- `count_message_tokens(msg: AnyMessage) → int` — tiktoken cl100k_base, handles str/list content + tool_calls
- `count_messages_tokens(messages) → int` — sum
- `get_context_window(model_name, extra_config) → int` — lookup table + `extra_config["context_window"]` override + 128K default
- `trim_messages(messages, model_name, max_tokens, extra_config, system_messages) → list` — keep most recent that fit within `context_window - response_reserve - system_tokens`

### 1b. Pre-call trimming in LLM-invoking components

Modify `agent.py`, `ai_model.py`, `react_agent.py`:
```python
# Before LLM call:
messages = trim_messages(messages, model_name=..., max_tokens=..., extra_config=...)
```

Add `resolve_model_config(node) → (model_name, max_tokens, extra_config)` to `services/llm.py` to avoid duplicating FK traversal.

**Not modified:** `categorizer.py` (already bounded — uses only system prompt + last message), `router.py` (no LLM call), `chat.py` (dead code, not registered).

### 1c. Agent output isolation

Agent nodes currently return ALL ReAct loop messages. Change to return only the final AI response:

```python
# BEFORE (agent.py):
return {"messages": out_messages, ...}          # 10-20 messages from ReAct loop

# AFTER:
return {"messages": [final_ai_message], ...}    # Just the answer
```

This prevents intermediate tool_call/tool_result messages from polluting shared state for downstream nodes. The full ReAct trace is still logged in `ExecutionLog` via the orchestrator.

### 1d. Files involved
- **Create:** `platform/services/context.py`, `platform/tests/test_context.py`
- **Modify:** `platform/services/llm.py` (add `resolve_model_config`), `platform/components/agent.py`, `platform/components/ai_model.py`, `platform/components/react_agent.py`
- **No schema/migration changes** — uses existing `extra_config` JSON field

---

## Layer 2: Conversation Continuity (Cross-Execution)

**Goal:** Multi-turn chat where each execution has access to conversation history. Requires schema changes and new orchestrator logic.

### 2a. Thread-based execution grouping

Activate the existing `Conversation` model. When a chat message arrives, find or create a conversation thread:

```
User sends message → find active Conversation for (user, workflow) → use its thread_id
                   → if none exists, create new Conversation + thread_id
```

Modify `send_chat_message()` in `platform/api/executions.py`:
- Look up existing `Conversation` for `(user_profile_id, workflow_id)`
- Reuse its `thread_id` instead of generating a random one
- Link the new execution to this conversation

### 2b. History loading into initial state

Modify `_build_initial_state()` in orchestrator to load conversation history:

```python
def _build_initial_state(execution) -> dict:
    # Current: only includes trigger text
    # New: also load recent messages from prior executions in same thread

    history_messages = _load_thread_history(
        thread_id=execution.thread_id,
        limit=20,           # last 20 messages
        max_tokens=16000,   # or token-budgeted
    )

    messages = history_messages + [HumanMessage(content=trigger_text)]
    return {"messages": messages, ...}
```

### 2c. History storage after execution

After execution completes (in `_finalize`), persist the conversation turn:

```python
# In _finalize():
# 1. Extract the user message + final AI response
# 2. Save to ConversationMessage table (new model)
# 3. Update Conversation.updated_at
```

New model `ConversationMessage`:
```python
class ConversationMessage(Base):
    id: int (PK)
    conversation_id: int (FK → Conversation)
    execution_id: str (FK → WorkflowExecution)
    role: str  # "human" | "ai"
    content: str
    token_count: int
    created_at: datetime
```

### 2d. Sliding window + compression

For long conversations, apply context budget:
- **Simple (Phase 1):** Keep last N messages that fit token budget (reuse `trim_messages` from Layer 1)
- **Advanced (Phase 2):** LLM-based compression — summarize old messages, keep recent ones (reuse pattern from `app/services/sessions.py:compress_conversation`)

### 2e. Files involved
- **Create:** `platform/models/conversation_message.py` (or extend `conversation.py`), migration
- **Modify:** `platform/api/executions.py` (thread lookup), `platform/services/orchestrator.py` (history loading + persistence), `platform/models/conversation.py` (activate)
- **Reuse:** `platform/services/context.py` from Layer 1

---

## Layer 3: Sub-workflow Context Isolation

**Goal:** A parent workflow can invoke child workflows with scoped context. Each child has its own state. Results flow back as structured data.

### 3a. Subworkflow execution model

Implement `platform/components/subworkflow.py`:

```python
@register("workflow")
def subworkflow_factory(node):
    subworkflow_id = node.subworkflow_id

    def subworkflow_node(state: dict) -> dict:
        # 1. Build scoped input for child
        child_input = _scope_context(state, node)

        # 2. Create child WorkflowExecution
        child_execution = create_child_execution(
            parent_execution_id=state["execution_id"],
            workflow_id=subworkflow_id,
            trigger_payload=child_input,
        )

        # 3. Run child synchronously (or async with wait)
        result = run_child_workflow(child_execution)

        # 4. Return structured result (NOT child's raw messages)
        return {
            "messages": [AIMessage(content=result.summary)],  # Just the output
            "node_outputs": {node_id: result.output},
        }

    return subworkflow_node
```

### 3b. Context scoping (parent → child)

What the child receives from the parent:
- **Trigger payload:** The parent's current output or a user-configured subset
- **User context:** Inherited from parent's state
- **NOT messages:** Child starts with fresh message list — only sees its own conversation

```python
def _scope_context(parent_state, node):
    """Build trigger payload for child workflow."""
    extra = node.component_config.extra_config or {}

    # Option A: Pass specific node_outputs
    input_source = extra.get("input_source", "last_message")
    if input_source == "last_message":
        messages = parent_state.get("messages", [])
        text = messages[-1].content if messages else ""
    elif input_source == "node_output":
        source_node = extra.get("source_node_id")
        text = str(parent_state.get("node_outputs", {}).get(source_node, ""))
    else:
        text = ""

    return {
        "text": text,
        "parent_execution_id": parent_state["execution_id"],
        "user_context": parent_state.get("user_context", {}),
    }
```

### 3c. Result aggregation (child → parent)

Child execution produces `final_output`. Parent receives it as:
- A structured dict in `node_outputs`
- An `AIMessage` summary in `messages` (so downstream nodes can reference it conversationally)

### 3d. Execution relationship

New FK on `WorkflowExecution`:
```python
parent_execution_id: str | None  # FK to parent execution
```

This enables:
- Tracing execution trees
- Cancellation cascading (cancel parent → cancel children)
- Debugging nested workflows

### 3e. Files involved
- **Modify:** `platform/components/subworkflow.py` (implement), `platform/models/execution.py` (add `parent_execution_id`)
- **Modify:** `platform/services/orchestrator.py` (add `run_child_workflow()` helper)
- **Migration** for `parent_execution_id` column

---

## Implementation Phases

| Phase | Layer | Scope | Dependencies |
|-------|-------|-------|-------------|
| **Phase A** | Layer 1 | Token counting, pre-call trimming, agent output filtering | None |
| **Phase B** | Layer 2a-2b | Thread grouping + history loading | Phase A (for trim_messages) |
| **Phase C** | Layer 2c-2d | History persistence + compression | Phase B |
| **Phase D** | Layer 3 | Sub-workflow implementation | Phase A |

Phase A is self-contained and delivers immediate value. Phases B-D can be done in any order after A.

---

## Key Design Decisions

1. **Trimming over compression** (Layer 1) — No LLM calls for compression. Fast, deterministic. Compression can be added in Layer 2d.

2. **Agent output isolation** — Agents return only their final response to shared state. ReAct internals stay internal. This is always-on, not configurable — no downstream node needs intermediate tool_call messages.

3. **Context window via `extra_config`** (Layer 1) — No schema migration. Users can optionally set `{"context_window": 32000}` on an ai_model node. Otherwise, auto-detected from model name.

4. **Thread grouping via existing Conversation model** (Layer 2) — Don't create a new model; activate the unused one. Add `ConversationMessage` for per-turn storage.

5. **Child workflows get scoped context, not raw messages** (Layer 3) — Clean boundary. Parent decides what to pass via `extra_config`. Child starts fresh.

6. **Memory system stays orthogonal** — The memory system (facts, episodes, procedures) provides long-term knowledge. Context management provides short-term conversation flow. They complement but don't replace each other. `identify_user` + `memory_read` tools remain the way agents access long-term memory.
