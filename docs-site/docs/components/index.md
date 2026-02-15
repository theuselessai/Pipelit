# Components

Pipelit provides approximately 42 component types that serve as the building blocks for workflows. Each component type represents a distinct piece of functionality -- from receiving events to reasoning with LLMs to routing data through conditional logic.

Components are organized into seven categories, each with a distinct role in the workflow pipeline.

---

<div class="grid" markdown>

<div class="card" markdown>

### [Triggers](triggers/index.md) <span class="badge badge--trigger">6 types</span>

Entry points that initiate workflow execution. Triggers are first-class nodes on the canvas -- they receive events from external sources (Telegram, chat, schedules) and pass data downstream.

**Chat** | **Telegram** | **Manual** | **Schedule** | **Workflow** | **Error**

</div>

<div class="card" markdown>

### [AI](ai/index.md) <span class="badge badge--ai">4 types</span>

LLM-powered nodes that reason, classify, route, and extract structured data. AI nodes connect to an AI Model sub-component and optionally to tools and memory.

**Agent** | **Categorizer** | **Router** | **Extractor**

</div>

<div class="card" markdown>

### [Tools](tools/index.md) <span class="badge badge--tool">5 types</span>

Sub-component nodes that provide capabilities to agents via LangChain tool calling. When an agent invokes a tool, the tool node executes and returns results to the agent's reasoning loop.

**Run Command** | **HTTP Request** | **Web Search** | **Calculator** | **Date & Time**

</div>

<div class="card" markdown>

### [Self-Awareness](self-awareness/index.md) <span class="badge badge--ai">11 types</span>

Components that give agents awareness of the platform itself -- creating API credentials, inspecting their own identity, managing epics and tasks, spawning child workflows, and monitoring system health.

**Create Agent User** | **Platform API** | **WhoAmI** | **Get TOTP Code** | **Epic Tools** | **Task Tools** | **Spawn & Await** | **Workflow Create** | **Workflow Discover** | **Scheduler Tools** | **System Health**

</div>

<div class="card" markdown>

### [Memory](memory/index.md) <span class="badge badge--ai">3 types</span>

Persistent knowledge storage that agents can read from and write to across executions. Includes user identification for personalized interactions.

**Memory Read** | **Memory Write** | **Identify User**

</div>

<div class="card" markdown>

### [Logic](logic/index.md) <span class="badge badge--logic">9 types</span>

Flow-control nodes for branching, looping, filtering, merging, and orchestrating execution order. These nodes shape how data flows through the workflow graph.

**Switch** | **Code** | **Merge** | **Filter** | **Loop** | **Wait** | **Human Confirmation** | **Aggregator** | **Subworkflow**

</div>

<div class="card" markdown>

### [Sub-Components](sub-components/index.md) <span class="badge badge--sub">3 types</span>

Configuration nodes that attach to AI nodes via special handles. They provide model selection, output parsing, and code execution capabilities.

**AI Model** | **Output Parser** | **Code Execute**

</div>

</div>

---

## How Components Work

Every component on the canvas is a **node** in the workflow graph. Nodes connect to each other via **edges** that carry typed data between output ports and input ports.

### Port System

Each component type defines its **input ports** and **output ports** with specific data types:

| Data Type | Description |
|-----------|-------------|
| `STRING` | Plain text |
| `NUMBER` | Numeric value |
| `BOOLEAN` | True/false |
| `OBJECT` | JSON object |
| `ARRAY` | JSON array |
| `MESSAGES` | LangGraph message list |
| `ANY` | Accepts any type |

When you draw an edge between two nodes, Pipelit validates that the source output port type is compatible with the target input port type. Incompatible connections are rejected with a 422 error.

### Execution Model

Components follow a consistent execution pattern:

1. The **orchestrator** resolves Jinja2 expressions in the component's configuration (system prompt, extra config).
2. The component's `run()` function executes with the current workflow state.
3. The component returns a flat dict with port values (e.g., `{"output": "result text"}`).
4. The orchestrator wraps non-underscore keys into `node_outputs[node_id]` for downstream access.
5. A `node_status` WebSocket event is published with the result status.

### Sub-Component Connections

AI nodes connect to sub-components via special diamond-shaped handles at the bottom of the node:

| Handle | Color | Purpose |
|--------|-------|---------|
| model | Blue (#3b82f6) | AI Model connection (required) |
| tools | Green (#10b981) | Tool connections |
| memory | Amber (#f59e0b) | Memory connections |
| output_parser | Slate (#94a3b8) | Output parser connection |

### Accessing Upstream Data

Use Jinja2 template expressions to reference data from upstream nodes:

```
{{ trigger.text }}
{{ nodeId.portName }}
{{ agent_abc123.output | upper }}
```

The `trigger` shorthand always refers to whichever trigger fired the current execution.
