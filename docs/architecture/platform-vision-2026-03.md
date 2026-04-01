# Platform Vision — State of the World

**Date:** 2026-03-22
**Context:** Design session consolidating architecture across pipelit, plit, msg-gateway, and tela

---

## The System Today

Four repositories, three layers, one vision that hasn't fully connected yet.

### Repository Map

```
plit/                  — CLI + packager (Rust)
  ├── plit             — Control plane CLI
  ├── plit-gw          — Gateway binary (from msg-gateway crate)
  └── plit-tui         — Terminal UI (from tela engine)

msg-gateway/           — Universal message router (Rust)
  ├── adapters/        — External adapter subprocesses (Telegram, generic)
  └── backends/        — Backend adapters (Pipelit webhook, OpenCode REST+SSE)

pipelit/               — Workflow engine (Python/FastAPI)
  ├── platform/        — Backend: API, orchestrator, components, models
  └── platform/frontend/ — React SPA (the GUI that's becoming a burden)

tela/                  — Terminal UI engine (Rust + JSX)
  ├── tela-engine      — QuickJS + ratatui runtime
  ├── tela-cli         — CLI tool (run, dev, init)
  └── examples/        — plit-tui, graph-boxes, graph-canvas
```

### What Exists and Works

```
PIPELIT (Workflow Engine)
  ✅ Workflow CRUD via REST API
  ✅ 23+ built-in node types (agents, code, triggers, routing, assertions)
  ✅ LangGraph agent execution with sandboxing (bwrap/container)
  ✅ Workflow composition — workflow nodes trigger child workflows
  ✅ Real-time WebSocket updates (node status, execution progress)
  ✅ Jinja2 expression resolution between nodes
  ✅ Assertion nodes for in-graph validation
  ✅ Agent tools: platform_api, workflow_create, workflow_discover
  ✅ CodeBlock + CodeBlockVersion + CodeBlockTest (versioned code storage)
  ✅ input_schema / output_schema fields on Workflow model (exist, unpopulated)
  ✅ Chat endpoint for conversational workflow triggering
  ✅ Scheduler (self-rescheduling via RQ)

GATEWAY (Universal Router)
  ✅ Multi-backend routing (Pipelit webhook, OpenCode REST+SSE, External subprocess)
  ✅ External adapter architecture (subprocess lifecycle management)
  ✅ Telegram adapter (Node.js, grammy long-polling)
  ✅ Generic adapter (built-in HTTP/WebSocket)
  ✅ CEL-based guardrails (inbound/outbound message filtering, hot-reload)
  ✅ Health monitoring with emergency alerts
  ✅ Admin API for credential CRUD
  ✅ Hot-reload config without restart
  ✅ Normalized message protocol (InboundMessage struct)

PLIT CLI (Control Plane)
  ✅ plit init (interactive setup wizard)
  ✅ plit start/stop (full stack lifecycle via honcho)
  ✅ plit credentials create/list/activate/deactivate
  ✅ plit auth login/status/logout (Pipelit backend auth)
  ✅ plit api workflow list/get/validate/delete
  ✅ plit api node-types (component catalog)
  ✅ plit local chat/send/listen (gateway messaging)
  ✅ plit health (system status)
  ✅ Auto-generated Rust API client (84 models, 19 modules)

TELA (Terminal UI Engine)
  ✅ JSX → QuickJS → ratatui rendering pipeline
  ✅ Component library: box, text, list, table, tabs, input, gauge, canvas
  ✅ Native APIs: fetch, WebSocket, storage, clipboard, env, filesystem
  ✅ Permission-gated security model (manifest.json)
  ✅ Hot-reload dev mode
  ✅ plit-tui chat client (working)
  ✅ graph-boxes example (DAG visualization with Unicode box drawing)
  ✅ graph-canvas example (braille-based graph rendering)
  ✅ Published to crates.io (v0.1.0)
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL WORLD                               │
│  Telegram    REST/WebSocket    (Discord, Email, Slack — planned)    │
│  MCP Clients (Claude Desktop, CC, Cursor — future)                 │
└──────┬──────────┬──────────────────────────────────────────────────┘
       │          │
       ▼          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         PLIT GATEWAY                                 │
│                     (Universal Message Router)                      │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Adapter Layer (external subprocesses)                         │  │
│  │  telegram (Node.js) │ generic (built-in) │ future: MCP-backed │  │
│  └─────────────────────────┬─────────────────────────────────────┘  │
│                            │                                        │
│  ┌─────────────────────────▼─────────────────────────────────────┐  │
│  │  Guardrails (CEL-based, hot-reload)                           │  │
│  └─────────────────────────┬─────────────────────────────────────┘  │
│                            │                                        │
│  ┌─────────────────────────▼─────────────────────────────────────┐  │
│  │  Routing Layer (credential.backend → named backend)           │  │
│  └──────┬──────────────────┬─────────────────────┬───────────────┘  │
│         │                  │                     │                  │
│  ┌──────▼──────┐  ┌───────▼───────┐  ┌──────────▼───────────┐     │
│  │  Pipelit    │  │  OpenCode     │  │  External (any)      │     │
│  │  (webhook)  │  │  (REST+SSE)   │  │  (subprocess)        │     │
│  └──────┬──────┘  └───────┬───────┘  └──────────┬───────────┘     │
│         │                 │                      │                  │
│  ┌──────▼─────────────────▼──────────────────────▼───────────────┐  │
│  │  MCP Server Host (planned)                                    │  │
│  │  Spawns + manages MCP server processes                        │  │
│  │  Adapters talk to MCP servers for polling + sending           │  │
│  │  Agents call MCP tools directly for mid-workflow actions      │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
└──────────┬─────────────────┬────────────────────────────────────────┘
           │                 │
           ▼                 ▼
┌────────────────┐  ┌────────────────┐
│    PIPELIT     │  │   OPENCODE    │
│   PLATFORM     │  │   SERVER      │
│                │  │               │
│ Workflow engine│  │ AI-assisted   │
│ Agent backends │  │ code editing  │
│ REST API       │  │               │
│ WebSocket      │  │               │
└───────┬────────┘  └────────────────┘
        │
        │ API + WebSocket
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       USER INTERFACES                               │
│                                                                     │
│  ┌────────────────────┐  ┌────────────────────────────────────────┐ │
│  │  React SPA         │  │  Tela Situation Room (target state)   │ │
│  │  (current GUI)     │  │                                        │ │
│  │                    │  │  ┌─ Graph ──────────┐┌─ Status ──────┐│ │
│  │  Becoming a burden │  │  │ live DAG view    ││ execution     ││ │
│  │  as node types     │  │  │ algorithmic      ││ node outputs  ││ │
│  │  multiply          │  │  │ layout           ││ errors        ││ │
│  │                    │  │  └──────────────────┘└───────────────┘│ │
│  │  Every new type    │  │  ┌─ Chat ───────────────────────────┐│ │
│  │  requires frontend │  │  │ "change scribe temp to 0.3"     ││ │
│  │  changes           │  │  │ Agent makes API calls            ││ │
│  │                    │  │  │ Graph updates live                ││ │
│  │                    │  │  │ "run it with this input"          ││ │
│  │                    │  │  │ Execution streams in status panel ││ │
│  └────────────────────┘  │  └──────────────────────────────────┘│ │
│                          └────────────────────────────────────────┘ │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  PLIT CLI (already built)                                      │ │
│  │  plit start/stop │ credentials │ api │ chat │ health           │ │
│  │  Used by: humans and privileged agents                         │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Design Principles (Established 2026-03-22)

### 1. The Smallest Unit Is a Function

`(state: dict) → dict` — the atom. Nodes are functions with contracts. Workflows are compositions of functions. Workflows embedded as nodes are fractal. The distinction between node and workflow is granularity, not kind.

### 2. Workflows Are Deterministic Pipelines

Strict typed contracts between workflows. No inter-workflow conversation. Agents reason inside nodes; orchestration stays deterministic. This is why N8N works — humans trust what they can see and predict.

### 3. REPL via Composition

Every node and workflow is independently testable. Test harness pattern: `trigger_manual → workflow node → assertion node`. No new eval endpoints — the platform primitives already provide full REPL capability.

### 4. Execution Primitives Are Sufficient

Three node types cover all execution needs:
- **Code node** — any Python function
- **Agent node** — LLM with tools (LangGraph today, CC/others future)
- **Workflow node** — calls another workflow by slug

No new runtime primitives needed. A "custom node" is just one of these three with specific configuration.

### 5. Dynamic Registry for Visibility (Not Execution)

Execution and discoverability are separate concerns. Custom nodes are "dark" without a registry. The `node_type_templates` table makes them visible in palettes, discoverable via API, and renderable on canvas. Uses versioned references (package manager pattern) backed by existing `CodeBlock`/`CodeBlockVersion` infrastructure.

### 6. Machine-Readable Contracts

`input_schema` / `output_schema` (JSON Schema) on every workflow. Foundation for: discovery, composition, REPL, MCP tool exposure, schema-driven config UI. The fields exist on the model today — just need populating.

### 7. Agent Backend Abstraction

Agent nodes abstract over execution backends. LangGraph today. Claude Code, OpenAI Agents SDK, others in future. Same sandbox, same `(state) → dict` contract. Configuration choice, not structural change.

---

## The MCP-First Integration Strategy

### The Insight

Millions of MCP servers already exist for Discord, Slack, Gmail, Postgres, GitHub, Jira, Notion, and more. Building custom adapters for each is unnecessary.

### Research Findings (2026-03-22)

| Integration | Best MCP Server | Stars | Cursor/Since Support |
|---|---|---|---|
| Discord | `barryyip0625/mcp-discord` | 76 | `minId`/`maxId` on search |
| Slack | `korotovsky/slack-mcp-server` | 1,470 | `filter_date_after`, cursor pagination |
| Email | `codefuturist/email-mcp` | 21 | `since` (ISO 8601), IMAP IDLE |
| Postgres | `bytebase/dbhub` | 2,372 | Via SQL WHERE clause |
| GitHub | `github/github-mcp-server` | Official | Via search queries |

**Key finding:** No MCP server supports push/subscription. All are request-response. The MCP protocol has no event primitive.

### The Architecture

The gateway manages two categories of processes:

```
Gateway Process Manager
  ├── Adapter Processes (own poll loops, speak gateway protocol)
  │     └── Adapter talks to MCP server for polling + sending
  │
  └── MCP Server Processes (passive tool providers)
        └── Available to adapters, agents, and config UI
