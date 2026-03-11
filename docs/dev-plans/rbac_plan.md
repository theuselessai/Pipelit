# Plan: User Roles and RBAC (admin / normal)

> **Created:** 2026-03-11
> **Status:** Draft
> **Issue:** #136
> **Milestone:** v0.3.0
> **Depends on:** Nothing
> **Blocked by:** #137 (User management API) depends on this

---

## 1. Problem

Pipelit has no role or permission system. All authenticated users have equal access to everything — workflows, credentials, executions, schedules, memory, and agent users. Several endpoint groups have zero user filtering:

- **Schedules** — any user sees/modifies all scheduled jobs
- **Memory** — any user sees/deletes all facts, episodes, procedures, checkpoints
- **Agent users** — any user can list/delete all agent users

The `is_agent` flag on UserProfile distinguishes agent-created users from human users, but this concept is being removed — agents will use named API keys belonging to human users instead (#137).

---

## 2. Design Decisions (Resolved)

| Decision | Choice | Rationale |
|---|---|---|
| Number of roles | 2: `admin` \| `normal` | Simple, sufficient for v0.3.0 |
| Agent role | None — removed entirely | Agents use human user's API keys (#137) |
| `is_agent` flag | Drop in this PR | No longer needed; agent users going away |
| `create_agent_user` component | Delete | Replaced by named API keys in #137 |
| `/users/agents/` endpoints | Delete | Replaced by `/users/` CRUD in #137 |
| Agent Users frontend page | Delete | No more agent user concept |
| Credential access | Own + admin override | Normal users manage own credentials; admins see all |
| Schedule access | Ownership filtering | Normal users see schedules for own workflows; admins see all |
| Memory access | Ownership filtering | Normal users see memory scoped to own workflows; admins see all |
| Per-resource ACLs | Out of scope | v0.4.0+ via WorkflowCollaborator enforcement |
| First user | Auto-admin (setup wizard) | Already the only user creation path |
| Existing users | Admin on migration | Preserves current access levels |
| Startup enforcement | None | Auth dependencies handle everything at request time |
| WorkflowCollaborator table | Delete (model + table) | Unused, simplifies `get_workflow()` to pure ownership + admin bypass |

---

## 3. Permission Matrix

| Endpoint group | admin | normal |
|---|---|---|
| **Credentials** (CRUD) | all credentials | own only (`user_profile_id`) |
| **Workflows** (CRUD) | all workflows | own only |
| **Workflow execution** | all workflows | own workflows |
| **Executions** (list/detail) | all executions | own only (`Workflow.owner_id`) |
| **Schedules** (CRUD) | all schedules | own workflow's schedules |
| **Memory** (facts/episodes/etc) | all memory | own workflow's memory |
| **Chat / messaging** | all workflows | own workflows |
| **Own API key** | yes | yes |
| **Own profile / password** | yes | yes |
| **Other users' data** | yes | no (403) |
| **System settings** | yes | no (403) |

"Own" = workflows where `Workflow.owner_id == current_user.id`.

---

## 4. Current State (What Exists)

### Already scoped by user (no RBAC work needed beyond admin override)

| Endpoint group | File | Current filtering |
|---|---|---|
| Workflows | `api/workflows.py` | `get_workflow()` checks `owner_id` + `WorkflowCollaborator` (collaborator check being removed) |
| Credentials | `api/credentials.py` | Filters by `user_profile_id` on all endpoints |
| Executions | `api/executions.py` | Joins `Workflow`, filters by `Workflow.owner_id` |
| Workspaces | `api/workspaces.py` | Filters by `user_profile_id` |
| Nodes/Edges | `api/nodes.py` | Uses `get_workflow()` helper (inherits ownership check) |

### No user filtering (gaps to fix)

| Endpoint group | File | Issue |
|---|---|---|
| Schedules | `api/schedules.py` | Returns all jobs for any authenticated user |
| Memory | `api/memory.py` | Returns all facts/episodes/procedures/checkpoints globally |
| Agent users | `api/users.py` | Global list/delete — being removed entirely |

### `is_agent` usage (all to be removed)

| File | Line | Usage | Action |
|---|---|---|---|
| `models/user.py` | L29 | Column definition | Drop column |
| `components/create_agent_user.py` | L88 | Sets `is_agent=True` | Delete entire component |
| `components/get_totp_code.py` | L43 | Filters `is_agent == True` | Remove `is_agent` filter (look up any user) |
| `api/users.py` | L27, L68, L98 | Filters `is_agent == True` | Delete entire file |
| `tests/test_mfa.py` | L392, L482, L510, L565, L585 | Test fixtures | Update fixtures |
| `tests/test_api_extended.py` | L421, L441, L461 | Test fixtures | Update fixtures |
| `alembic/versions/00bb091e6dd1_*` | L27 | Migration adding column | No change (historical) |

---

## 5. Implementation Plan

### Phase 1: Model + Migration

#### 1a. UserProfile model changes (`platform/models/user.py`)

- Add `role: Mapped[str] = mapped_column(String(10), default="normal")`
- Remove `is_agent: Mapped[bool]` column
- Keep `created_by_agent_id` FK (still useful for tracking lineage)

#### 1a-2. Delete WorkflowCollaborator model (`platform/models/workflow.py`)

- Remove `WorkflowCollaborator` class
- Remove `collaborators` relationship from `Workflow` model
- Drop `workflow_collaborators` table in migration

#### 1b. Alembic migration (single file, batch operations)

```
1. batch_alter_table("user_profiles"):
   - add_column("role", String(10), server_default="normal", nullable=False)
2. execute("UPDATE user_profiles SET role = 'admin'")  -- all existing users become admin
3. batch_alter_table("user_profiles"):
   - drop_column("is_agent")
4. drop_table("workflow_collaborators")
```

Use `PRAGMA foreign_keys` OFF/ON for SQLite safety (matches pattern in `00bb091e6dd1`).

#### 1c. Setup wizard (`platform/api/auth.py` L100-103)

Add `role="admin"` to the UserProfile constructor in the setup endpoint.

---

### Phase 2: Auth Dependencies

#### 2a. `require_admin` dependency (`platform/auth.py`)

New FastAPI dependency that wraps `get_current_user` and checks `role == "admin"`. Returns 403 if not admin.

#### 2b. Update `get_workflow` helper (`platform/api/_helpers.py`)

- Remove `WorkflowCollaborator` subquery entirely
- Admin: query by slug only (no ownership check)
- Normal: query by slug + `Workflow.owner_id == profile.id`

#### 2c. Credential helper

Add similar admin-bypass pattern for credential lookups: admin sees all, normal sees own (`user_profile_id == profile.id`).

---

### Phase 3: Endpoint Protection

#### 3a. Credentials (`platform/api/credentials.py`)

- Admin: remove `user_profile_id` filter (see all)
- Normal: keep existing filter (own only)
- No `require_admin` — both roles can access, just different scope

#### 3b. Executions (`platform/api/executions.py`)

- Admin: remove `Workflow.owner_id` filter (see all)
- Normal: keep existing filter (own only)

#### 3c. Schedules (`platform/api/schedules.py`)

- Add join to `Workflow` table
- Admin: no workflow ownership filter
- Normal: filter `Workflow.owner_id == profile.id`
- Apply to: list, get, patch, delete, pause, resume, batch-delete

#### 3d. Memory (`platform/api/memory.py`)

Memory tables (`MemoryFact`, `MemoryEpisode`, `MemoryProcedure`, `MemoryUser`) need a scoping strategy. Check if these tables have a workflow or user FK to filter on. If not, make memory endpoints admin-only as an interim measure until memory is properly scoped in v0.4.0.

#### 3e. Workflows (`platform/api/workflows.py`)

- List: admin sees all workflows, normal sees own only (already filtered)
- Single/patch/delete: `get_workflow()` helper handles this via Phase 2b

#### 3f. Chat (`platform/api/executions.py` chat endpoints)

Already gated by `get_workflow()` — admin bypass in Phase 2b covers this.

---

### Phase 4: Removals

#### 4a. Delete `create_agent_user` component

- Remove `platform/components/create_agent_user.py`
- Remove registration from `components/__init__.py`
- Remove from `NODE_TYPE_REGISTRY` / `schemas/node_type_defs.py`
- Remove from `schemas/node.py` component type literal
- Remove from `models/node.py` polymorphic identity + config mapping
- Remove from `SUB_COMPONENT_TYPES` in `services/builder.py` and `services/topology.py`
- Update `components/platform_api.py` docstring (references "call create_agent_user")
- Update `components/whoami.py` instructions (references "use create_agent_user")

#### 4b. Delete `/users/agents/` endpoints

- Remove `platform/api/users.py` (entire file)
- Remove router registration from `platform/main.py`

#### 4c. Delete Agent Users frontend page

- Remove route from `App.tsx`
- Remove page component
- Remove sidebar navigation entry
- Remove `api/users.ts` hooks (or the agent-specific parts)

#### 4d. Update `get_totp_code` component

- Remove `is_agent == True` filter on L43 (look up any user by username)
- No other changes needed — the tool is still useful for MFA verification flows

---

### Phase 5: Tests

#### 5a. New RBAC tests (new file: `tests/test_rbac.py`)

- Admin can list all workflows, credentials, executions, schedules
- Normal user sees only own workflows, credentials, executions, schedules
- Normal user gets 403 on admin-only endpoints
- Normal user cannot access another user's workflow (404)
- Admin can access any user's workflow
- Setup wizard creates admin user

#### 5b. Update existing tests

- `tests/test_mfa.py` — remove `is_agent=True` from fixtures, use `created_by_agent_id` if needed
- `tests/test_api_extended.py` — remove `is_agent=True` from fixtures
- Any test creating UserProfile with `is_agent` — update or remove

---

## 6. Files Changed

| File | Change type |
|---|---|
| `models/user.py` | Edit: add `role`, remove `is_agent` |
| `models/workflow.py` | Edit: remove `WorkflowCollaborator` class + relationship |
| `auth.py` | Edit: add `require_admin` dependency |
| `api/_helpers.py` | Edit: admin bypass in `get_workflow` |
| `api/auth.py` | Edit: set `role="admin"` in setup |
| `api/credentials.py` | Edit: admin override scope |
| `api/executions.py` | Edit: admin override scope |
| `api/schedules.py` | Edit: add ownership filtering + admin override |
| `api/memory.py` | Edit: add scoping or admin-only |
| `api/workflows.py` | Edit: admin sees all in list |
| `api/users.py` | **Delete** |
| `components/create_agent_user.py` | **Delete** |
| `components/__init__.py` | Edit: remove `create_agent_user` import |
| `components/get_totp_code.py` | Edit: remove `is_agent` filter |
| `components/platform_api.py` | Edit: remove `create_agent_user` references in docstring |
| `components/whoami.py` | Edit: remove `create_agent_user` references in instructions |
| `models/node.py` | Edit: remove `create_agent_user` polymorphic identity + config mapping |
| `schemas/node.py` | Edit: remove `create_agent_user` from component type literal |
| `schemas/node_type_defs.py` | Edit: remove `create_agent_user` registration |
| `services/builder.py` | Edit: remove `create_agent_user` from `SUB_COMPONENT_TYPES` |
| `services/topology.py` | Edit: remove `create_agent_user` from `SUB_COMPONENT_TYPES` |
| `alembic/versions/xxx_add_role_drop_is_agent.py` | **New**: migration |
| `tests/test_rbac.py` | **New**: RBAC permission tests |
| `tests/test_mfa.py` | Edit: remove `is_agent` from fixtures, remove `create_agent_user` tests |
| `tests/test_api_extended.py` | Edit: remove `is_agent` from fixtures |
| `tests/test_components_db.py` | Edit: remove `create_agent_user` tests |
| `tests/test_topology.py` | Edit: remove `create_agent_user` from `SUB_COMPONENT_TYPES` assertion |
| `main.py` | Edit: remove agent users router |
| `frontend/src/App.tsx` | Edit: remove agent users route |
| `frontend/src/features/users/` | **Delete**: agent users page |
| `frontend/src/api/users.ts` | **Delete** or edit: remove agent hooks |

---

## 7. Order of Implementation

1. **Branch**: `feature/rbac-roles`
2. **Phase 1**: Model + migration (smallest blast radius, can test independently)
3. **Phase 2**: Auth dependencies (`require_admin`, `get_workflow` admin bypass)
4. **Phase 4**: Removals (delete agent user system — unblocks is_agent column drop)
5. **Phase 3**: Endpoint protection (apply ownership filtering + admin overrides)
6. **Phase 5**: Tests (alongside each phase, final RBAC test suite at end)
7. **Verify**: all existing tests pass, CI green
8. **PR**: squash merge to master

---

## 8. Out of Scope

- Multi-key API system → #137
- User CRUD endpoints (create/list/update/delete users) → #137
- Named API keys → #137
- Removing agent user concept from deep agent workflows → #137
- Workflow sharing / collaboration (if needed, rebuild from scratch) → v0.4.0
- Per-resource ACLs → v0.4.0
- Custom roles → v0.4.0
- Multi-tenant workspace isolation → v0.4.0
