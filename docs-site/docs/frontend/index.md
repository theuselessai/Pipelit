# Frontend Guide

Pipelit ships with a **React single-page application** (SPA) that provides the full visual interface for designing workflows, managing credentials, inspecting executions, and more.

## Tech Stack

| Library | Role |
|---------|------|
| **React 18** + **Vite** | Component framework and build toolchain |
| **TypeScript** | Type-safe frontend codebase |
| **Shadcn/ui** | Accessible UI primitives (dialogs, tables, selects, etc.) |
| **@xyflow/react v12** (React Flow) | Drag-and-drop workflow canvas |
| **TanStack Query** | Server state management with caching and mutations |
| **React Router** | Client-side routing |
| **CodeMirror 6** | Modal editors with Jinja2 syntax highlighting |
| **Lucide React** + **Font Awesome** | Icons in the sidebar and on canvas nodes |

## Source Structure

```
platform/frontend/src/
├── api/            # TanStack Query hooks + fetch client
├── components/     # Shared components (ExpressionTextarea, VariablePicker, layout)
├── features/       # Page-level feature modules
│   ├── auth/       # Login, setup, AuthProvider
│   ├── workflows/  # Dashboard + editor (canvas, palette, details panel)
│   ├── credentials/
│   ├── executions/
│   ├── epics/
│   ├── memories/
│   ├── users/
│   └── settings/
├── hooks/          # useTheme, useWebSocket
├── lib/            # WebSocket manager, Jinja2 highlighting plugin
├── types/          # TypeScript type definitions
├── App.tsx         # Route definitions
└── main.tsx        # QueryClient + AuthProvider + Router
```

## Routes

All pages except `/login` and `/setup` are protected by authentication. The authenticated layout wraps pages in a collapsible sidebar with navigation links.

| Route | Page | Description |
|-------|------|-------------|
| `/login` | Login | Username and password form |
| `/setup` | Setup | First-time admin account creation |
| `/` | [Dashboard](dashboard.md) | Workflow list with create/delete |
| `/workflows/:slug` | [Workflow Editor](editor.md) | Three-panel canvas editor |
| `/credentials` | [Credentials](credentials-ui.md) | API key and bot token management |
| `/executions` | [Executions](executions-ui.md) | Execution list with status filters |
| `/executions/:id` | [Execution Detail](executions-ui.md#execution-detail) | Per-execution logs and output |
| `/epics` | [Epics](epics-ui.md) | Epic list with task tracking |
| `/epics/:epicId` | [Epic Detail](epics-ui.md#epic-detail) | Tasks, budget, and cost breakdown |
| `/memories` | [Memories](memories-ui.md) | Facts, episodes, checkpoints, procedures, users |
| `/agent-users` | Agent Users | Agent user management |
| `/settings` | [Settings](settings-ui.md) | Theme and MFA configuration |

## Running the Frontend

### Development Mode

In development, Vite runs a hot-reloading dev server that proxies API requests to the FastAPI backend.

```bash
cd platform/frontend
npm install
npm run dev
```

The Vite dev server starts on `http://localhost:5173` and proxies all `/api` requests to the FastAPI backend at `http://localhost:8000`. You need both the FastAPI server and the Vite dev server running simultaneously.

!!! tip "Hot module replacement"
    Vite provides instant hot module replacement (HMR). Saving a React component file updates the browser immediately without a full page reload.

### Production Mode

For production, build the frontend into static files that FastAPI serves directly.

```bash
cd platform/frontend
npm run build
```

This compiles the SPA into `platform/frontend/dist/`, which FastAPI mounts as a static file directory. No separate frontend server is required -- access everything through the FastAPI process at port 8000.

## Authentication Flow

The frontend uses **Bearer token authentication**. On login, the client sends credentials to `POST /api/v1/auth/token/` and receives an API key. This key is stored in memory (via `AuthProvider` context) and injected into all subsequent API requests via the `Authorization: Bearer <key>` header.

A `401 Unauthorized` response from any API call triggers an automatic redirect to the login page.

## Real-time Updates via WebSocket

The frontend maintains a **single persistent WebSocket connection** to the backend at `/ws/?token=<api_key>`. This connection, managed by the `WebSocketManager` singleton, provides:

- **Automatic reconnection** with exponential backoff
- **Channel subscriptions** -- subscribe to `workflow:<slug>` or `execution:<id>` channels
- **TanStack Query cache updates** -- incoming WebSocket events directly update the query cache, eliminating the need for polling or refetching after mutations

Event types received over WebSocket include:

- `node_created`, `node_updated`, `node_deleted` -- canvas mutations
- `edge_created`, `edge_updated`, `edge_deleted` -- connection changes
- `workflow_updated` -- workflow metadata changes
- `node_status` -- per-node execution status (pending, running, success, failed, skipped)
- `execution_completed`, `execution_failed`, `execution_interrupted` -- execution lifecycle

## What's Next?

- [Dashboard](dashboard.md) -- Manage your workflows
- [Workflow Editor](editor.md) -- Design workflows on the visual canvas
- [Executions](executions-ui.md) -- Monitor and inspect workflow runs
