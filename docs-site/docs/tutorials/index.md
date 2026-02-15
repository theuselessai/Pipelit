# Tutorials

Hands-on, step-by-step guides for building real workflows in Pipelit. Each tutorial walks you through a complete project from start to finish.

!!! tip "Prerequisites"
    All tutorials assume you have Pipelit [installed](../getting-started/installation.md) and [running](../getting-started/first-run.md), with at least one [LLM credential](../frontend/credentials-ui.md) configured. If you have not done this yet, start with the [Getting Started](../getting-started/index.md) guide.

---

<div class="grid" markdown>

<div class="card" markdown>

### [Build a Conversational Chatbot](chat-agent.md)

<span class="badge badge--ai">Beginner</span>

Create a chat-based agent with conversation memory. Learn the fundamentals of triggers, agents, AI models, and the chat interface.

**You will learn:** Chat triggers, agent nodes, AI model connection, system prompts, conversation memory.

</div>

<div class="card" markdown>

### [Set Up a Telegram Bot](telegram-bot.md)

<span class="badge badge--trigger">Beginner</span>

Connect Pipelit to Telegram via BotFather. Build a bot that receives messages, processes them with an LLM agent, and sends replies automatically.

**You will learn:** Telegram credentials, webhook setup, Telegram triggers, automatic message delivery.

</div>

<div class="card" markdown>

### [Conditional Routing with Switch Nodes](conditional-routing.md)

<span class="badge badge--logic">Intermediate</span>

Route messages to different agents based on content classification. Use a categorizer to analyze input and switch nodes to direct traffic to specialized handlers.

**You will learn:** Categorizer nodes, switch nodes, conditional edges, multi-branch workflows.

</div>

<div class="card" markdown>

### [Scheduled Workflow Execution](scheduled-workflow.md)

<span class="badge badge--trigger">Intermediate</span>

Run workflows on a recurring schedule without external cron. Configure intervals, retries, and monitoring for automated tasks like health checks and reports.

**You will learn:** Schedule triggers, the Schedules API, interval configuration, retry and backoff, pause/resume.

</div>

<div class="card" markdown>

### [Multi-Agent Delegation](multi-agent.md)

<span class="badge badge--ai">Advanced</span>

Build an orchestrator agent that decomposes complex tasks into epics and individual work items, then delegates them to child workflows using spawn_and_await.

**You will learn:** Epics and tasks, spawn_and_await, cost tracking, multi-workflow coordination.

</div>

<div class="card" markdown>

### [Self-Improving Agent](self-improving-agent.md)

<span class="badge badge--tool">Advanced</span>

Create an agent that can inspect its own configuration, modify its system prompt, and create new workflows programmatically -- all through the platform API.

**You will learn:** WhoAmI, create_agent_user, platform_api tools, self-modification patterns, safety considerations.

</div>

<div class="card" markdown>

### [Programmatic Workflow Creation with YAML DSL](yaml-dsl.md)

<span class="badge badge--tool">Advanced</span>

Define entire workflows in YAML and have agents build them programmatically. Learn the DSL structure, node and edge definitions, and how agents use the workflow_create tool.

**You will learn:** YAML DSL syntax, workflow_create tool, programmatic workflow construction.

</div>

</div>

---

## Suggested learning path

If you are new to Pipelit, work through the tutorials in order:

1. **[Chatbot](chat-agent.md)** -- learn the core concepts
2. **[Telegram Bot](telegram-bot.md)** -- add an external channel
3. **[Conditional Routing](conditional-routing.md)** -- build branching logic
4. **[Scheduled Workflows](scheduled-workflow.md)** -- automate recurring tasks
5. **[Multi-Agent](multi-agent.md)** -- coordinate multiple workflows
6. **[Self-Improving Agent](self-improving-agent.md)** -- enable autonomous evolution
7. **[YAML DSL](yaml-dsl.md)** -- programmatic workflow creation

Each tutorial builds on concepts introduced in earlier ones.
