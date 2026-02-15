# Concepts

This section explains the core ideas behind Pipelit. Understanding these concepts will help you design effective workflows and get the most out of the platform.

<div class="grid" markdown>

<div class="card" markdown>

### [Workflows](workflows.md)

The central organizing unit in Pipelit. A workflow is a visual pipeline you design on a canvas, connecting triggers, agents, tools, and logic nodes into an executable graph.

</div>

<div class="card" markdown>

### [Nodes & Edges](nodes-and-edges.md)

Nodes are the building blocks of workflows. Edges are the connections between them. Together they form a typed, directed graph with validated data flow.

</div>

<div class="card" markdown>

### [Triggers](triggers.md)

Triggers are specialized nodes that initiate workflow execution. Pipelit supports chat, Telegram, manual, scheduled, workflow, and error triggers -- all as first-class nodes on the canvas.

</div>

<div class="card" markdown>

### [Agents](agents.md)

LLM-powered nodes that reason, call tools, and produce responses. Agents use LangGraph's ReAct architecture and support conversation memory, tool calling, and model selection.

</div>

<div class="card" markdown>

### [Tools](tools.md)

Sub-component nodes that give agents capabilities: execute shell commands, make HTTP requests, search the web, evaluate math, and check the current time.

</div>

<div class="card" markdown>

### [Expressions](expressions.md)

Jinja2 template expressions let you reference upstream node outputs in system prompts and configuration fields. Use `{{ nodeId.portName }}` syntax with filters and fallbacks.

</div>

<div class="card" markdown>

### [Execution](execution.md)

How workflows run: trigger-scoped compilation, topological node ordering, real-time WebSocket status updates, and result propagation through the graph.

</div>

<div class="card" markdown>

### [Memory](memory.md)

Persistent knowledge storage across executions. Conversation memory gives agents continuity. Global memory stores facts, episodes, and procedures that any agent can recall.

</div>

<div class="card" markdown>

### [Epics & Tasks](epics-and-tasks.md)

A task delegation system for multi-agent coordination. Epics group related tasks with budgets and deadlines. Agents can create, query, and update them autonomously.

</div>

<div class="card" markdown>

### [Cost Tracking](cost-tracking.md)

Per-execution token counting and USD cost calculation. Tracks input/output tokens across all LLM calls with Epic-level budget enforcement.

</div>

<div class="card" markdown>

### [Scheduler](scheduler.md)

Self-rescheduling recurring execution without external cron. Configurable intervals, repeat counts, retry with exponential backoff, pause/resume, and crash recovery.

</div>

<div class="card" markdown>

### [Security](security.md)

Authentication, authorization, credential encryption, and sandboxed code execution. Bearer token API keys, Fernet-encrypted secrets, and restricted execution environments.

</div>

</div>