```

Three usage patterns:

| Pattern | Adapter | MCP Server | Example |
|---|---|---|---|
| Bilateral trigger | Adapter polls MCP, pushes inbound | Passive tools | Slack, Discord, Email |
| Tool only | No adapter needed | Passive tools | Postgres, GitHub, Jira |
| Custom real-time | Adapter owns connection directly | No MCP | Telegram (already built) |

### One MCP Server, Multiple Roles

A single integration (e.g., Slack) touches four node-level concerns:

| Role | Node Type | MCP Tool Used |
|---|---|---|
| **Trigger** (inbound) | `trigger_slack` | `conversations_history` (via adapter poll) |
| **Send** (outbound) | `send_slack` | `conversations_add_message` |
| **Tool** (mid-workflow) | `slack_search` | `conversations_search_messages` |
| **Config** (UI discovery) | Config dropdowns | `channels_list`, `users_search` |

The MCP server is shared across all roles. Same auth, same process, same credential.

### What This Means for v0.6.0

The planned custom adapters (#9 Discord, #10 Slack, #11 Email) can largely be replaced by:
1. Gateway hosts MCP servers
2. Thin adapter wraps MCP server with a poll loop
3. Agent tools call MCP directly for mid-workflow actions
4. Config UI queries MCP for discovery (list channels, users, etc.)

Only truly real-time bilateral chat (Telegram) needs a custom adapter. Everything else is MCP-polled.

---

## The GUI Problem and the TUI Solution

### The Problem

The React frontend is becoming a burden. Every new node type requires:
- Backend: component registration, schemas, node_type_defs
- Frontend: NodePalette, NodeDetailsPanel, WorkflowCanvas, type definitions
- Both sides must stay in sync

With MCP-based integrations, node types will explode (15-60 tools per MCP server). The web GUI cannot keep up.

### The Solution: Conversational TUI

The Tela-based situation room replaces the "click and configure" paradigm with "observe and talk":

**Three panels:**
- **Graph** — live read-only DAG visualization (algorithmic layout, no manual positioning)
- **Status** — execution state, node outputs, errors (WebSocket-driven)
- **Chat** — natural language interface to a privileged agent

**The agent has tools to:**
- Create/modify/delete nodes and edges (platform API)
- Create/modify workflows (workflow_create)
- Run executions (chat endpoint)
- Discover existing workflows and nodes (workflow_discover)
- Query MCP servers for config values (list channels, users, etc.)

**No config panels. No forms. No per-node-type frontend code.** The editing surface is conversation. The graph and status are feedback loops.

### Why This Works

1. **Schema-driven** — `input_schema`/`output_schema` tells the agent what's valid
2. **API-complete** — every operation is already REST CRUD
3. **Live updates** — WebSocket pushes changes to graph view instantly
4. **REPL** — "run it with this input" is just a chat message
5. **Scales infinitely** — new MCP tools, new node types, new integrations require zero UI code

### What Tela Already Has

- JSX → terminal rendering pipeline (working)
- Chat client connected to Pipelit (working)
- DAG visualization prototypes (graph-boxes, graph-canvas)
- WebSocket support (working)
- Situation room design doc (PLIT-TUI-REDESIGN.md)

### What Tela Needs

- Graph view connected to live workflow data (API + WebSocket)
- Split-panel layout (graph + status + chat)
- Agent integration for conversational editing
- Schema-driven rendering for node details (when user wants to inspect)

---

## The Dynamic Node Registry — Detailed Design

### Execution vs Discoverability

**Execution primitives are sufficient.** Code nodes, agent nodes, and workflow nodes cover all runtime needs.

**The registry solves visibility.** Custom nodes exist but are "dark" without it.

### Templates with Versioned References

Registry entries are reusable types (classes). Nodes in workflows are instances that pin to a specific version.

```
node_type_templates table:
  slug, name, description, category, icon
  input_schema, output_schema
  implementation_type (code / workflow / agent)
  implementation_ref (code_block_id / workflow_slug / agent_config_id)
  current_version
  created_at, updated_at

