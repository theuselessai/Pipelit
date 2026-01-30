# React GUI Implementation Plan

> **Status: Implemented** — All phases (0-10) completed. Frontend builds successfully, all 66 backend tests pass.

Stack: React + Vite + TypeScript, Shadcn/ui, React Flow (@xyflow/react v12), TanStack Query, React Router, React Hook Form + Zod

Location: `platform/frontend/` (monorepo — single repo, Django serves built files in production)

## Phase 0: Backend Prep

### 0a. Fix node creation bug
**File:** `platform/apps/workflows/api/nodes.py` line 30
- Add `llm_credential_id=config_data.get("llm_credential_id")` to `ComponentConfig.objects.create()`

### 0b. Add CORS support
- `pip install django-cors-headers` (add to requirements)
- **File:** `platform/config/settings/base.py` — add `corsheaders` to INSTALLED_APPS, add `CorsMiddleware` before `CommonMiddleware`
- **File:** `platform/config/settings/development.py` — add `CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]`

### 0c. Add Credentials REST API
No credentials API exists yet. Create:
- **File:** `platform/apps/workflows/api/credentials.py` — CRUD router for BaseCredentials + subtypes (LLM, Telegram, Git, Tool)
- **File:** `platform/apps/workflows/api/schemas.py` — add credential schemas
- **File:** `platform/apps/workflows/api/__init__.py` — wire credentials router
- Endpoints: `GET/POST /credentials/`, `GET/PATCH/DELETE /credentials/{id}/`
- Sensitive fields (api_key, bot_token, ssh_key) returned masked on GET, accepted plaintext on POST/PATCH

### 0d. Add LLM Provider/Model list endpoints
The GUI needs to populate dropdowns for LLM provider and model selection:
- `GET /credentials/llm-providers/` — list LLMProvider records
- `GET /credentials/llm-models/` — list LLMModel records (optionally filtered by provider)

### 0e. Static files config
- **File:** `platform/config/settings/base.py` — add `STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist"]`, set `STATIC_ROOT`
- **File:** `platform/config/urls.py` — add catch-all for SPA routing (serve index.html for non-API routes)

---

## Phase 1: Scaffold React App

```bash
cd platform
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npx shadcn@latest init
npm install @tanstack/react-query react-router-dom react-hook-form @hookform/resolvers zod reactflow date-fns
npx shadcn@latest add button input label card table dialog alert dropdown-menu select textarea switch toast form tabs separator badge sheet
```

### Project structure
```
frontend/src/
├── api/
│   ├── client.ts          # fetch wrapper with Bearer token injection, 401 redirect
│   ├── auth.ts            # login(username, password) → token
│   ├── workflows.ts       # workflow CRUD hooks
│   ├── nodes.ts           # node CRUD hooks
│   ├── edges.ts           # edge CRUD hooks
│   ├── triggers.ts        # trigger CRUD hooks
│   ├── executions.ts      # execution list/detail/cancel hooks
│   └── credentials.ts     # credential CRUD hooks
├── components/
│   ├── ui/               # shadcn components (auto-generated)
│   └── layout/
│       ├── AppLayout.tsx  # sidebar + header shell
│       ├── Sidebar.tsx
│       └── ProtectedRoute.tsx
├── features/
│   ├── auth/
│   │   ├── AuthProvider.tsx
│   │   ├── LoginPage.tsx
│   │   └── useAuth.ts
│   ├── workflows/
│   │   ├── DashboardPage.tsx        # workflow list + stats
│   │   ├── WorkflowEditorPage.tsx   # main editor layout
│   │   ├── components/
│   │   │   ├── WorkflowCanvas.tsx   # React Flow canvas
│   │   │   ├── NodePalette.tsx      # drag-to-add node types
│   │   │   ├── NodeDetailsPanel.tsx # right sidebar config
│   │   │   ├── TriggerPanel.tsx     # trigger CRUD
│   │   │   ├── EdgePanel.tsx        # edge config
│   │   │   └── nodes/              # custom React Flow node renderers
│   │   └── hooks/
│   │       └── useWorkflowEditor.ts # canvas state + API sync
│   ├── credentials/
│   │   ├── CredentialsPage.tsx
│   │   └── forms/                   # per-type credential forms
│   ├── executions/
│   │   ├── ExecutionsPage.tsx
│   │   └── ExecutionDetailPage.tsx
│   └── settings/
│       └── SettingsPage.tsx
├── types/
│   └── models.ts          # TS types mirroring Django schemas
├── lib/
│   └── utils.ts
├── App.tsx                # routes
└── main.tsx               # QueryClient + AuthProvider + RouterProvider
```

