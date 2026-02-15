# Quickstart Tutorial

Build your first workflow — a chat agent that can answer questions using the calculator and datetime tools.

## 1. Create a Workflow

From the dashboard, click **New Workflow**. Give it a name like "My First Agent" and click create. You'll be taken to the workflow editor.

## 2. Add a Chat Trigger

The workflow editor has three panels:

- **Left** — Node Palette (click to add nodes)
- **Center** — Canvas (drag to arrange, click edges to connect)
- **Right** — Node Details Panel (configure selected node)

From the Node Palette, click **Chat** under Triggers. A chat trigger node appears on the canvas.

## 3. Add an AI Model

Click **AI Model** under Sub-Components. An AI model node appears. Select it and configure:

- **Credential** — Select an LLM provider credential (you'll need to [add one](../frontend/credentials-ui.md) first)
- **Model** — Choose a model (e.g., `gpt-4o`, `claude-sonnet-4-20250514`)

## 4. Add an Agent

Click **Agent** under AI. An agent node appears. Select it and configure:

- **System Prompt** — e.g., "You are a helpful assistant. Use your tools to answer questions accurately."

## 5. Connect the Nodes

Draw connections between the nodes:

1. **Chat Trigger → Agent** — Drag from the Chat Trigger's right handle to the Agent's left handle
2. **AI Model → Agent** — Drag from the AI Model's top diamond handle to the Agent's bottom "model" diamond handle

## 6. Add Tools

Add a **Calculator** and **Date & Time** tool from the palette. Connect each to the Agent's "tools" diamond handle (green).

## 7. Test It

Click the **Chat** button in the bottom panel to open the chat interface. Send a message:

> "What is 42 * 17? Also, what time is it?"

Watch the nodes light up in real time as the agent processes your request:

- Chat Trigger → **running** (blue) → **success** (green)
- Agent → **running** → calls Calculator tool → calls DateTime tool → **success**

The agent's response appears in the chat panel with the calculated result and current time.

## What's Next?

- [Concepts](../concepts/index.md) — Understand workflows, nodes, edges, and execution
- [Telegram Bot Tutorial](../tutorials/telegram-bot.md) — Connect your agent to Telegram
- [Conditional Routing](../tutorials/conditional-routing.md) — Route messages to different agents based on content
- [Component Reference](../components/index.md) — Explore all available node types