WorkflowNode additions:
  node_type_template_slug  — which registry type
  pinned_version           — which version
```

- Execution layer unchanged — nodes run as regular code/workflow/agent
- Version pinning — updates don't break existing workflows
- Workflows with schemas auto-register as node types

### MCP-Sourced Registry Entries

When gateway hosts an MCP server, its tools can auto-register as node types:

```
MCP Server: slack-mcp (15 tools)
  → auto-registers 15 node_type_templates:
    slug: slack/conversations_history
    slug: slack/conversations_add_message
    slug: slack/channels_list
    ...
  → each has input_schema/output_schema from MCP tool definition
  → implementation_type: "mcp_tool"
  → implementation_ref: "slack-mcp:conversations_history"
```

This is the bridge between MCP ecosystem and the node palette.

---

## Connective Tissue — What's Missing

The pieces don't come together because three things are missing:

### 1. Contracts (`input_schema` / `output_schema`)

**What it unblocks:**
- Workflow-as-node composability (callers know what to send)
- Agent discovery via `workflow_discover` (agents know how to call workflows)
- Schema-driven config UI (TUI or web — render from schema, not hardcoded)
- MCP tool exposure (expose workflows as MCP tools to external clients)
- REPL testing (know what input to provide)
- Dynamic registry (schemas define the node type's ports)

**Effort:** Low. The fields exist. Just populate them on existing workflows.

### 2. MCP Hosting in Gateway

**What it unblocks:**
- Universal integrations (Slack, Discord, Email, Postgres, GitHub, etc.)
- Agent tool access to external systems (mid-workflow MCP calls)
- Config discovery (list channels, users, tables via MCP)
- MCP-backed adapter pattern (thin adapter + MCP server)
- Exposing workflows as MCP tools to external clients

**Effort:** Medium-high. Requires gateway changes: MCP process management, MCP protocol bridge, adapter-to-MCP communication.

### 3. Tela Situation Room

**What it unblocks:**
- Conversational workflow editing (no more per-node-type frontend code)
- Live graph visualization
- REPL via chat
- Eliminates the GUI bottleneck entirely
- Power user workflow — keyboard-driven, scriptable

**Effort:** Medium. Core pieces exist (chat client, graph rendering, WebSocket). Need: split-panel layout, API-driven graph view, agent integration.

### Dependency Graph

```
input_schema/output_schema (P0 — enables everything)
    │
    ├──→ Dynamic Node Registry
    │       │
    │       ├──→ #169 Node/Workflow Generator
    │       │       │
    │       │       └──→ #163 DSL Spec (codifies what works)
    │       │               │
    │       │               └──→ #181 Workflow Test Execution
    │       │
    │       └──→ MCP-sourced registry entries
    │               │
    │               └──→ v0.6.0 MCP-based integrations
    │
    ├──→ Tela Situation Room (schema-driven rendering)
    │
    └──→ MCP Hosting in Gateway
            │
            ├──→ MCP-backed adapters (Slack, Discord, Email)
            ├──→ Agent MCP tool access (mid-workflow)
            └──→ Expose workflows as MCP tools (inbound)
