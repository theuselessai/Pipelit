# System Overview

Pipelit is a visual workflow automation platform for building LLM-powered agents. This page describes how all major system components connect and interact.

## Architecture Diagram

```mermaid
graph TB
    subgraph Frontend["React Frontend (Vite + TypeScript)"]
        RC[React Flow Canvas]
        TQ[TanStack Query]
        WM[WebSocketManager]
    end

    subgraph API["FastAPI Application"]
        Routes[API Routers<br/>/api/v1/*]
        Auth[Bearer Token Auth]
        Pydantic[Pydantic Schemas]
        StaticMount[Static File Mount<br/>frontend/dist/]
    end

    subgraph DB["Database Layer"]
        SA[SQLAlchemy 2.0 ORM]
        Alembic[Alembic Migrations]
        SQLite[(SQLite / PostgreSQL)]
        Checkpoints[(checkpoints.db<br/>SqliteSaver)]
    end

    subgraph RedisLayer["Redis"]
        PubSub[Pub/Sub Channels]
        JobQueue[RQ Job Queue]
        Cache[Graph Cache]
        ExecState[Execution State]
    end

    subgraph Workers["RQ Workers"]
        Executor[WorkflowExecutor]
        Orchestrator[Orchestrator]
        Scheduler[Scheduler Jobs]
    end

    subgraph Execution["Execution Engine"]
        Builder[Builder<br/>Workflow → LangGraph]
        LangGraph[LangGraph<br/>CompiledGraph]
        Components[Component Library<br/>20+ node types]
        Topology[Topology Analyzer<br/>BFS reachability]
    end

    subgraph External["External Services"]
        LLM[LLM Providers<br/>OpenAI / Anthropic / etc.]
        Telegram[Telegram Bot API]
        Webhooks[Incoming Webhooks]
    end

    %% Frontend → API
    RC -->|HTTP REST| Routes
    TQ -->|fetch + Bearer token| Routes
    WM <-->|WebSocket + token| PubSub

    %% API → DB
    Routes --> Auth
    Routes --> Pydantic
    Routes --> SA
    SA --> SQLite
    Alembic --> SQLite

    %% API → Redis
    Routes -->|broadcast events| PubSub
    Routes -->|enqueue jobs| JobQueue

    %% Workers
    JobQueue -->|dequeue| Executor
    Executor --> Orchestrator
    Orchestrator --> Builder
    Builder --> Topology
    Builder --> LangGraph
    Orchestrator --> Components
    Orchestrator -->|node_status events| PubSub
    Orchestrator -->|state read/write| ExecState
    Scheduler -->|self-rescheduling| JobQueue

    %% Execution
    Components -->|LLM calls| LLM
    Components -->|checkpointer| Checkpoints
    Builder -->|cache compiled graph| Cache

    %% External triggers
    Telegram -->|incoming messages| Routes
    Webhooks -->|incoming payloads| Routes

    %% Styling
    classDef frontend fill:#e0e7ff,stroke:#4f46e5,color:#1e1b4b
    classDef api fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef db fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef redis fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    classDef worker fill:#fce7f3,stroke:#db2777,color:#831843
    classDef exec fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef external fill:#f3e8ff,stroke:#7c3aed,color:#3b0764

    class RC,TQ,WM frontend
    class Routes,Auth,Pydantic,StaticMount api
    class SA,Alembic,SQLite,Checkpoints db
    class PubSub,JobQueue,Cache,ExecState redis
    class Executor,Orchestrator,Scheduler worker
    class Builder,LangGraph,Components,Topology exec
    class LLM,Telegram,Webhooks external
```

## Component Descriptions

### React Frontend

The frontend is a React SPA built with Vite and TypeScript. It uses React Flow (v12) for the visual workflow canvas, TanStack Query for server state management, and Shadcn/ui for the component library.

- **React Flow Canvas** -- Users design workflows by placing nodes and connecting them with edges on a drag-and-drop canvas.
- **TanStack Query** -- All API calls use TanStack Query hooks. Mutations no longer invalidate queries on success; instead, updates arrive via WebSocket and are applied directly to the query cache.
- **WebSocketManager** -- A singleton that maintains a persistent WebSocket connection with exponential backoff reconnection and automatic resubscription after disconnect.

### FastAPI Application

The backend is a FastAPI application serving both the REST API and the built frontend.

- **API Routers** -- All endpoints live under `/api/v1/` and handle workflow CRUD, node/edge management, executions, credentials, chat, schedules, memory, and epics/tasks.
- **Bearer Token Auth** -- Every request is authenticated via `Authorization: Bearer <api_key>`. There is no session auth, OAuth, or basic auth.
- **Pydantic Schemas** -- Request/response validation uses Pydantic models with `Literal` types for component types, trigger types, and edge types.
- **Static File Mount** -- In production, the built frontend (`frontend/dist/`) is served directly by FastAPI.

