# Workflow Composition Design

**Date:** 2026-03-22
**Status:** Validated via prototype
**Context:** Session exploring decomposition of monolithic workflow-generator into composable units

## Core Insight

The smallest unit in Pipelit is a **function**: `(state: dict) → dict`.

Everything is composition of this atom:

```
function         — (state) → dict                    — the atom
node             — function + config + schema         — atom with a contract
workflow         — nodes + edges                      — composition of atoms
workflow-as-node — workflow embedded in another graph  — fractal composition
```

Nodes and workflows are interchangeable. A workflow embedded as a node in another graph has the same interface as any other node. The distinction between "node" and "workflow" is granularity, not kind.

## Design Principles

### 1. Workflows Are Deterministic Pipelines

- Strict typed contracts between workflows
- No negotiation/clarification loops between composed workflows
- Agents do reasoning *inside* nodes; orchestration stays deterministic
- This is the N8N layer — the reliable backbone
- The moment workflows "converse" with each other, you've left the workflow space and entered the agent space (hard to debug, hard to price, hard to guarantee)

### 2. Prefer `agent` Over `deep_agent` in Composed Workflows

- Deep agents (planning, filesystem, subagents) are overkill for scoped tasks within a pipeline
- Regular agents with specific tools are faster, cheaper, more predictable, easier to test
- Reserve deep_agent for genuinely open-ended conversational nodes (e.g., the Scribe gathering requirements from a human)

### 3. Machine-Readable Contracts via input_schema / output_schema

- `input_schema` and `output_schema` fields already exist on the Workflow model (currently null)
- Populate with JSON Schema to define the contract
- Enables autonomous agents to discover workflows via `workflow_discover` and know:
  - What the workflow does (description)
  - What input it expects (input_schema)
  - What it returns (output_schema)
- Same pattern as OpenAPI / function calling tool schemas
- This is the foundation for workflow-as-node composability

### 4. Workflows and Nodes Are REPL (Read-Eval-Print Loop)

- Every node is independently invocable with an input and returns observable output
- Every workflow is independently callable with a typed payload and returns a result
- No need to run the full chain to test one piece
- **REPL is achieved through composition, not new infrastructure:**
  - Assertion nodes provide in-graph validation (already built)
  - A workflow embedded as a `workflow` node + downstream `assertion` node = REPL for that workflow
  - Test harness pattern: `trigger_manual → workflow node → assertion node`
- This enables rapid prompt iteration: change a node's prompt, eval it, see output, adjust, repeat

### 5. The Generator Is Scale-Invariant

- A "node generator" and a "workflow generator" are the same thing at different scales
- The generator takes requirements and produces a **function with a contract** (`input_schema → output_schema`)
- Whether that function is implemented as a code node, an agent with tools, a small workflow, or a nested workflow is an implementation detail
- The contract is what matters, not the internal structure

## Proof of Concept

### What We Built

Split the monolithic workflow-generator (22 nodes) into two composed workflows:

**requirements-gatherer** (6 nodes):
```
trigger_chat → scribe (deep_agent) → scribe_check (switch)
                                        ├─ "ready" → invoke_constructor (workflow node → workflow-generator-b)
                                        └─ "__other__" → reply_clarify
```

**workflow-generator-b** (18 nodes):
```
trigger_workflow → dispatch → gherkin_agent + topology_agent (parallel)
                                → checks → join → verifier → check → builder/reply
```

### What Worked

- Parent triggers child via `workflow` node with `input_mapping`
- Data passes correctly from parent's `node_outputs.scribe.output` to child's `trigger_wf.requirements`
- Child executes full pipeline (dispatch, parallel agents, join, verify)
- Parent resumes after child completes, receives child's output
- Output visible on canvas in both workflows

### Bugs Found (Infrastructure)

1. **Jinja2 path resolution**: `trigger_wf.payload.requirements` should be `trigger_wf.requirements` — the trigger_workflow node flattens the payload when emitting as node output
2. **Trigger mode**: `implicit` mode bypasses trigger resolver; `explicit` mode required for the child's `trigger_workflow` node to fire
3. **Long prompts in inline JSON**: System prompts dropped when embedded in large JSON payloads during node creation — must patch separately via API

## Decomposition Plan

| Workflow | Input Contract | Output Contract |
|---|---|---|
| **requirements-gatherer** | natural language (chat) | `{requirements: string}` |
| **spec-generator** | `{requirements: string}` | `{gherkin: string, topology: string}` |
| **spec-verifier** | `{gherkin: string, topology: string}` | `{verdict: pass\|fail, issues: string[]}` |
| **workflow-builder** | `{gherkin: string, topology: string}` | `{workflow_slug: string}` |

Orchestration chain:
```
requirements-gatherer → spec-generator → spec-verifier → workflow-builder
```

