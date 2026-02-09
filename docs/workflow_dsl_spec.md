# Workflow DSL Specification

## Date: 2025-02-09
## Prerequisites: `multiagent_delegation_architecture.md`, `tool_schemas_and_component_specs.md`

---

## Overview

A YAML-based declarative workflow definition language that agents use to create workflows via the `workflow_create` tool. Inspired by Microsoft's Agent Framework Declarative Workflows — a "coding" task format that compiles to Pipelit API calls (nodes + edges).

The DSL provides two modes:
1. **Create from scratch** — Full workflow definition with steps, triggers, and tools
2. **Fork and patch** (`based_on` + `patches`) — Start from an existing workflow, apply incremental modifications

---

## 1. Full Workflow DSL

### 1.1 Basic Structure

```yaml
name: "Moltbook Webhook Verification"
description: "Receives Moltbook verification ping and responds with token"
tags: ["webhook", "verification", "moltbook"]

trigger:
  type: webhook

model:
  capability: "gpt-4"           # Resolved to concrete credential at compile time
  # OR
  inherit: true                  # Use parent agent's model credential

steps:
  - id: validate
    type: code
    snippet: |
      import json
      payload = json.loads(input_data)
      if payload.get("type") != "verification":
          raise ValueError("Not a verification request")
      return {"token": payload["verify_token"], "status": "ok"}

  - id: respond
    type: code
    snippet: |
      return {"verified": True, "token": trigger.payload.token}
```

### 1.2 Step Types

Each step maps to a Pipelit component type:

| Step Type | Component Type | Required Fields | Optional Fields |
|-----------|---------------|-----------------|-----------------|
| `agent` | `agent` | `prompt` (system prompt) | `model`, `tools`, `memory` |
| `code` | `code` | `snippet` | — |
| `http` | `http_request` (tool) | `url` | `method`, `headers`, `body`, `timeout` |
| `switch` | `switch` | `rules` | `default` |
| `loop` | `loop` | `over`, `body` | `max_iterations` |
| `workflow` | `workflow` | `slug` | `payload` |
| `transform` | `text_template` | `template` | — |
| `human` | `human_confirmation` | `message` | `timeout` |

### 1.3 Triggers

```yaml
# Webhook trigger
trigger:
  type: webhook

# Telegram trigger
trigger:
  type: telegram
  credential: inherit           # Use parent's telegram credential

# Chat trigger (for testing / manual invocation)
trigger:
  type: chat

# No trigger (subworkflow — invoked by parent)
trigger: none
```

### 1.4 Model Declaration

Models are declared by **capability**, not by credential ID. The DSL compiler resolves capabilities to concrete credentials at creation time.

```yaml
# Capability-based (recommended)
model:
  capability: "gpt-4"           # Matches any credential providing gpt-4
  temperature: 0.7

# Inherit from parent agent
model:
  inherit: true                  # Copies the parent agent's model + credential

# Explicit (escape hatch — not recommended)
model:
  credential_id: 5
  model_name: "gpt-4o"
  temperature: 0.7
```

**Resolution order:**
1. `inherit: true` → Copy `llm_credential_id` and `model_name` from the parent agent's node config
2. `capability: "<model>"` → Query `GET /credentials/?type=llm_provider` and find a credential that provides the requested model
3. `credential_id` → Direct reference (fragile, avoid)

### 1.5 Implicit vs Explicit Flow

**Implicit linear flow** — Steps execute in order. No edges needed:

```yaml
steps:
  - id: fetch
    type: http
    url: "https://api.example.com/data"

  - id: process
    type: code
    snippet: |
      data = json.loads(input_data)
      return {"count": len(data["items"])}

  - id: respond
    type: agent
    prompt: "Summarize the data"
```

Compiles to: `trigger → fetch → process → respond` (3 direct edges)

**Explicit branching** — Use `goto` or `switch`:

```yaml
steps:
  - id: classify
    type: switch
    rules:
      - field: "trigger.payload.type"
        operator: "equals"
        value: "verification"
        route: "verify"
      - field: "trigger.payload.type"
        operator: "equals"
        value: "message"
        route: "handle_msg"
    default: "log_unknown"

  - id: verify
    type: code
    snippet: "return {'verified': True}"

  - id: handle_msg
    type: agent
    prompt: "Process the incoming message"

  - id: log_unknown
    type: code
    snippet: "return {'error': 'unknown type'}"
```

Compiles to: `switch` node with conditional edges (`condition_value` on each edge).