```

### Recommended Execution Order

```
Phase 1: Foundation
  → Populate input_schema/output_schema on existing workflows
  → Tela situation room MVP (graph + chat, schema-driven)

Phase 2: Composition
  → Dynamic Node Registry (node_type_templates table)
  → #169 Node/Workflow Generator (uses composition + registers outputs)
  → #163 DSL Spec (codifies proven patterns)

Phase 3: Universal Integration
  → MCP hosting in gateway
  → MCP-backed adapter pattern
  → MCP-sourced registry entries
  → v0.6.0 integrations via MCP (Slack, Discord, Email)

Phase 4: Full Vision
  → Agent backend abstraction (CC alongside LangGraph)
  → Expose workflows as MCP tools to external clients
  → #181 Workflow test execution
  → Self-modifying system (privileged agents install + configure via plit CLI)
```

---

## What We Proved Today (2026-03-22)

1. **Workflow composition works** — split workflow-generator into requirements-gatherer + workflow-generator-b, end-to-end execution validated
2. **Data passing works** — `input_mapping` on workflow nodes, trigger_wf flattens payload
3. **The platform primitives are sufficient** — no new node types needed for composition
4. **The MCP ecosystem covers most integrations** — cursor/pagination support exists
5. **The GUI is the bottleneck** — not the engine, not the gateway, not the architecture
6. **The TUI + conversational editing is the path forward** — no per-node-type frontend code

---

## Open Questions

1. **MCP protocol for triggers** — MCP has no event/subscription primitive. Gateway-driven polling via adapters is the current answer. Is there a better pattern emerging in the MCP ecosystem?

2. **Tela graph layout algorithm** — Sugiyama (layered) vs force-directed vs custom? Need to handle parallel branches, merge points, conditional routing. Left-to-right vs top-down?

3. **Agent for conversational editing** — Which agent tools are needed beyond platform_api? How does the agent understand workflow semantics (not just CRUD)?

4. **Schema evolution** — When input_schema/output_schema change on a workflow, what happens to upstream callers that depend on the old contract? Semver for workflows?

5. **Cross-repo coordination** — Changes span pipelit, plit, msg-gateway, and tela. What's the release coordination strategy?