### Vite config
```ts
// vite.config.ts
export default defineConfig({
  server: {
    proxy: { '/api': 'http://localhost:8000' }
  }
})
```

---

## Phase 2: API Client + Types

- `api/client.ts` — fetch wrapper that reads token from localStorage, injects `Authorization: Bearer`, handles 401 → redirect to `/login`
- `types/models.ts` — mirror all schemas from `platform/apps/workflows/api/schemas.py` + credential types
- TanStack Query hooks per resource (e.g. `useWorkflows()`, `useWorkflow(slug)`, `useCreateWorkflow()`)

---

## Phase 3: Auth + Layout

- `AuthProvider` context stores token + user state
- `LoginPage` — form → `POST /api/v1/auth/token/` → store token → redirect to dashboard
- `ProtectedRoute` — checks auth, redirects to login if missing
- `AppLayout` — sidebar nav (Workflows, Credentials, Executions, Settings) + header with user menu

### Routes
```
/login          → LoginPage
/               → DashboardPage (workflow list)
/workflows/:slug → WorkflowEditorPage
/credentials    → CredentialsPage
/executions     → ExecutionsPage
/executions/:id → ExecutionDetailPage
/settings       → SettingsPage
```

---

## Phase 4: Dashboard

- Workflow list (table with name, status badge, node/edge/trigger counts, dates)
- Create workflow dialog (name, slug auto-generated, description)
- Delete workflow confirmation
- Click row → navigate to editor

---

## Phase 5: Workflow Editor — Canvas

- Three-panel layout: left palette | center canvas | right details
- React Flow canvas loads nodes/edges from `GET /workflows/{slug}/` (detail endpoint returns embedded nodes, edges, triggers)
- Custom node components per ComponentType (color-coded, icon per type)
- Drag from palette → create node via API → add to canvas
- Connect nodes → create edge via API
- Select node → show config in right panel
- Move node → debounced position update via API
- Delete node → confirmation → API call

---

## Phase 6: Node Configuration Panel

- Right sidebar shows selected node's config
- Dynamic form based on `component_type`:
  - **chat_model / react_agent / plan_and_execute**: system_prompt textarea, LLM model selector, LLM credential selector, temperature
  - **router / categorizer**: system_prompt, extra_config JSON
  - **code**: code block selector
  - **workflow**: subworkflow selector
  - **tool_node / http_request**: extra_config JSON editor
  - Other types: generic extra_config JSON
- Entry point toggle, interrupt before/after toggles

---

## Phase 7: Triggers + Edges

- Trigger panel (tab in editor): list, create, edit, delete triggers
- Trigger form: type dropdown (Literal enum), credential selector, config JSON, active toggle, priority
- Edge panel: list edges, edit type (direct/conditional), condition mapping JSON editor
- Visual edge styling: solid for direct, dashed for conditional

---

## Phase 8: Credentials Management

- Table page listing all credentials with type badge
- Create dialog: pick type → type-specific form
- LLM: provider, api_key (masked on read), base_url
- Telegram: bot_token (masked), allowed_user_ids
- Git: provider, credential_type, fields per type
- Tool: tool_type, config JSON
- Edit/delete with confirmation

---

## Phase 9: Execution Monitoring

- Table: execution_id, workflow name, status badge, timestamps
- Filter by workflow slug, status
- Detail page: metadata, trigger payload JSON viewer, final output JSON viewer, cancel button
- Logs: table of node executions with status, duration, expandable input/output JSON
- Polling (5s interval) for running executions

---

## Phase 10: Polish

- Error boundaries, loading skeletons, toast notifications
- Dark mode via Shadcn theme
- Responsive sidebar (collapsible on mobile)

---

## Files Modified (Backend)

| File | Change |
|------|--------|
| `platform/apps/workflows/api/nodes.py:30` | Add `llm_credential_id` to create |
| `platform/apps/workflows/api/__init__.py` | Wire credentials router |
| `platform/apps/workflows/api/credentials.py` | New — credential CRUD |
| `platform/apps/workflows/api/schemas.py` | Add credential schemas |
| `platform/config/settings/base.py` | CORS, static files |
| `platform/config/settings/development.py` | CORS origins |
| `platform/config/urls.py` | SPA catch-all |
| `platform/requirements.txt` or pip install | django-cors-headers |

## Verification

1. `cd platform && python -m pytest tests/ -v` — all existing tests pass
2. `cd platform/frontend && npm run build` — build succeeds
3. Start Django + Vite dev servers, login with test user, create a workflow, add nodes, connect edges, add trigger, verify in Django admin
4. Create credentials, verify masked display
5. Run a workflow manually, check execution monitoring page