### 1.6 Tools for Agent Steps

Agent steps can declare inline tools:

```yaml
steps:
  - id: worker
    type: agent
    prompt: "You are a data analysis agent. Analyze the provided dataset."
    model:
      capability: "gpt-4"
    tools:
      - type: code                # Inline code execution tool
      - type: http_request        # HTTP request tool
      - type: calculator          # Calculator tool
      - type: web_search          # Web search tool
        config:
          searxng_url: "http://localhost:8080"
    memory: true                  # Enable memory_read + memory_write
```

Each tool entry creates a tool node and a `tool` edge connecting it to the agent.

### 1.7 Loops

```yaml
steps:
  - id: process_items
    type: loop
    over: "{{ fetch.output }}"     # Jinja2 expression for the iterable
    max_iterations: 100
    body:
      - id: transform_item
        type: code
        snippet: |
          item = json.loads(input_data)
          return {"processed": item["name"].upper()}

      - id: store_item
        type: http
        url: "https://api.example.com/items"
        method: POST
        body: "{{ transform_item.output }}"
```

### 1.8 Subworkflow Steps

Reference existing workflows:

```yaml
steps:
  - id: verify
    type: workflow
    slug: "moltbook-verify"
    payload:
      token: "{{ trigger.payload.verify_token }}"
```

---

## 2. Fork and Patch Mode (`based_on` + `patches`)

For partial matches — start from an existing workflow and apply incremental modifications instead of creating from scratch.

### 2.1 Structure

```yaml
based_on: "moltbook-verify"        # Existing workflow slug to fork
name: "ServiceX Webhook Verification"
description: "Adapted from moltbook-verify for ServiceX"
tags: ["webhook", "verification", "servicex"]

patches:
  - action: update_prompt
    step_id: "code_1"
    snippet: |
      # Updated for ServiceX token format
      return {"token": payload["sx_token"], "status": "ok"}

  - action: add_step
    after: "code_1"
    step:
      id: notify
      type: http
      url: "https://servicex.com/api/confirm"
      method: POST
      body: '{"verified": true}'

  - action: add_tool
    agent_id: "agent_1"
    tool:
      type: web_search
      config:
        searxng_url: "http://localhost:8080"

  - action: remove_tool
    agent_id: "agent_1"
    tool_type: "calculator"

  - action: remove_step
    step_id: "old_logger"

  - action: update_config
    step_id: "agent_1"
    config:
      extra_config:
        conversation_memory: true
```

### 2.2 Patch Actions

| Action | Description | Parameters |
|--------|-------------|------------|
| `add_step` | Insert a new step into the workflow | `after` (step_id), `step` (full step spec) |
| `remove_step` | Remove a step and reconnect edges | `step_id` |
| `update_prompt` | Update a code snippet or agent system prompt | `step_id`, `snippet` or `prompt` |
| `update_config` | Modify step configuration | `step_id`, `config` (merged into existing) |
| `add_tool` | Connect a new tool to an agent | `agent_id`, `tool` (tool spec) |
| `remove_tool` | Disconnect a tool from an agent | `agent_id`, `tool_type` |
| `update_trigger` | Change the trigger type or config | `trigger` (trigger spec) |
| `update_model` | Change the model for an agent step | `step_id`, `model` (model spec) |

### 2.3 Fork Semantics

When `based_on` is specified:

1. **Clone** — Copy all nodes, edges, and configurations from the source workflow into a new workflow
2. **Rename** — Apply `name`, `description`, `tags` from the DSL
3. **Patch** — Apply each patch action in order
4. **Validate** — Run the standard workflow validation pipeline
5. **Return** — New workflow slug, preserving the original as-is

The source workflow is never modified.

---

## 3. Capability-Based Resource Resolution

### 3.1 Problem

When an agent dynamically creates a workflow, it needs to specify which LLM credential and model to use. But credentials are platform-specific — the agent shouldn't hardcode credential IDs.

### 3.2 Resolution Strategies

**Strategy 1: `inherit`** (recommended for subworkflows)

```yaml
model:
  inherit: true
```

The DSL compiler copies the parent agent's `llm_credential_id` and `model_name` into the new workflow's agent nodes. This is the simplest and most common case — the child uses the same model as the parent.

**Strategy 2: Capability matching**

```yaml
model:
  capability: "gpt-4"
```

The compiler queries `GET /credentials/?type=llm_provider`, then for each credential calls `GET /credentials/{id}/models/` to find one that provides the requested model. First match wins.

