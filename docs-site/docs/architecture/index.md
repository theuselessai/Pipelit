# Architecture

This section provides a deep dive into Pipelit's internal architecture, covering everything from the high-level system topology to the low-level execution mechanics.

## Section Overview

| Page | Description |
|------|-------------|
| [System Overview](system-overview.md) | High-level diagram of how all system components connect: FastAPI, Redis, RQ, LangGraph, WebSocket, and the React frontend. |
| [Backend](backend.md) | Backend architecture details -- FastAPI app structure, SQLAlchemy 2.0 models with polymorphic inheritance, Pydantic schemas, RQ background processing, Redis, and Alembic migrations. |
| [Execution Engine](execution-engine.md) | How workflows are compiled and executed: the orchestrator, builder, topology analyzer, executor, Jinja2 expression resolver, and LangGraph state management. |
| [Node I/O](node-io.md) | The standardized type system for node inputs and outputs: DataType enum, PortDefinition, NodeTypeSpec registry, edge validation, and component output conventions. |
| [WebSocket System](websocket-system.md) | The global authenticated WebSocket architecture: Redis pub/sub fan-out, subscription protocol, event types, and the frontend WebSocketManager singleton. |
| [Context Management](context-management.md) | How the platform manages LLM context windows: token counting, pre-call trimming, agent output isolation, conversation continuity, and sub-workflow context scoping. |
| [Multi-Agent Delegation](multi-agent.md) | Hierarchical multi-agent task delegation: the epic/task registry, spawn_and_await for child workflow execution, workflow discovery, and the YAML DSL for programmatic workflow creation. |
| [Workflow DSL](workflow-dsl.md) | The YAML-based declarative workflow definition language: step types, triggers, model resolution, implicit flow, fork-and-patch mode, and the DSL compiler pipeline. |
| [Self-Improving Agents](self-improving.md) | The vision and roadmap for self-aware, self-evolving agents: self-inspection, self-modification with guardrails, guided learning, memory-driven emergence, and the protection layer. |

## Key Design Principles

Pipelit's architecture follows several guiding principles:

- **Triggers are nodes.** There is no separate trigger subsystem. Triggers (chat, Telegram, webhook, scheduler) are first-class workflow nodes with the same lifecycle as any other node.
- **Workflows over agents.** The unit of delegation is workflows, not individual agents. Workflows are composable graphs that subsume agent capabilities.
- **Trigger-scoped execution.** When a trigger fires, only the nodes reachable downstream from that trigger are compiled and executed. Unconnected nodes on the same canvas are ignored.
- **Component output convention.** Components return flat dicts. The orchestrator handles wrapping, state management, and side effects via underscore-prefixed keys.
- **Real-time by default.** All mutations and execution events are broadcast via WebSocket. The frontend never polls.