Each independently testable with fixture inputs. Each REPL-invocable via test harness workflows.

## Dynamic Node Registry — Critical Gap

### Problem

All node types are currently hardcoded:

- `COMPONENT_REGISTRY` — Python dict populated at import time by `@register` decorators
- `NODE_TYPE_REGISTRY` — hardcoded in `node_type_defs.py` with port definitions for 23+ built-in types
- Frontend — hardcoded component types in palette, canvas, config panel

If the generator creates a custom node at runtime, there is **nowhere for it to live**. It cannot be registered without restarting the server, visualized on the canvas, discovered by other workflows, or inspected for its ports and schema.

### Solution: Database-Backed Node Registry

A `custom_node_types` table (or similar) that stores dynamically created node types:

| Field | Purpose |
|---|---|
| `slug` | Unique identifier |
| `name` | Display name |
| `description` | What it does |
| `input_schema` | JSON Schema for inputs |
| `output_schema` | JSON Schema for outputs |
| `implementation_type` | `code` / `workflow` / `agent` |
| `implementation_ref` | Code block ID, workflow slug, or agent config |
| `icon` / `category` | For the palette/canvas |
| `created_at` | When it was registered |

**Implementation types:**
- `code` — points to a `CodeBlock` row (Python function)
- `workflow` — points to a workflow slug (composition of nodes)
- `agent` — points to an agent config (LLM with tools)

All expose the same `input_schema → output_schema` contract.

### Integration Points