### Database Layer

- **SQLAlchemy 2.0 ORM** -- All models use SQLAlchemy 2.0 with declarative mapping. The node system uses polymorphic inheritance for component configurations.
- **Alembic Migrations** -- Schema changes are managed via Alembic. SQLite `batch_alter_table` operations require extra care to avoid data loss.
- **SQLite / PostgreSQL** -- SQLite is the default for development; PostgreSQL is supported for production.
- **Checkpoints DB** -- A separate SQLite database (`checkpoints.db`) stores LangGraph conversation checkpoints for agent memory continuity.

### Redis

Redis serves four distinct roles in the platform:

- **Pub/Sub** -- The WebSocket broadcast system uses Redis pub/sub to fan out events across multiple API server instances and RQ workers.
- **Job Queue** -- RQ (Redis Queue) manages background job processing for workflow executions and scheduled jobs.
- **Graph Cache** -- Compiled LangGraph graphs are cached in Redis to avoid recompilation on repeated executions.
- **Execution State** -- Per-execution state (node outputs, node results, route values) is stored in Redis during execution and cleaned up after completion.

### RQ Workers

Background processing is handled by RQ workers that dequeue jobs from Redis.

- **WorkflowExecutor** -- The top-level wrapper that sets up the execution environment and delegates to the orchestrator.
- **Orchestrator** -- The core execution engine that walks through nodes in topological order, resolves expressions, executes components, and broadcasts status events.
- **Scheduler Jobs** -- Self-rescheduling jobs that implement recurring workflow execution without external cron. Each job dispatches its trigger, handles success/failure with exponential backoff, and enqueues its next run.

### Execution Engine

- **Builder** -- Compiles a `Workflow` database model into a LangGraph `CompiledGraph`. Only nodes reachable from the firing trigger are included (trigger-scoped execution via BFS).
- **LangGraph** -- The compiled graph is executed by LangGraph, which handles state transitions, message passing, and checkpointing.
- **Component Library** -- Over 20 component types implement the actual node logic: agents, tools, triggers, routing, code execution, memory, and more.
- **Topology Analyzer** -- BFS-based reachability analysis that determines which nodes are downstream from a given trigger.

### External Services

- **LLM Providers** -- Agent and AI nodes call external LLM APIs (OpenAI, Anthropic, and others) via LangChain. Credentials are stored encrypted with Fernet.
- **Telegram Bot API** -- The Telegram trigger handler receives incoming messages and dispatches them to workflows.
- **Incoming Webhooks** -- External services can trigger workflow execution via webhook endpoints.

## Request Flow

A typical user interaction flows through the system as follows:

```mermaid
sequenceDiagram
    participant User as Browser
    participant API as FastAPI
    participant DB as SQLite
    participant Redis
    participant RQ as RQ Worker
    participant LG as LangGraph
    participant LLM as LLM Provider
    participant WS as WebSocket

    User->>API: POST /workflows/{slug}/chat/
    API->>DB: Create WorkflowExecution
    API->>Redis: Enqueue RQ job
    API-->>User: 202 Accepted (execution_id)

    RQ->>Redis: Dequeue job
    RQ->>DB: Load workflow + nodes + edges
    RQ->>RQ: Build LangGraph (trigger-scoped BFS)
    RQ->>Redis: Set initial execution state

    loop For each node in topological order
        RQ->>WS: Broadcast node_status: running
        RQ->>RQ: Resolve Jinja2 expressions
        RQ->>LG: Execute component
        LG->>LLM: API call (if AI node)
        LLM-->>LG: Response
        LG-->>RQ: Component output
        RQ->>Redis: Store node_outputs
        RQ->>WS: Broadcast node_status: success
    end

    RQ->>DB: Update execution status
    RQ->>WS: Broadcast execution_completed
    RQ->>Redis: Cleanup execution state

    WS-->>User: Real-time status updates
```

## Technology Stack Summary

| Layer | Technology |
|-------|-----------|
| Frontend | React, TypeScript, Vite, React Flow v12, TanStack Query, Shadcn/ui |
| API | FastAPI, Pydantic, Uvicorn |
| ORM | SQLAlchemy 2.0 |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Migrations | Alembic |
| Background Jobs | RQ (Redis Queue) |
| Execution Engine | LangGraph |
| LLM Integration | LangChain |
| Cache / Pub/Sub / State | Redis |
| Auth | Bearer token (API keys), Fernet encryption for secrets |