**Strategy 3: Discovery** (agent asks the platform)

```yaml
model:
  discover: true
  preference: "cheapest"        # or "fastest", "most_capable"
```

The compiler lists available credentials and models, applies the preference filter, and selects automatically. Useful when the agent doesn't know what's available.

### 3.3 Tool Resource Resolution

Some tools need external credentials or URLs (e.g., `web_search` needs `searxng_url`). Resolution:

```yaml
tools:
  - type: web_search
    config:
      searxng_url: inherit       # Copy from parent agent's web_search tool config

  - type: http_request
    config:
      headers:
        Authorization: "Bearer {{ credential.api_key }}"   # Resolved at runtime
```

The `inherit` keyword on tool config values instructs the compiler to look up the parent agent's tool of the same type and copy the matching config value.

---

## 4. DSL Compiler

### 4.1 Architecture

```
YAML string (from agent's tool call)
    │
    ▼
┌──────────────┐
│  DSL Parser  │   ← Validates YAML structure, resolves `inherit` references
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│  Resource Resolver│  ← Resolves capabilities to credential IDs, inherits from parent
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  Graph Builder   │  ← Converts steps → nodes[], edges[] (API format)
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  API Caller      │  ← POST /workflows/, POST /nodes/, POST /edges/, POST /validate/
└──────┬───────────┘
       │
       ▼
{ workflow_id, slug, node_count, edge_count }
```

### 4.2 Step → Node/Edge Mapping

For a simple linear workflow:

```yaml
trigger:
  type: webhook
steps:
  - id: code_1
    type: code
    snippet: "return {'ok': True}"
  - id: agent_1
    type: agent
    prompt: "Summarize"
```

Compiles to:

```json
{
  "nodes": [
    {"node_id": "trigger_webhook_1", "component_type": "trigger_webhook", "is_entry_point": true},
    {"node_id": "code_1", "component_type": "code", "config": {"extra_config": {"snippet": "return {'ok': True}"}}},
    {"node_id": "agent_1", "component_type": "agent", "config": {"system_prompt": "Summarize", "llm_credential_id": 5, "model_name": "gpt-4o"}}
  ],
  "edges": [
    {"source_node_id": "trigger_webhook_1", "target_node_id": "code_1", "edge_type": "direct"},
    {"source_node_id": "code_1", "target_node_id": "agent_1", "edge_type": "direct"}
  ]
}
```

### 4.3 Error Handling

The compiler validates at each stage:

1. **Parse errors** → Return `{"error": "Invalid YAML: ...", "success": false}`
2. **Unknown step types** → Return `{"error": "Unknown step type 'xyz' at step 'step_1'", "success": false}`
3. **Resource resolution failures** → Return `{"error": "No credential found providing model 'gpt-4'", "success": false}`
4. **API validation failures** → Return validation errors from `POST /validate/`, then delete the partially-created workflow (rollback)

### 4.4 Fork Compiler (for `based_on` mode)

When `based_on` is present:

1. `GET /workflows/{based_on}/` — Fetch source workflow
2. `GET /workflows/{based_on}/nodes/` — Fetch all nodes
3. `GET /workflows/{based_on}/edges/` — Fetch all edges
4. `POST /workflows/` — Create new workflow with new name/description
5. For each source node: `POST /workflows/{new_slug}/nodes/` — Clone with same config
6. For each source edge: `POST /workflows/{new_slug}/edges/` — Clone
7. Apply patches in order:
   - `add_step`: Create node, create edges (reconnect)
   - `remove_step`: Delete node, reconnect surrounding edges
   - `update_prompt`: `PATCH /workflows/{slug}/nodes/{id}/` with new config
   - `add_tool`: Create tool node + tool edge
   - `remove_tool`: Delete tool edge + tool node
   - etc.
8. `POST /workflows/{new_slug}/validate/`

---

## 5. Integration with Task Registry

### 5.1 Task Requirements

Tasks in the registry can declare **requirements** — capabilities needed for the workflow that executes them. This connects task planning to workflow creation.

```python
# In task_create tool:
create_task(
    epic_id="ep_01JKXYZ",
    title="Analyze coverage gaps",
    requirements='{"model": "gpt-4", "tools": ["code", "web_search"], "memory": true}',
)
```

When the agent later creates a workflow for this task, the requirements inform:
- Which model capability to use
- Which tools to attach
- Whether memory is needed

### 5.2 Discovery → Create → Execute Pipeline