- `GET /workflows/node-types/` merges built-in `NODE_TYPE_REGISTRY` + dynamic registry from DB
- Frontend palette renders both built-in and custom nodes from the same API
- `workflow_discover` tool can search custom nodes alongside workflows
- Generator (#169) writes new node types to this registry
- DSL spec (#163) references both built-in and custom node types

### Why This Is a Prerequisite

The node generator (#169) needs somewhere to **put** what it creates. Without a dynamic registry, generated nodes cannot be reused, discovered, or composed into other workflows. This must be built before the generator and before the DSL spec.

## Roadmap Implications

1. **Populate `input_schema`/`output_schema` on workflows (P0)** — Foundation for contracts, discoverability, and workflow-as-node composability. Just populate the existing fields.

2. **Dynamic Node Registry (P0)** — Separate concern from execution. Makes custom nodes visible in the palette, discoverable via API, renderable on the canvas. Prerequisite for the generator to produce reusable, visible outputs.

3. **#169 (Node/Workflow Generator)** — Uses composition pattern. Produces code nodes, agent nodes, or workflows depending on scale. Registers outputs in the dynamic registry.

4. **#163 (DSL Spec)** — Codifies proven patterns. Must include `input_schema`/`output_schema` as first-class fields. References both built-in and custom node types from registry.

5. **REPL is composition** — No new eval endpoints needed. Test any workflow by embedding it as a `workflow` node in a test harness with assertion nodes.

6. **Agent backend abstraction (future)** — CC as an alternative agent backend alongside LangGraph. Same sandbox, same contract.

7. **Recommended order:**
   ```
   ✅ Workflow composition (validated 2026-03-22)
   → Populate input_schema/output_schema on workflows
   → Dynamic Node Registry
   → #169 Node/workflow generator (uses composition + registers outputs)
   → #163 DSL spec (codifies what works, references registry)
   → #181 Workflow test execution (builds on DSL + assertions)
   ```

## Key Architectural Insight

The distinction between workflows and agents is the critical business decision:

- **Workflows** = deterministic, strict contracts, testable, composable like functions. Humans trust things they can see and predict.
- **Agents** = LLM reasoning contained *within* workflow nodes. Powerful but scoped.

The power is that a workflow *contains* agents, not that workflows *are* agents. Keep the orchestration deterministic, let the LLM do its thing inside each node.

This is why N8N's business works — a thin layer of deterministic orchestration that humans can reason about, with the intelligence happening inside individual nodes.

## Agent Node as Backend Abstraction

The agent node type is an abstraction over execution backends. Today it uses LangGraph (`create_react_agent`). The same node contract — `(state) → dict`, sandboxed execution, input/output schema — can support alternative backends:

| Backend | Strength | Use Case |
|---|---|---|
| **LangGraph** (current) | Structured tool calling, ReAct loop | Most agent tasks — classification, extraction, API calls |
| **Claude Code** (future) | Autonomous coding, planning, filesystem ops | Code generation, refactoring, complex multi-step builds |
| **Other SDKs** (future) | Varies | OpenAI Agents SDK, CrewAI, etc. |

All backends run inside the same sandboxed environment (bwrap/container). The node's external contract is unchanged — callers don't know or care which backend executes the work. This is a configuration choice on the node, not a structural change.

The builder node in the workflow-generator is a natural candidate for a CC backend — it needs to call APIs, inspect results, handle errors, and retry. That's an autonomous session, not a single ReAct loop.

**Status:** Future direction. Not a blocker for current work. The existing LangGraph backend covers all immediate needs.

## Execution Primitives Are Sufficient

The existing node types cover all **execution** needs — no new runtime primitives required:

- **Code node** — runs any Python function. A "custom node" is just a code node with specific logic.
- **Agent node** — LangGraph agent (or future backends) with tools wired via tool edges. A "custom tool" is just a code node connected as a tool edge.
- **Workflow node** — calls any workflow by slug. A "custom composite node" is just a workflow.

## Dynamic Node Registry — Visibility and Discoverability

Execution and discoverability are separate concerns. The primitives above solve execution. The registry solves **visibility**:

### The Problem

- The palette shows 23 hardcoded node types — that's all users see
- A "sentiment analyzer" code block created last week is invisible
- A workflow with `input_schema`/`output_schema` doesn't appear as a draggable node type
- Custom nodes exist but are **dark** — you must know they're there and manually configure a code/workflow node to reference them
- Same problem applies to credential types — only hardcoded types are visible

### What the Registry Solves

| Concern | Without Registry | With Registry |
|---|---|---|
| **Catalog** | Users must remember what exists | Browsable list of all reusable units |
| **Palette** | 23 hardcoded types | Built-in + custom types, merged |
| **Canvas rendering** | Custom nodes look generic | Proper icons, categories, port definitions |
| **Discovery** | `workflow_discover` returns workflows only | Returns all reusable units with schemas |
| **Credential types** | Hardcoded LLM/Telegram/webhook | Dynamic types, free-typing |

### Design: Templates with Versioned References

A dynamic registry entry is a **reusable type** (like a class), not an instance. Nodes in workflows are **instances** that reference a specific version of the type.

Key distinction:
- **Code node instance** = "this specific Python code in this specific workflow" — one-off, not reusable
- **Registry entry** = "a reusable type that can be instantiated many times across many workflows" — a package

#### The Versioning Pattern

Instances pin to a specific version. The registry publishes new versions. Instances upgrade explicitly. This is the package manager pattern.

The existing `CodeBlock` + `CodeBlockVersion` + `CodeBlockTest` model already provides the versioning infrastructure for code-backed types. Workflows already have versioning via their own update history.

#### Registry Table: `node_type_templates`

| Field | Purpose |
|---|---|
| `slug` | Unique identifier (e.g. `sentiment-analyzer`) |
| `name` | Display name |
| `description` | What it does |
| `category` | For palette grouping |
| `icon` | For canvas rendering |
| `input_schema` | JSON Schema for input ports |
| `output_schema` | JSON Schema for output ports |
| `implementation_type` | `code` / `workflow` / `agent` |
| `implementation_ref` | Code block ID, workflow slug, or agent config ID |
| `current_version` | Latest published version |
| `created_at` | When it was registered |
| `updated_at` | Last update |

#### Instance Reference (on WorkflowNode)

When a user drags a registry type onto the canvas, the node stores:

| Field | Value |
|---|---|
| `component_type` | `code` / `workflow` / `agent` (the underlying primitive) |
| `node_type_template_slug` | `sentiment-analyzer` (which registry type this is) |
| `pinned_version` | `3` (which version of the template) |

This means:
- **Execution layer unchanged** — the node runs as a regular code/workflow/agent node
- **Canvas knows the type** — renders with the registry's icon, ports, category
- **Version pinning** — updating the registry type doesn't break existing workflows
- **Explicit upgrade** — users choose when to upgrade instances to a new version

#### Workflow-Backed Types

Workflows with `input_schema`/`output_schema` populated can auto-register as node types. A workflow IS a registry entry — its slug is the template slug, its version history is the version. Instances are `workflow` nodes with `target_workflow` pointing at the slug.

#### How It Composes

```
Registry (types)                    Workflows (instances)
┌───────────────────┐              ┌────────────────────────────┐
│ sentiment-analyzer│              │ my-workflow                │
│   type: code      │──────────►  │   node: analyze            │
│   code_block: 42  │   creates   │     type: code             │
│   version: 3      │   instance  │     template: sent-analyzer│
│   input: {text}   │             │     pinned_version: 3      │
│   output: {score}│              │                            │
└───────────────────┘              └────────────────────────────┘
```

### Integration Points

- `GET /workflows/node-types/` merges built-in `NODE_TYPE_REGISTRY` + `node_type_templates` from DB
- Frontend palette renders both built-in and custom nodes from the same API
- `workflow_discover` tool searches custom nodes alongside workflows
- Generator (#169) registers new node types in this table with version 1
- DSL spec (#163) can reference both built-in and custom node type slugs
- Version upgrade UI — show when a node's pinned version is behind `current_version`
