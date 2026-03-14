---
hide:
  - navigation
---

![Pipelit](assets/images/banner.png)

<div class="hero" markdown>

**Build, connect, and orchestrate LLM-powered agents — visually.**

Pipelit is a self-hosted workflow automation engine for designing LLM agent pipelines on a drag-and-drop canvas. Wire up triggers, agents, tools, and routing logic — then watch them execute in real time.

[Get Started](getting-started/index.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/theuselessai/Pipelit){ .md-button }

</div>

---

## Quick Start

Install and run via the [plit](https://github.com/theuselessai/plit) CLI:

```bash
curl -fsSL https://raw.githubusercontent.com/theuselessai/plit/main/install.sh | bash
plit init
plit start
```

Or for development, see the full [Getting Started](getting-started/index.md) guide.

---

<div class="grid grid-features" markdown>

<div class="card" markdown>

### Visual Canvas

Drag-and-drop React Flow editor with node palette, config panel, and live execution badges showing running/success/failed status on every node.

</div>

<div class="card" markdown>

### Multi-Trigger

Webhooks, chat, scheduled intervals, manual — all unified as first-class workflow nodes on the canvas. External messaging via the [msg-gateway](https://github.com/theuselessai/plit).

</div>

<div class="card" markdown>

### LLM Agents

LangGraph ReAct agents with tool-calling: shell commands, HTTP requests, web search, calculator, datetime, and more.

</div>

<div class="card" markdown>

### Conditional Routing

Switch nodes evaluate rules and route to different branches via conditional edges. AI routers classify and direct traffic.

</div>

<div class="card" markdown>

### Scheduled Execution

Recurring runs with configurable intervals, retry with exponential backoff, pause/resume, and automatic crash recovery.

</div>

<div class="card" markdown>

### Real-time Updates

Single global WebSocket pushes node status, execution events, and canvas mutations — zero polling.

</div>

<div class="card" markdown>

### Cost Tracking

Per-execution token counting and USD cost calculation with Epic-level budget enforcement. Know exactly what your agents spend.

</div>

<div class="card" markdown>

### Conversation Memory

Optional per-agent conversation persistence across executions. Global memory system with facts, episodes, and procedures.

</div>

<div class="card" markdown>

### Self-Improving Agents

Agents can read epics/tasks, spawn child workflows, modify their own graphs, and schedule future work — autonomously.

</div>

<div class="card" markdown>

### Multi-Provider LLM

Use OpenAI, Anthropic, MiniMax, GLM, or any OpenAI-compatible API. Configure credentials once, select models per agent node.

</div>

<div class="card" markdown>

### Skills

Structured Claude Code workflows for repeatable engineering tasks. Approval gates, CI analysis, review triage — automated with human oversight.

</div>

</div>

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Backend** | FastAPI, SQLAlchemy 2.0, Alembic, Pydantic, RQ (Redis Queue) |
| **Frontend** | React, Vite, TypeScript, Shadcn/ui, React Flow (@xyflow/react v12), TanStack Query |
| **Execution** | LangGraph, LangChain, Redis pub/sub, WebSocket |
| **Auth** | Bearer token API keys, RBAC (admin/normal), TOTP-based MFA |

## License

Apache 2.0