```
1. task_create(requirements={model: "gpt-4", tools: ["code"]})

2. workflow_discover(requirements={model: "gpt-4", tools: ["code"]})
   → Returns matches with gap analysis:
     [
       {slug: "analysis-v2", match_score: 0.95, has: ["code", "gpt-4"], missing: [], extra: ["http"]},
       {slug: "analysis-v1", match_score: 0.70, has: ["code"], missing: ["gpt-4"], extra: []},
     ]

3a. Full match (≥0.95): reuse as-is
    → spawn_and_await(task_id, workflow_slug="analysis-v2")

3b. Partial match (≥0.5): fork + patch
    → workflow_create(dsl_yaml_with_based_on="analysis-v1", patches=[add model capability])
    → spawn_and_await(task_id, workflow_slug="analysis-v1-patched")

3c. No match (<0.5): create from scratch
    → workflow_create(dsl_yaml_with_full_spec)
    → spawn_and_await(task_id, workflow_slug="new-analysis")
```

---

## 6. Examples

### 6.1 Simple Webhook Handler

```yaml
name: "Health Check Endpoint"
description: "Returns 200 OK for monitoring"
tags: ["health", "monitoring"]

trigger:
  type: webhook

steps:
  - id: respond
    type: code
    snippet: |
      return {"status": "healthy", "timestamp": __import__("datetime").datetime.utcnow().isoformat()}
```

### 6.2 Agent with Tools

```yaml
name: "Research Assistant"
description: "Agent that can search the web and execute code"
tags: ["research", "agent"]

trigger: none                    # Subworkflow — invoked by parent

model:
  inherit: true

steps:
  - id: researcher
    type: agent
    prompt: |
      You are a research assistant. Use web search to find information
      and code execution to process data. Return structured findings.
    tools:
      - type: web_search
        config:
          searxng_url: inherit
      - type: code
      - type: calculator
    memory: true
```

### 6.3 Multi-Step Pipeline with Branching

```yaml
name: "Content Moderator"
description: "Classifies content and routes to appropriate handler"
tags: ["moderation", "content"]

trigger:
  type: webhook

model:
  capability: "gpt-4"

steps:
  - id: classify
    type: agent
    prompt: "Classify the content as 'safe', 'review', or 'block'. Output only the category."

  - id: route
    type: switch
    rules:
      - field: "classify.output"
        operator: equals
        value: "safe"
        route: approve
      - field: "classify.output"
        operator: equals
        value: "block"
        route: reject
    default: manual_review

  - id: approve
    type: code
    snippet: "return {'action': 'approve', 'reason': 'auto-approved'}"

  - id: reject
    type: code
    snippet: "return {'action': 'reject', 'reason': 'auto-blocked'}"

  - id: manual_review
    type: human
    message: "Content needs manual review. Please approve or reject."
```

### 6.4 Fork and Patch

```yaml
based_on: "moltbook-verify"
name: "ServiceX Webhook Verification"
description: "Adapted from moltbook-verify for ServiceX API"
tags: ["webhook", "verification", "servicex"]

patches:
  - action: update_prompt
    step_id: "code_1"
    snippet: |
      import json
      payload = json.loads(input_data)
      # ServiceX uses different token field
      return {"token": payload["sx_verify_token"], "status": "ok"}

  - action: add_step
    after: "code_1"
    step:
      id: confirm
      type: http
      url: "https://api.servicex.com/webhooks/confirm"
      method: POST
      body: '{"verified": true, "agent_id": "{{ trigger.payload.agent_id }}"}'
```

---

## 7. Design Notes

### Why YAML over JSON?

- More readable for LLMs generating workflow specs
- Multi-line strings (`|`) are natural for code snippets and prompts
- Comments are supported (agents can annotate their reasoning)
- JSON is a valid YAML subset — agents can emit either

### Why not a visual builder?

The DSL is for **programmatic** workflow creation by agents. Human users continue to use the visual canvas. The DSL and canvas produce the same underlying representation (nodes + edges).

### Relationship to `platform_api` tool

The `workflow_create` tool with DSL is a higher-level interface than raw `platform_api`. Agents could still use `platform_api` directly for fine-grained control, but the DSL is the recommended path for workflow creation — it handles resource resolution, validation, and rollback automatically.

### DSL is not stored

The YAML DSL is ephemeral — it's compiled to nodes/edges at creation time. The workflow stores the standard node/edge representation. The DSL is a creation-time convenience, not a persistent format. To reconstruct the DSL from a workflow, a decompiler would be needed (future enhancement).
