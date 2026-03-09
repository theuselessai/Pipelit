# Plan: msg-gateway Integration (One-Shot Migration)

## TL;DR

> **Quick Summary**: Replace Pipelit's built-in Telegram polling, chat endpoint, and browser chat UI with msg-gateway as the unified messaging layer. All protocol-specific code moves to gateway. Pipelit becomes a pure workflow execution engine: inbound webhook receives normalized messages, outbound call sends responses.
>
> **Deliverables**:
> - New `POST /api/v1/inbound` endpoint (gateway → pipelit webhook)
> - New `GatewayCredential` model replacing `TelegramCredential`
> - New `gateway_client.py` HTTP client for gateway admin + send APIs
> - Credential API syncs CRUD to gateway (tokens never stored locally)
> - Delivery service uses gateway for outbound (replaces direct Telegram API)
> - Orchestrator sends confirmation prompts via gateway on interrupt
> - `UserProfile.telegram_user_id` → `external_user_id`
> - `PendingTask.telegram_chat_id` → `chat_id` (String) + `credential_id`
> - Frontend: gateway credential CRUD, no browser chat, no poll start/stop buttons
> - Dead code removed: telegram_poller, telegram handler, chat endpoints, ChatPanel
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES — 5 waves
> **Critical Path**: T1 → T6 → T8 → T14 → T21 → F1-F4

---

## Context

### Original Request
Replace pipelit's built-in Telegram polling, chat endpoint, browser chat UI, and all protocol-specific code with msg-gateway (a standalone Rust message gateway at `../msg-gateway`) as the unified messaging layer. One-shot migration, no gradual rollout.

### Interview Summary
**Key Decisions** (21 total, across two sessions):
1. Pipelit manages credentials via gateway admin API — bot tokens never stored in Pipelit
2. Chat trigger exists but browser chat UI removed — external clients use gateway generic adapter
3. Outbound via `POST /gateway/api/v1/send` — agents never see bot tokens
4. One-shot migration, no gradual rollout
5. Frontend does NOT know about gateway — single Pipelit WebSocket only
6. Gateway unavailable = error (block operations like credential CRUD)
7. No inline keyboard / callback_query — out of scope
8. Remove browser chat completely (ChatPanel, chat API hooks, chat endpoints)
9. Inbound auth: service token (`GATEWAY_INBOUND_TOKEN`), separate dependency, NOT `get_current_user()`
10. Outbound failure: silent failure + log warning
11. UserProfile: `telegram_user_id` → `external_user_id` (user insists despite Metis risk warning)
12. thread_id format: `user_id:chat_id:workflow_id` (generic chat_id)
13. Keep both trigger types: `trigger_telegram` + `trigger_chat` stay as separate types, both backed by gateway
14. Credential UI: Name + Adapter Type dropdown + Token + optional Config JSON
15. Post-create display: adapter_type + status only (no masked token — not stored locally)
16. Test button: `GET /admin/health` for active credentials, "please activate first" for inactive
17. Health check approach for credential testing
18. No auto-create credentials on trigger node creation
19. Test strategy: TDD (RED-GREEN-REFACTOR)
20. UserProfile rename confirmed despite Metis warning
21. Trigger types: keep both, no merge

**Research Findings**:
- msg-gateway has admin API (CRUD credentials), send API, file upload/download
- Gateway `PipelitAdapter` POSTs to inbound URL with Bearer token
- `dispatch_event()` supports `workflow_id` + `trigger_node_id` for direct dispatch
- Gateway `GET /admin/health` returns per-adapter health (Healthy/Unhealthy/Dead)
- ~50 files affected: 5 delete, ~15 modify, ~20 test updates, 3 new
- Gateway admin API: POST/PUT/DELETE/PATCH(activate/deactivate) credentials

### Metis Review
**Identified Gaps** (addressed):
- Inbound auth must use separate `verify_gateway_token()` dependency → incorporated
- PendingTask migration must NOT use `batch_alter_table` (SQLite data loss risk) → use add_column + drop_column
- Confirmation prompt on interrupt has no sender in new flow → orchestrator calls `gateway_client.send_message()`
- allowed_user_ids filtering → gateway adapter handles this, pipelit doesn't check
- Telegram poll start/stop API endpoints → must be removed, replaced by credential activate/deactivate
- Gateway client must be mockable → lazy init, not module-level singleton
- Conversation memory orphaning → acceptable for one-shot migration
- ChatMessageIn/Out schemas → removed with chat endpoints
- Inactive workflow check → inbound returns 422
- bot_token must NEVER appear in trigger_payload or local DB

---

## Work Objectives

### Core Objective
Make pipelit a protocol-agnostic workflow execution engine. All messaging protocol handling (Telegram, generic chat) is delegated to msg-gateway. Pipelit receives normalized `InboundMessage` via webhook and sends responses via gateway send API.

### Concrete Deliverables
- `platform/services/gateway_client.py` — HTTP client for gateway admin + send + file APIs
- `platform/api/inbound.py` — `POST /api/v1/inbound` webhook endpoint
- `platform/models/credential.py` — `GatewayCredential` model replacing `TelegramCredential`
- 3 Alembic migrations (GatewayCredential, UserProfile rename, PendingTask columns)
- Updated `platform/services/delivery.py` — gateway outbound instead of Telegram API
- Updated `platform/services/orchestrator.py` — confirmation prompts via gateway
- Updated `platform/api/credentials.py` — CRUD synced to gateway admin API
- Updated frontend `CredentialsPage.tsx` — gateway credential type UI
- Removed: `telegram_poller.py`, `telegram.py` handler, `chat.ts`, ChatPanel, chat endpoints

### Definition of Done
- [ ] `python -m pytest tests/ -v` → all tests pass (0 failures)
- [ ] `curl POST /api/v1/inbound` with valid payload → 202, execution created
- [ ] `curl POST /api/v1/credentials/` with gateway type → 201, gateway admin API called
- [ ] No references to `TelegramCredential`, `telegram_poller`, `poll_telegram_credential_task` in codebase
- [ ] No `bot_token` stored in pipelit DB or trigger_payload
- [ ] `npm run build` in frontend → 0 errors

### Must Have
- Inbound webhook with service token auth (`GATEWAY_INBOUND_TOKEN`)
- Gateway client with send_message, create/update/delete_credential, upload_file (stub)
- GatewayCredential model with gateway_credential_id + adapter_type
- Credential CRUD synced to gateway (create/update/delete)
- Delivery via gateway send API
- Confirmation prompt sent via gateway on orchestrator interrupt
- UserProfile.external_user_id (renamed from telegram_user_id)
- PendingTask with generic chat_id (String) + credential_id
- Frontend gateway credential type with test button (health check)
- All dead Telegram/chat code removed

### Must NOT Have (Guardrails)
- **NO** bot_token in pipelit DB or trigger_payload — tokens only in gateway
- **NO** `batch_alter_table` in Alembic migrations — use add_column + drop_column (SQLite safety)
- **NO** gateway in `/health` endpoint — don't break liveness probes
- **NO** trigger resolver refactoring beyond removing telegram entries
- **NO** outbound file upload invocation in delivery — stub method exists but `file_ids=[]` always
- **NO** per-adapter config schemas — keep credential config simple (name + adapter + token + optional JSON)
- **NO** inline keyboard / callback_query handling — out of scope
- **NO** browser chat UI or chat endpoint — completely removed
- **NO** auto-create credentials on trigger node creation
- **NO** module-level gateway_client singleton that connects on import — must be lazy/mockable
- **NO** trigger type merge — keep trigger_telegram and trigger_chat as separate types

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest, platform/tests/)
- **Automated tests**: TDD (RED-GREEN-REFACTOR)
- **Framework**: pytest (existing)
- **Each task**: Write failing test FIRST → implement → verify green → commit

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **API endpoints**: Use Bash (curl) — send requests, assert status + response fields
- **Backend services**: Use Bash (pytest) — run specific test files/functions
- **Frontend**: Use Playwright (playwright skill) — navigate, interact, assert DOM, screenshot
- **Database**: Use Bash (python REPL / alembic) — verify schema, run migrations

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — foundation, all independent):
├── T1: Config: gateway settings [quick]
├── T2: GatewayCredential model + migration [quick]
├── T3: UserProfile: external_user_id rename + migration [quick]
├── T4: PendingTask: generalize columns + migration [quick]
├── T5: Inbound schemas + auth dependency [quick]
├── T6: Gateway HTTP client + tests [deep]
└── T7: Node type registry: update trigger descriptions [quick]

Wave 2 (After Wave 1 — core services):
├── T8: Inbound endpoint + tests (depends: T1, T3, T5, T6) [deep]
├── T9: Credential API: gateway sync + tests (depends: T2, T6) [unspecified-high]
├── T10: Delivery: gateway outbound + tests (depends: T6) [unspecified-high]
├── T11: Orchestrator: interrupt + confirmation + tests (depends: T4, T6) [deep]
├── T12: Agent/deep_agent: user_context key rename + tests (depends: none) [quick]
└── T13: Trigger resolver: remove telegram entries + tests (depends: none) [quick]

Wave 3 (After Wave 2 — cleanup + frontend):
├── T14: Remove telegram_poller + handler + clean main.py (depends: T8) [quick]
├── T15: Remove chat endpoints + schemas (depends: T8) [quick]
├── T16: Remove Telegram poll start/stop endpoints (depends: T9) [quick]
├── T17: Frontend types + remove chat.ts (depends: none) [quick]
├── T18: CredentialsPage: gateway credential UI (depends: T9) [visual-engineering]
├── T19: NodeDetailsPanel: remove ChatPanel + poll buttons (depends: T14, T16) [visual-engineering]
└── T20: Frontend cleanup: palette descriptions + canvas (depends: none) [quick]

Wave 4 (After Wave 3 — test stabilization):
├── T21: Update conftest + fixtures + affected test files (depends: T3, T14, T15) [unspecified-high]
└── T22: Integration test: full inbound→execution→outbound (depends: T8, T10, T11) [deep]

Wave FINAL (After ALL — independent review, 4 parallel):
├── F1: Plan compliance audit [oracle]
├── F2: Code quality review [unspecified-high]
├── F3: Real QA [unspecified-high + playwright]
└── F4: Scope fidelity check [deep]

Critical Path: T1 → T6 → T8 → T14 → T21 → F1-F4
Parallel Speedup: ~65% faster than sequential
Max Concurrent: 7 (Wave 1)
```

### Dependency Matrix

| Task | Blocked By | Blocks | Wave |
|------|-----------|--------|------|
| T1 | — | T6, T8 | 1 |
| T2 | — | T9 | 1 |
| T3 | — | T8, T21 | 1 |
| T4 | — | T11 | 1 |
| T5 | — | T8 | 1 |
| T6 | T1 | T8, T9, T10, T11 | 1 |
| T7 | — | — | 1 |
| T8 | T1, T3, T5, T6 | T14, T15, T22 | 2 |
| T9 | T2, T6 | T16, T18 | 2 |
| T10 | T6 | T22 | 2 |
| T11 | T4, T6 | T22 | 2 |
| T12 | — | — | 2 |
| T13 | — | — | 2 |
| T14 | T8 | T19, T21 | 3 |
| T15 | T8 | T21 | 3 |
| T16 | T9 | T19 | 3 |
| T17 | — | — | 3 |
| T18 | T9 | — | 3 |
| T19 | T14, T16 | — | 3 |
| T20 | — | — | 3 |
| T21 | T3, T14, T15 | F1-F4 | 4 |
| T22 | T8, T10, T11 | F1-F4 | 4 |
| F1-F4 | T21, T22 | — | FINAL |

### Agent Dispatch Summary

- **Wave 1**: 7 tasks — T1-T5,T7 → `quick`, T6 → `deep`
- **Wave 2**: 6 tasks — T8 → `deep`, T9-T10 → `unspecified-high`, T11 → `deep`, T12-T13 → `quick`
- **Wave 3**: 7 tasks — T14-T17,T20 → `quick`, T18-T19 → `visual-engineering`
- **Wave 4**: 2 tasks — T21 → `unspecified-high`, T22 → `deep`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. Config: Add Gateway Settings

  **What to do**:
  - RED: Write test asserting `Settings` has `GATEWAY_URL`, `GATEWAY_ADMIN_TOKEN`, `GATEWAY_SEND_TOKEN`, `GATEWAY_INBOUND_TOKEN` fields with empty string defaults
  - GREEN: Add fields to `Settings` class in `config.py`
  - REFACTOR: Verify test passes, clean up

  **Must NOT do**:
  - Do NOT add gateway health checks or connectivity validation on startup
  - Do NOT create .env file — just add fields to Settings class

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T2-T7)
  - **Blocks**: T6 (gateway client reads settings), T8 (inbound reads GATEWAY_INBOUND_TOKEN)
  - **Blocked By**: None

  **References**:
  **Pattern References**:
  - `platform/config.py` — Existing `Settings` class with `DATABASE_URL`, `REDIS_URL` etc. Follow the same pattern for new fields.

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/ -k "settings or config"` → PASS
  - [ ] `from config import settings; assert hasattr(settings, 'GATEWAY_URL')` → True

  **QA Scenarios**:
  ```
  Scenario: Settings fields exist with defaults
    Tool: Bash (python)
    Preconditions: Platform venv activated
    Steps:
      1. Run: python -c "from config import settings; print(settings.GATEWAY_URL, settings.GATEWAY_ADMIN_TOKEN, settings.GATEWAY_SEND_TOKEN, settings.GATEWAY_INBOUND_TOKEN)"
      2. Assert: Output is four empty strings (defaults)
    Expected Result: No ImportError, all fields return ""
    Failure Indicators: ImportError, AttributeError
    Evidence: .sisyphus/evidence/task-1-config-defaults.txt
  ```

  **Commit**: YES
  - Message: `feat(config): add gateway settings`
  - Files: `platform/config.py`, `platform/tests/test_config.py`
  - Pre-commit: `pytest tests/ -k config`

- [x] 2. GatewayCredential Model + Alembic Migration

  **What to do**:
  - RED: Write test that imports `GatewayCredential`, creates instance with `gateway_credential_id` + `adapter_type`, verifies fields
  - GREEN: In `models/credential.py`:
    - Remove `TelegramCredential` class entirely
    - Remove `telegram_credential` relationship from `BaseCredential`
    - Add `GatewayCredential` class:
      ```python
      class GatewayCredential(Base):
          __tablename__ = "gateway_credentials"
          id = Column(Integer, primary_key=True)
          base_credentials_id = Column(Integer, ForeignKey("credentials.id", ondelete="CASCADE"), unique=True)
          gateway_credential_id = Column(String(255), nullable=False)  # ID in gateway
          adapter_type = Column(String(50), nullable=False)  # "telegram", "generic", etc.
          base_credential = relationship("BaseCredential", backref=backref("gateway_credential", uselist=False))
      ```
    - Update `credential_type` discriminator: add `"gateway"`, ensure `"telegram"` is removed or aliased
  - Create Alembic migration:
    - Create `gateway_credentials` table
    - Drop `telegram_credentials` table
    - Use `op.create_table()` and `op.drop_table()` — NOT `batch_alter_table`
  - REFACTOR: Verify test passes

  **Must NOT do**:
  - Do NOT use `batch_alter_table` — SQLite data loss risk
  - Do NOT try to migrate existing telegram credential data — clean slate
  - Do NOT store tokens or sensitive data in GatewayCredential

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1, T3-T7)
  - **Blocks**: T9 (credential API needs GatewayCredential model)
  - **Blocked By**: None

  **References**:
  **Pattern References**:
  - `platform/models/credential.py` — Full polymorphic inheritance pattern. `TelegramCredential` is the reference for what to replace with `GatewayCredential`. Study how `LLMProviderCredential` is structured — follow same pattern.
  - `platform/models/credential.py:TelegramCredential` — The class to DELETE. Note its `base_credentials_id` FK pattern.
  **API/Type References**:
  - `platform/schemas/credential.py:CredentialTypeStr` — Must add `"gateway"` to the Literal type. Currently `Literal["git", "llm", "telegram", "tool"]`.
  **Test References**:
  - `platform/tests/test_api.py` — Contains credential creation tests. Check what references `TelegramCredential`.

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/ -k credential` → PASS
  - [ ] `GatewayCredential` importable from `models.credential`
  - [ ] `TelegramCredential` no longer importable
  - [ ] Alembic migration runs: `alembic upgrade head` → no errors
  - [ ] `telegram_credentials` table dropped, `gateway_credentials` table created

  **QA Scenarios**:
  ```
  Scenario: Migration creates gateway_credentials table
    Tool: Bash (alembic + sqlite3)
    Preconditions: Database exists, venv activated
    Steps:
      1. Run: alembic upgrade head
      2. Run: sqlite3 pipelit.db ".tables" | grep gateway_credentials
      3. Run: sqlite3 pipelit.db ".tables" | grep telegram_credentials
    Expected Result: gateway_credentials exists, telegram_credentials does NOT exist
    Failure Indicators: Migration error, telegram_credentials still exists
    Evidence: .sisyphus/evidence/task-2-migration-tables.txt

  Scenario: GatewayCredential model works in ORM
    Tool: Bash (pytest)
    Preconditions: Migration applied
    Steps:
      1. Run: pytest tests/ -k "gateway_credential" -v
    Expected Result: All tests pass
    Failure Indicators: ImportError, IntegrityError
    Evidence: .sisyphus/evidence/task-2-orm-test.txt
  ```

  **Commit**: YES
  - Message: `feat(models): add GatewayCredential model + migration`
  - Files: `platform/models/credential.py`, `platform/schemas/credential.py`, `platform/alembic/versions/xxx_gateway_credential.py`
  - Pre-commit: `pytest tests/ -k credential`

- [x] 3. UserProfile: Rename telegram_user_id → external_user_id

  **What to do**:
  - RED: Write test creating UserProfile with `external_user_id="12345"`, assert field exists and is queryable
  - GREEN: In `models/user.py`:
    - Rename `telegram_user_id` column to `external_user_id`
    - Keep it as `BigInteger` for now (Telegram IDs are integers; other platforms may use strings — but changing type is separate scope)
    - Update any `__repr__` or property references
  - Create Alembic migration:
    - Use `op.add_column("user_profiles", Column("external_user_id", BigInteger, unique=True, nullable=True))`
    - Copy data: `op.execute("UPDATE user_profiles SET external_user_id = telegram_user_id")`
    - Drop old: `op.drop_column("user_profiles", "telegram_user_id")`
    - Do NOT use `batch_alter_table`
  - Update all Python references to `telegram_user_id` → `external_user_id` using `lsp_find_references` first
  - REFACTOR: Verify all tests pass

  **Must NOT do**:
  - Do NOT use `batch_alter_table` — SQLite data loss risk
  - Do NOT change column type (BigInteger stays for now)
  - Do NOT change how UserProfile is created in other modules yet — just the field name

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T2, T4-T7)
  - **Blocks**: T8 (inbound endpoint looks up by external_user_id), T21 (test fixtures)
  - **Blocked By**: None

  **References**:
  **Pattern References**:
  - `platform/models/user.py` — `UserProfile` model. Find `telegram_user_id` field, rename it.
  - `platform/handlers/telegram.py:_get_or_create_profile()` — Current user lookup pattern by `telegram_user_id`. The inbound endpoint (T8) will replicate this with `external_user_id`.
  **Test References**:
  - `platform/conftest.py` — Fixture creates `UserProfile(telegram_user_id=111222333)`. Must update to `external_user_id=111222333`.
  **External References**:
  - Use `lsp_find_references` on `telegram_user_id` in `models/user.py` to find ALL usages before renaming.
  - Use `ast_grep_search` for string literal `"telegram_user_id"` to catch dict key references.

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/ -k user` → PASS
  - [ ] `UserProfile.external_user_id` exists, `telegram_user_id` does NOT
  - [ ] Alembic migration runs: `alembic upgrade head` → no errors
  - [ ] `grep -r "telegram_user_id" platform/ --include="*.py" -l` → only alembic migration files

  **QA Scenarios**:
  ```
  Scenario: Column renamed in database
    Tool: Bash (sqlite3)
    Preconditions: Migration applied
    Steps:
      1. Run: sqlite3 pipelit.db "PRAGMA table_info(user_profiles)" | grep external_user_id
      2. Run: sqlite3 pipelit.db "PRAGMA table_info(user_profiles)" | grep telegram_user_id
    Expected Result: external_user_id exists, telegram_user_id does NOT
    Failure Indicators: telegram_user_id still in schema
    Evidence: .sisyphus/evidence/task-3-column-rename.txt

  Scenario: No references to old field name in active code
    Tool: Bash (grep)
    Preconditions: All code changes applied
    Steps:
      1. Run: grep -r "telegram_user_id" platform/ --include="*.py" -l | grep -v alembic
    Expected Result: 0 results
    Failure Indicators: Any file still references telegram_user_id
    Evidence: .sisyphus/evidence/task-3-no-old-refs.txt
  ```

  **Commit**: YES
  - Message: `refactor(models): rename telegram_user_id to external_user_id`
  - Files: `platform/models/user.py`, `platform/alembic/versions/xxx_rename_telegram_user_id.py`, + all files with references
  - Pre-commit: `pytest tests/ -v`

- [x] 4. PendingTask: Generalize Columns + Migration

  **What to do**:
  - RED: Write test creating PendingTask with `chat_id="12345"` (String) and `credential_id="tg_mybot"` (String), assert fields exist
  - GREEN: In `models/execution.py`:
    - Add `chat_id = Column(String(255), nullable=True)` column
    - Add `credential_id = Column(String(255), nullable=True)` column
    - Remove `telegram_chat_id` column after data copy
  - Create Alembic migration:
    - `op.add_column("pending_tasks", Column("chat_id", String(255), nullable=True))`
    - `op.add_column("pending_tasks", Column("credential_id", String(255), nullable=True))`
    - `op.execute("UPDATE pending_tasks SET chat_id = CAST(telegram_chat_id AS TEXT)")` — preserve existing data
    - `op.drop_column("pending_tasks", "telegram_chat_id")`
    - Do NOT use `batch_alter_table`
  - REFACTOR: Update any code that references `telegram_chat_id` on PendingTask

  **Must NOT do**:
  - Do NOT use `batch_alter_table`
  - Do NOT change PendingTask creation logic yet — that's T11 (orchestrator)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T3, T5-T7)
  - **Blocks**: T11 (orchestrator uses new columns)
  - **Blocked By**: None

  **References**:
  **Pattern References**:
  - `platform/models/execution.py` — `PendingTask` model. Find `telegram_chat_id` field (BigInteger).
  - `platform/services/orchestrator.py:_handle_interrupt()` — Creates PendingTask with `telegram_chat_id`. This is the primary consumer of the columns (changed in T11).
  **External References**:
  - Use `ast_grep_search` for `telegram_chat_id` to find ALL references in Python files.

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/ -k pending` → PASS
  - [ ] `PendingTask.chat_id` and `PendingTask.credential_id` exist as String columns
  - [ ] `PendingTask.telegram_chat_id` does NOT exist
  - [ ] Migration: `alembic upgrade head` → no errors

  **QA Scenarios**:
  ```
  Scenario: PendingTask columns migrated
    Tool: Bash (sqlite3)
    Preconditions: Migration applied
    Steps:
      1. Run: sqlite3 pipelit.db "PRAGMA table_info(pending_tasks)" | grep chat_id
      2. Run: sqlite3 pipelit.db "PRAGMA table_info(pending_tasks)" | grep credential_id
      3. Run: sqlite3 pipelit.db "PRAGMA table_info(pending_tasks)" | grep telegram_chat_id
    Expected Result: chat_id and credential_id exist, telegram_chat_id does NOT
    Evidence: .sisyphus/evidence/task-4-pending-columns.txt
  ```

  **Commit**: YES
  - Message: `refactor(models): generalize PendingTask columns`
  - Files: `platform/models/execution.py`, `platform/alembic/versions/xxx_pending_task_columns.py`
  - Pre-commit: `pytest tests/ -k pending`

- [x] 5. Inbound Pydantic Schemas + Auth Dependency

  **What to do**:
  - RED: Write tests for:
    - `GatewayInboundMessage` schema validation (valid/invalid payloads)
    - `verify_gateway_token()` dependency (valid token → passes, invalid → 401)
  - GREEN: Create `platform/schemas/inbound.py`:
    ```python
    class UserInfo(BaseModel):
        id: str
        username: str | None = None
        display_name: str | None = None

    class InboundSource(BaseModel):
        protocol: str
        chat_id: str
        message_id: str = ""
        reply_to_message_id: str | None = None
        from_: UserInfo | None = Field(None, alias="from")

    class InboundAttachment(BaseModel):
        filename: str
        mime_type: str
        size_bytes: int = 0
        download_url: str = ""

    class GatewayInboundMessage(BaseModel):
        route: dict  # {workflow_slug, trigger_node_id}
        credential_id: str
        source: InboundSource
        text: str
        attachments: list[InboundAttachment] = []
        timestamp: str
        extra_data: dict | None = None
    ```
  - Create `verify_gateway_token()` auth dependency in `platform/auth.py` (or new file):
    ```python
    def verify_gateway_token(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
        if credentials.credentials != settings.GATEWAY_INBOUND_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid gateway token")
    ```
  - REFACTOR: Verify tests pass

  **Must NOT do**:
  - Do NOT tie gateway auth to UserProfile or APIKey table
  - Do NOT add the inbound endpoint yet — just schemas and auth

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T4, T6-T7)
  - **Blocks**: T8 (inbound endpoint uses these schemas + auth)
  - **Blocked By**: None

  **References**:
  **Pattern References**:
  - `platform/auth.py` — Existing `get_current_user()` dependency pattern. The new `verify_gateway_token()` is simpler (just compares token string).
  - `platform/schemas/credential.py` — Example Pydantic schema structure in this project.
  - `platform/schemas/node_io.py` — Another schema example.
  **API/Type References**:
  - msg-gateway `src/message.rs` — The `InboundMessage` Rust struct that defines the payload format. Our Pydantic schema must match. Key fields: `route` (JSON), `credential_id`, `source` (nested), `text`, `attachments` (array), `timestamp`.
  - msg-gateway `src/adapter.rs:AdapterInboundRequest` — The adapter-to-gateway request format, which gets transformed into `InboundMessage`.

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/ -k "inbound_schema or gateway_token"` → PASS
  - [ ] `GatewayInboundMessage` validates a correct payload
  - [ ] `GatewayInboundMessage` rejects payload missing `route` or `credential_id`
  - [ ] `verify_gateway_token()` accepts valid token, rejects invalid

  **QA Scenarios**:
  ```
  Scenario: Schema validates correct payload
    Tool: Bash (python)
    Preconditions: venv activated
    Steps:
      1. Run: python -c "from schemas.inbound import GatewayInboundMessage; m = GatewayInboundMessage(route={'workflow_slug':'test','trigger_node_id':'t1'},credential_id='tg1',source={'protocol':'telegram','chat_id':'123'},text='hello',timestamp='2026-01-01T00:00:00Z'); print(m.credential_id)"
    Expected Result: Prints "tg1" without error
    Evidence: .sisyphus/evidence/task-5-schema-valid.txt

  Scenario: Schema rejects invalid payload
    Tool: Bash (python)
    Preconditions: venv activated
    Steps:
      1. Run: python -c "from schemas.inbound import GatewayInboundMessage; GatewayInboundMessage(text='hello')" 2>&1
    Expected Result: ValidationError (missing route, credential_id, source, timestamp)
    Evidence: .sisyphus/evidence/task-5-schema-invalid.txt
  ```

  **Commit**: YES
  - Message: `feat(schemas): add inbound schemas + gateway auth dependency`
  - Files: `platform/schemas/inbound.py`, `platform/auth.py`
  - Pre-commit: `pytest tests/ -k inbound`

- [x] 6. Gateway HTTP Client + Tests

  **What to do**:
  - RED: Write comprehensive tests for `GatewayClient` (mock HTTP with `responses` or `unittest.mock.patch`):
    - `send_message()` → correct URL, headers, body
    - `create_credential()` → correct admin URL, auth, body
    - `update_credential()`, `delete_credential()`, `activate_credential()`, `deactivate_credential()`
    - `upload_file()` → multipart POST
    - `check_credential_health()` → parse health response
    - Error cases: gateway unreachable → raises appropriate exception, gateway 4xx/5xx → propagates
  - GREEN: Create `platform/services/gateway_client.py`:
    - `GatewayClient` class with `requests` library
    - Lazy-initialized settings (read `GATEWAY_URL`, `GATEWAY_ADMIN_TOKEN`, `GATEWAY_SEND_TOKEN` on first call, not on import)
    - Methods:
      - `send_message(credential_id, chat_id, text, reply_to_message_id=None, file_ids=None, extra_data=None)` → `POST {GATEWAY_URL}/api/v1/send`
      - `upload_file(data, filename, mime_type)` → `POST {GATEWAY_URL}/api/v1/files` → returns `file_id`
      - `create_credential(id, adapter, token, config=None, route=None, active=False)` → `POST {GATEWAY_URL}/admin/credentials`
      - `update_credential(id, **kwargs)` → `PUT {GATEWAY_URL}/admin/credentials/{id}`
      - `delete_credential(id)` → `DELETE {GATEWAY_URL}/admin/credentials/{id}`
      - `activate_credential(id)` → `PATCH {GATEWAY_URL}/admin/credentials/{id}/activate`
      - `deactivate_credential(id)` → `PATCH {GATEWAY_URL}/admin/credentials/{id}/deactivate`
      - `check_credential_health(credential_id=None)` → `GET {GATEWAY_URL}/admin/health` → parse adapter health for specific credential
    - Auth: Bearer `admin_token` for `/admin/*`, Bearer `send_token` for `/api/v1/*`
    - Error handling: `ConnectionError` → raise `GatewayUnavailableError`; 4xx/5xx → raise `GatewayAPIError` with status + message
    - Module-level `get_gateway_client()` function (lazy singleton) — NOT a module-level instance
  - REFACTOR: Clean up, add docstrings

  **Must NOT do**:
  - Do NOT create module-level `gateway_client = GatewayClient()` — must be lazy for testability
  - Do NOT add retry logic on errors — silent fail is the policy
  - Do NOT actually call a running gateway in tests — all HTTP mocked

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Core infrastructure service with many methods, comprehensive error handling, extensive test coverage needed
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (only depends on T1 for config, but can mock settings)
  - **Parallel Group**: Wave 1 (with T1-T5, T7)
  - **Blocks**: T8, T9, T10, T11 (all core services use gateway client)
  - **Blocked By**: T1 (config settings) — but can mock settings in tests

  **References**:
  **Pattern References**:
  - `platform/services/delivery.py` — Current HTTP client usage pattern with `requests`. Look at how Telegram API calls are structured.
  - `platform/services/telegram_poller.py` — Another example of HTTP client with error handling.
  **API/Type References**:
  - msg-gateway `POST /api/v1/send` — Request: `{credential_id, chat_id, text, reply_to_message_id?, extra_data?, file_ids?}`. Response: `{status, protocol_message_id, timestamp}`. Auth: Bearer `send_token`.
  - msg-gateway `POST /api/v1/files` — Multipart: `{file, filename?, mime_type?}`. Response: `{file_id, filename, mime_type, size_bytes, download_url}`. Auth: Bearer `send_token`.
  - msg-gateway `POST /admin/credentials` — Request: `{id, adapter, token, active?, config?, route?}`. Response: `{id, status: "created"}`. Auth: Bearer `admin_token`.
  - msg-gateway `PUT /admin/credentials/{id}` — All fields optional. Response: `{id, status: "updated"}`.
  - msg-gateway `DELETE /admin/credentials/{id}` — Response: `{id, status: "deleted"}`.
  - msg-gateway `PATCH /admin/credentials/{id}/activate` — Response: `{id, status: "activated|already_active"}`.
  - msg-gateway `PATCH /admin/credentials/{id}/deactivate` — Response: `{id, status: "deactivated|already_inactive"}`.
  - msg-gateway `GET /admin/health` — Response includes `adapters` array with `{credential_id, adapter, health, failures}`.
  - Error format: `{"error": "string"}` with HTTP 400/401/404/500.

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/test_gateway_client.py -v` → PASS (all methods tested)
  - [ ] `GatewayClient` importable from `services.gateway_client`
  - [ ] All 8 methods work against mocked HTTP
  - [ ] Error handling: `ConnectionError` → `GatewayUnavailableError`, 4xx/5xx → `GatewayAPIError`

  **QA Scenarios**:
  ```
  Scenario: All client methods pass tests
    Tool: Bash (pytest)
    Preconditions: venv activated
    Steps:
      1. Run: pytest tests/test_gateway_client.py -v --tb=short
    Expected Result: All tests pass (send_message, create/update/delete/activate/deactivate_credential, upload_file, check_health, error cases)
    Failure Indicators: Any test failure
    Evidence: .sisyphus/evidence/task-6-client-tests.txt

  Scenario: Gateway unreachable error
    Tool: Bash (python)
    Preconditions: No gateway running, GATEWAY_URL set to unreachable host
    Steps:
      1. Run: python -c "from services.gateway_client import GatewayClient; c = GatewayClient(); c.send_message('cred1', 'chat1', 'hello')"
    Expected Result: Raises GatewayUnavailableError (or ConnectionError subclass)
    Evidence: .sisyphus/evidence/task-6-unreachable-error.txt
  ```

  **Commit**: YES
  - Message: `feat(services): add gateway HTTP client`
  - Files: `platform/services/gateway_client.py`, `platform/tests/test_gateway_client.py`
  - Pre-commit: `pytest tests/test_gateway_client.py -v`

- [ ] 7. Node Type Registry: Update Trigger Descriptions

  **What to do**:
  - RED: Write test asserting `trigger_telegram` and `trigger_chat` descriptions reference "gateway" instead of "Telegram API" / "browser chat"
  - GREEN: In `platform/schemas/node_type_defs.py`:
    - Update `trigger_telegram` description: "Receives messages from Telegram via msg-gateway" (was: direct Telegram API)
    - Update `trigger_chat` description: "Receives messages from external chat clients via msg-gateway generic adapter" (was: browser chat)
    - Update `files` output port schema for both: `{filename, mime_type, size_bytes, url}` (was: `{file_id, file_name, mime_type, file_size}`)
  - REFACTOR: Verify tests pass

  **Must NOT do**:
  - Do NOT add a new `trigger_gateway` type — keep existing types
  - Do NOT change the component_type strings — `trigger_telegram` and `trigger_chat` stay as-is
  - Do NOT change port definitions beyond the files port schema

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1-T6)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  **Pattern References**:
  - `platform/schemas/node_type_defs.py` — All node type registrations. Find `register_node_type("trigger_telegram", ...)` and `register_node_type("trigger_chat", ...)`.
  - `platform/schemas/node_types.py` — `NodeTypeSpec`, `PortDefinition` classes.

  **Acceptance Criteria**:
  - [ ] `trigger_telegram` description mentions gateway
  - [ ] `trigger_chat` description mentions gateway generic adapter
  - [ ] Files port schema: `{filename, mime_type, size_bytes, url}` (not `file_id`)

  **QA Scenarios**:
  ```
  Scenario: Updated descriptions in node type registry
    Tool: Bash (python)
    Preconditions: venv activated
    Steps:
      1. Run: python -c "from schemas.node_types import NODE_TYPE_REGISTRY; t = NODE_TYPE_REGISTRY['trigger_telegram']; print(t.description)"
      2. Assert: Output contains "gateway"
    Expected Result: Description mentions gateway
    Evidence: .sisyphus/evidence/task-7-trigger-desc.txt
  ```

  **Commit**: YES
  - Message: `chore(schemas): update trigger node type descriptions for gateway`
  - Files: `platform/schemas/node_type_defs.py`
  - Pre-commit: `pytest tests/ -k node_type`

- [ ] 8. Inbound Webhook Endpoint + Tests

  **What to do**:
  - RED: Write comprehensive tests for `POST /api/v1/inbound`:
    - Valid payload → 202, execution_id returned
    - Invalid gateway token → 401
    - Missing workflow_slug → 404
    - Missing trigger_node_id → 404
    - Inactive workflow → 422
    - `/confirm_xxx` text → routes to confirmation handler
    - `/cancel_xxx` text → routes to confirmation handler
    - Payload with attachments → file tags appended to text
    - Missing `source.from` → still works (creates anonymous profile or uses system profile)
  - GREEN: Create `platform/api/inbound.py`:
    - `POST /api/v1/inbound` with `verify_gateway_token` dependency
    - Logic:
      1. Extract `workflow_slug` and `trigger_node_id` from `route`
      2. Look up `Workflow` by slug → 404 if not found
      3. Check `workflow.is_active` → 422 if inactive
      4. Look up `WorkflowNode` by node_id + workflow_id → 404 if not found
      5. Handle `/confirm_xxx` and `/cancel_xxx` text patterns:
         - Query `PendingTask` by task_id from text
         - Resume or cancel the interrupted execution
         - Send confirmation response via `gateway_client.send_message()`
         - Return 200 with confirmation result
      6. Get or create `UserProfile` from `source.from_`:
         - Look up by `external_user_id` matching `source.from_.id`
         - If not found: create with `external_user_id=int(source.from_.id)`, `username=source.from_.username`
         - If `source.from_` is None: use a system/anonymous profile
      7. Build `event_data`:
         ```python
         {
             "text": text_with_file_tags,
             "chat_id": payload.source.chat_id,
             "message_id": payload.source.message_id,
             "credential_id": payload.credential_id,
             "user_id": payload.source.from_.id if payload.source.from_ else "",
             "files": [{"filename": a.filename, "mime_type": a.mime_type, "size_bytes": a.size_bytes, "url": a.download_url} for a in payload.attachments],
         }
         ```
      8. For each attachment, append file tag: `[Attached file: {filename} | url: {download_url} | type: {mime_type}]`
      9. Call `dispatch_event("gateway_inbound", event_data, user_profile, db, workflow_id=workflow.id, trigger_node_id=node.node_id)`
      10. Return 202 with `{"execution_id": str, "status": "pending"}`
  - Register router in `platform/api/__init__.py` (if exists) or `platform/main.py`
  - REFACTOR: Clean up

  **Must NOT do**:
  - Do NOT use `get_current_user()` for auth — use `verify_gateway_token()`
  - Do NOT store bot_token anywhere
  - Do NOT check allowed_user_ids — gateway handles filtering

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Complex endpoint with many code paths (confirm/cancel, user provisioning, file handling, error cases)
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 2)
  - **Parallel Group**: Wave 2 (with T9-T13)
  - **Blocks**: T14 (remove old handler after inbound works), T15 (remove chat after inbound works), T22 (integration test)
  - **Blocked By**: T1 (config), T3 (external_user_id), T5 (schemas + auth), T6 (gateway client)

  **References**:
  **Pattern References**:
  - `platform/handlers/manual.py` — Best pattern for the inbound endpoint structure. Similar request handling flow.
  - `platform/handlers/telegram.py:_get_or_create_profile()` (lines ~120-145) — User provisioning logic to REPLICATE (not import — file will be deleted). Copy the lookup-or-create pattern but use `external_user_id` instead of `telegram_user_id`.
  - `platform/handlers/telegram.py:handle_confirmation()` — Confirmation flow logic to replicate for `/confirm_xxx` and `/cancel_xxx` text patterns.
  - `platform/handlers/__init__.py:dispatch_event()` — The function to call. Signature: `dispatch_event(event_type, event_data, user_profile, db, workflow_id=None, trigger_node_id=None)`.
  **API/Type References**:
  - `platform/schemas/inbound.py` (from T5) — `GatewayInboundMessage` schema for request body
  - `platform/models/execution.py:PendingTask` — Query this for confirmation handling
  - `platform/models/user.py:UserProfile` — Create/lookup by `external_user_id`
  - `platform/models/workflow.py:Workflow` — Look up by slug, check `is_active`
  - `platform/models/node.py:WorkflowNode` — Look up by `node_id` + `workflow_id`

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/test_inbound.py -v` → PASS (all cases)
  - [ ] Valid inbound → 202, execution created
  - [ ] Invalid token → 401
  - [ ] Bad route → 404
  - [ ] Inactive workflow → 422
  - [ ] `/confirm_xxx` → confirmation handled
  - [ ] Attachments → file tags in text

  **QA Scenarios**:
  ```
  Scenario: Valid inbound creates execution
    Tool: Bash (curl)
    Preconditions: Server running, workflow "test-wf" exists with trigger node
    Steps:
      1. curl -X POST http://localhost:8000/api/v1/inbound -H "Authorization: Bearer $GATEWAY_INBOUND_TOKEN" -H "Content-Type: application/json" -d '{"route":{"workflow_slug":"test-wf","trigger_node_id":"trigger_telegram_abc"},"credential_id":"tg_test","source":{"protocol":"telegram","chat_id":"12345","message_id":"1","from":{"id":"777","username":"testuser"}},"text":"hello","attachments":[],"timestamp":"2026-03-10T00:00:00Z"}'
      2. Assert HTTP status 202
      3. Assert response body contains "execution_id" and "status":"pending"
    Expected Result: 202 with execution_id
    Failure Indicators: Non-202 status, missing execution_id
    Evidence: .sisyphus/evidence/task-8-valid-inbound.txt

  Scenario: Invalid token rejected
    Tool: Bash (curl)
    Steps:
      1. curl -X POST http://localhost:8000/api/v1/inbound -H "Authorization: Bearer WRONG_TOKEN" -H "Content-Type: application/json" -d '{"route":{},"credential_id":"x","source":{"protocol":"t","chat_id":"1"},"text":"hi","timestamp":"2026-01-01"}'
      2. Assert HTTP status 401
    Expected Result: 401 Unauthorized
    Evidence: .sisyphus/evidence/task-8-invalid-token.txt

  Scenario: File attachments create file tags
    Tool: Bash (pytest)
    Steps:
      1. Run test that sends inbound with attachments
      2. Assert event_data["text"] contains "[Attached file: doc.pdf | url: http://gateway/files/uuid | type: application/pdf]"
    Expected Result: File tags appended to text
    Evidence: .sisyphus/evidence/task-8-file-tags.txt
  ```

  **Commit**: YES
  - Message: `feat(api): add inbound webhook endpoint`
  - Files: `platform/api/inbound.py`, `platform/api/__init__.py` or `platform/main.py`, `platform/tests/test_inbound.py`
  - Pre-commit: `pytest tests/test_inbound.py -v`

- [ ] 9. Credential API: Sync with Gateway + Tests

  **What to do**:
  - RED: Write tests for:
    - CREATE with `credential_type="gateway"` → calls `gateway_client.create_credential()`, saves local `GatewayCredential`, returns 201
    - CREATE with gateway error → 502, no local save
    - DELETE gateway credential → calls `gateway_client.delete_credential()`, deletes local record
    - UPDATE gateway credential → calls `gateway_client.update_credential()`
    - TEST (health check) gateway credential → calls `gateway_client.check_credential_health()`, returns health status
    - ACTIVATE/DEACTIVATE → calls gateway activate/deactivate
    - LIST → includes gateway credentials with adapter_type in detail
    - LLM/git/tool credential types → unchanged behavior
  - GREEN: In `platform/api/credentials.py`:
    - `create_credential()`: Add `elif credential_type == "gateway":` branch:
      - Extract `adapter_type`, `token`, `config` from `detail`
      - Call `gateway_client.create_credential(id=name, adapter=adapter_type, token=token, config=config)`
      - If gateway returns error → raise `HTTPException(502, detail=gateway_error)`
      - On success → create `BaseCredential` + `GatewayCredential` (no token stored locally)
    - `delete_credential()`: If credential has `gateway_credential`:
      - Call `gateway_client.delete_credential(gw_cred.gateway_credential_id)`
      - If gateway fails → raise `HTTPException(502)`
      - On success → delete local
    - `update_credential()`: If credential has `gateway_credential`:
      - If `detail` has new token → call `gateway_client.update_credential(id, token=new_token)`
      - Other detail updates (adapter_type change) → update local + gateway
    - `test_credential()`: Add gateway test case:
      - Call `gateway_client.check_credential_health(gw_cred.gateway_credential_id)`
      - Return `{ok: True/False, error: health_status}` based on health
    - `_serialize_credential()`: Add gateway case:
      - Return `detail = {"adapter_type": gw_cred.adapter_type, "gateway_credential_id": gw_cred.gateway_credential_id}`
  - Add activate/deactivate endpoints (or add to existing update flow):
    - `POST /credentials/{id}/activate/` → `gateway_client.activate_credential()`
    - `POST /credentials/{id}/deactivate/` → `gateway_client.deactivate_credential()`
  - REFACTOR: Clean up

  **Must NOT do**:
  - Do NOT store token in local DB — only send to gateway
  - Do NOT change LLM/git/tool credential flows
  - Do NOT add per-adapter config schemas — keep detail as flat dict

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Significant API changes with gateway sync, multiple branches, error handling
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 2)
  - **Parallel Group**: Wave 2 (with T8, T10-T13)
  - **Blocks**: T16 (remove poll endpoints), T18 (frontend credential UI)
  - **Blocked By**: T2 (GatewayCredential model), T6 (gateway client)

  **References**:
  **Pattern References**:
  - `platform/api/credentials.py:create_credential()` — The existing function with `if/elif` dispatch by `credential_type`. Add `"gateway"` branch following the same pattern as `"telegram"` (which is being replaced).
  - `platform/api/credentials.py:_serialize_credential()` — The serialization function with type-specific detail dicts. Add `"gateway"` case.
  - `platform/api/credentials.py:test_credential()` — Existing LLM test logic. Add gateway health check case.
  **API/Type References**:
  - `platform/models/credential.py:GatewayCredential` (from T2) — The model to create on success
  - `platform/services/gateway_client.py` (from T6) — Client methods to call
  - `platform/schemas/credential.py:CredentialTypeStr` — Must include `"gateway"`

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/ -k credential` → PASS
  - [ ] CREATE gateway → 201, gateway API called, no token in local DB
  - [ ] CREATE gateway with gateway down → 502, no local record
  - [ ] DELETE gateway → gateway API called, local record deleted
  - [ ] TEST gateway → returns health status
  - [ ] LIST → gateway credentials show adapter_type in detail

  **QA Scenarios**:
  ```
  Scenario: Create gateway credential succeeds
    Tool: Bash (pytest)
    Steps:
      1. Run test: mock gateway_client.create_credential → success
      2. POST /credentials/ with type="gateway", detail={adapter_type: "telegram", token: "bot123:ABC"}
      3. Assert: 201 returned
      4. Assert: gateway_client.create_credential called with correct args
      5. Assert: local DB has GatewayCredential row with adapter_type="telegram"
      6. Assert: no token stored in local DB
    Expected Result: 201, synced to gateway, no local token
    Evidence: .sisyphus/evidence/task-9-create-success.txt

  Scenario: Create fails when gateway unavailable
    Tool: Bash (pytest)
    Steps:
      1. Mock gateway_client.create_credential → raises GatewayUnavailableError
      2. POST /credentials/ with type="gateway"
      3. Assert: 502 returned
      4. Assert: no BaseCredential or GatewayCredential rows created
    Expected Result: 502, no local records
    Evidence: .sisyphus/evidence/task-9-gateway-down.txt
  ```

  **Commit**: YES
  - Message: `refactor(api): sync credential CRUD with gateway`
  - Files: `platform/api/credentials.py`, `platform/tests/test_credentials.py` (or similar)
  - Pre-commit: `pytest tests/ -k credential`

- [ ] 10. Delivery Service: Gateway Outbound + Tests

  **What to do**:
  - RED: Write tests for:
    - `deliver()` with valid credential_id + chat_id → calls `gateway_client.send_message()`
    - `deliver()` with missing credential_id → returns without sending (manual/schedule triggers)
    - `deliver()` when gateway fails → logs warning, does NOT raise (silent failure policy)
    - `_format_output()` preserved unchanged
  - GREEN: Rewrite `platform/services/delivery.py`:
    - Remove ALL Telegram API code (`sendMessage`, `sendChatAction`, `_send_long_message`, `_resolve_bot_token`)
    - Remove `import requests` for Telegram API (keep if needed for gateway client)
    - New `deliver(execution, db)`:
      1. Get `credential_id` from `execution.trigger_payload.get("credential_id")`
      2. Get `chat_id` from `execution.trigger_payload.get("chat_id")`
      3. If either is missing → return (manual/schedule triggers have no chat context)
      4. Format output text with `_format_output()` (keep this method unchanged)
      5. Call `get_gateway_client().send_message(credential_id, chat_id, text, file_ids=[])`
      6. Wrap in try/except: log warning on any gateway error, do NOT raise
    - Remove `send_typing_action()` — or keep as stub that does nothing
  - REFACTOR: Clean up imports

  **Must NOT do**:
  - Do NOT change `_format_output()` — preserve formatting logic
  - Do NOT invoke `upload_file()` — `file_ids=[]` always
  - Do NOT add retry logic
  - Do NOT raise exceptions on gateway failure — log + return

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 2)
  - **Parallel Group**: Wave 2 (with T8-T9, T11-T13)
  - **Blocks**: T22 (integration test)
  - **Blocked By**: T6 (gateway client)

  **References**:
  **Pattern References**:
  - `platform/services/delivery.py` — The file to REWRITE. Read the entire file first. Preserve `_format_output()` exactly. Replace `_send_telegram_message()` and `_resolve_bot_token()` with `gateway_client.send_message()`.
  - `platform/services/delivery.py:_format_output()` — KEEP THIS METHOD UNCHANGED. It formats workflow output into human-readable text.
  **API/Type References**:
  - `platform/services/gateway_client.py:send_message()` (from T6) — `send_message(credential_id, chat_id, text, file_ids=[])`
  - `platform/models/execution.py:WorkflowExecution.trigger_payload` — JSON dict containing `credential_id` and `chat_id` (set by inbound endpoint in T8)

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/ -k delivery` → PASS
  - [ ] No Telegram API imports or calls remain in delivery.py
  - [ ] `deliver()` calls `gateway_client.send_message()` with correct args
  - [ ] Gateway failure → logged warning, no exception raised
  - [ ] Missing credential_id → returns without sending

  **QA Scenarios**:
  ```
  Scenario: Delivery sends via gateway
    Tool: Bash (pytest)
    Steps:
      1. Mock gateway_client.send_message → success
      2. Create execution with trigger_payload={credential_id: "tg1", chat_id: "123"}
      3. Call deliver(execution, db)
      4. Assert: send_message called with credential_id="tg1", chat_id="123"
    Expected Result: Message sent via gateway client
    Evidence: .sisyphus/evidence/task-10-delivery-send.txt

  Scenario: Delivery handles gateway failure silently
    Tool: Bash (pytest)
    Steps:
      1. Mock gateway_client.send_message → raises GatewayUnavailableError
      2. Call deliver(execution, db)
      3. Assert: no exception raised
      4. Assert: warning logged
    Expected Result: Silent failure with log
    Evidence: .sisyphus/evidence/task-10-delivery-silent-fail.txt
  ```

  **Commit**: YES
  - Message: `refactor(services): replace delivery with gateway outbound`
  - Files: `platform/services/delivery.py`, `platform/tests/test_delivery.py`
  - Pre-commit: `pytest tests/ -k delivery`

- [x] 11. Orchestrator: Interrupt + Confirmation Prompt via Gateway + Tests

  **What to do**:
  - RED: Write tests for:
    - `_handle_interrupt()` stores `chat_id` (String) and `credential_id` in PendingTask
    - `_handle_interrupt()` sends confirmation prompt via `gateway_client.send_message()`
    - Prompt text includes `/confirm_{task_id}` and `/cancel_{task_id}` instructions
  - GREEN: In `platform/services/orchestrator.py`:
    - Update `_handle_interrupt()`:
      1. Get `chat_id` from trigger_payload (was `telegram_chat_id`)
      2. Get `credential_id` from trigger_payload
      3. Create `PendingTask` with `chat_id=str(chat_id)`, `credential_id=credential_id`
      4. Build confirmation prompt text:
         ```python
         prompt = f"Action requires confirmation.\n\nTo confirm: /confirm_{task_id}\nTo cancel: /cancel_{task_id}"
         ```
      5. If `credential_id` and `chat_id`: call `get_gateway_client().send_message(credential_id, chat_id, prompt)`
      6. Wrap gateway call in try/except — log warning on failure (don't break interrupt flow)
  - REFACTOR: Clean up

  **Must NOT do**:
  - Do NOT change core orchestrator execution logic
  - Do NOT raise exceptions on gateway send failure during interrupt

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Core orchestrator logic with careful interrupt flow handling
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 2)
  - **Parallel Group**: Wave 2 (with T8-T10, T12-T13)
  - **Blocks**: T22 (integration test)
  - **Blocked By**: T4 (PendingTask columns), T6 (gateway client)

  **References**:
  **Pattern References**:
  - `platform/services/orchestrator.py:_handle_interrupt()` — The method to MODIFY. Read carefully. Currently creates PendingTask with `telegram_chat_id`. Change to `chat_id` + `credential_id`. Add gateway send call.
  - `platform/handlers/telegram.py:handle_confirmation()` — The confirmation response pattern. The prompt text format.
  **API/Type References**:
  - `platform/models/execution.py:PendingTask` (from T4) — New columns: `chat_id`, `credential_id`
  - `platform/services/gateway_client.py:send_message()` (from T6) — To send the prompt

  **Acceptance Criteria**:
  - [ ] Test: `pytest tests/ -k orchestrator` → PASS
  - [ ] PendingTask created with `chat_id` (String) and `credential_id`
  - [ ] Confirmation prompt sent via gateway with `/confirm_` and `/cancel_` commands
  - [ ] Gateway send failure during interrupt → logged, not raised

  **QA Scenarios**:
  ```
  Scenario: Interrupt creates PendingTask with gateway fields
    Tool: Bash (pytest)
    Steps:
      1. Mock orchestrator with human_confirmation node
      2. Trigger execution with trigger_payload containing chat_id and credential_id
      3. Assert PendingTask.chat_id == "12345" (String)
      4. Assert PendingTask.credential_id == "tg_test"
    Expected Result: PendingTask has correct gateway fields
    Evidence: .sisyphus/evidence/task-11-interrupt-pending.txt

  Scenario: Confirmation prompt sent via gateway
    Tool: Bash (pytest)
    Steps:
      1. Mock gateway_client.send_message
      2. Trigger interrupt
      3. Assert send_message called with prompt containing /confirm_ and /cancel_
    Expected Result: Prompt sent via gateway
    Evidence: .sisyphus/evidence/task-11-confirm-prompt.txt
  ```

  **Commit**: YES
  - Message: `refactor(services): update orchestrator interrupt flow for gateway`
  - Files: `platform/services/orchestrator.py`, `platform/tests/test_orchestrator.py`
  - Pre-commit: `pytest tests/ -k orchestrator`

- [x] 12. Agent/Deep Agent: user_context Key Rename + Tests

  **What to do**:
  - RED: Write test asserting agent thread_id uses `chat_id` key from user_context (not `telegram_chat_id`)
  - GREEN: In `platform/components/agent.py` and `platform/components/deep_agent.py`:
    - Change `user_context.get("telegram_chat_id", "")` → `user_context.get("chat_id", "")`
    - Thread ID format stays: `{user_profile_id}:{chat_id}:{workflow_id}`
    - Keep the same construction logic — only the dict key name changes
  - REFACTOR: Verify tests pass

  **Must NOT do**:
  - Do NOT change thread_id format or construction logic
  - Do NOT change how checkpointer works
  - Do NOT attempt to migrate old conversation memories

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 2)
  - **Parallel Group**: Wave 2 (with T8-T11, T13)
  - **Blocks**: None
  - **Blocked By**: None (just a dict key rename in component code)

  **References**:
  **Pattern References**:
  - `platform/components/agent.py:231-236` — Thread ID construction. Find `telegram_chat_id` in `user_context.get()` call.
  - `platform/components/deep_agent.py:257-261` — Same pattern as agent.py. Same change needed.
  **WHY**:
  - The `user_context` dict will be populated by the inbound endpoint (T8) with `chat_id` key instead of `telegram_chat_id`. Both agent components must read the new key.

  **Acceptance Criteria**:
  - [ ] `grep -r "telegram_chat_id" platform/components/` → 0 results
  - [ ] Thread ID uses `user_context.get("chat_id", "")` in both files

  **QA Scenarios**:
  ```
  Scenario: No telegram_chat_id references in components
    Tool: Bash (grep)
    Steps:
      1. Run: grep -r "telegram_chat_id" platform/components/ --include="*.py"
    Expected Result: 0 matches
    Evidence: .sisyphus/evidence/task-12-no-old-key.txt
  ```

  **Commit**: YES
  - Message: `refactor(components): rename user_context key to chat_id`
  - Files: `platform/components/agent.py`, `platform/components/deep_agent.py`
  - Pre-commit: `pytest tests/ -k agent`

- [x] 13. Trigger Resolver: Remove Telegram Entries + Tests

  **What to do**:
  - RED: Write test asserting `EVENT_TYPE_TO_COMPONENT` does NOT contain `"telegram_message"` or `"telegram_chat"` keys
  - GREEN: In `platform/triggers/resolver.py`:
    - Remove `"telegram_message"` and `"telegram_chat"` from `EVENT_TYPE_TO_COMPONENT` dict
    - Remove `_match_telegram()` method
    - Remove any credential cache logic specific to telegram
    - Keep: `manual`, `schedule`, `workflow`, `error`, `webhook` mappings
    - Add `"gateway_inbound"` → map to both `trigger_telegram` and `trigger_chat` component types (since inbound endpoint uses direct dispatch via `workflow_id` + `trigger_node_id`, the resolver is actually bypassed — but add the mapping for completeness)
  - REFACTOR: Clean up imports

  **Must NOT do**:
  - Do NOT refactor the resolver beyond removing telegram-specific entries
  - Do NOT change how `manual`, `schedule`, `webhook` etc work

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 2)
  - **Parallel Group**: Wave 2 (with T8-T12)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  **Pattern References**:
  - `platform/triggers/resolver.py` — Read the entire file. Find `EVENT_TYPE_TO_COMPONENT` dict and `_match_telegram()` method. Remove telegram-specific code, keep everything else.

  **Acceptance Criteria**:
  - [ ] `"telegram_message"` not in `EVENT_TYPE_TO_COMPONENT`
  - [ ] `"telegram_chat"` not in `EVENT_TYPE_TO_COMPONENT`
  - [ ] `_match_telegram` method does not exist
  - [ ] `pytest tests/ -k resolver` → PASS

  **QA Scenarios**:
  ```
  Scenario: No telegram entries in resolver
    Tool: Bash (grep)
    Steps:
      1. Run: grep -n "telegram" platform/triggers/resolver.py
    Expected Result: 0 matches (or only in comments about removal)
    Evidence: .sisyphus/evidence/task-13-no-telegram-resolver.txt
  ```

  **Commit**: YES
  - Message: `refactor(triggers): remove telegram entries from resolver`
  - Files: `platform/triggers/resolver.py`
  - Pre-commit: `pytest tests/ -k resolver`

- [ ] 14. Remove telegram_poller + handler + Clean main.py

  **What to do**:
  - DELETE `platform/services/telegram_poller.py`
  - DELETE `platform/handlers/telegram.py`
  - DELETE `platform/tests/test_telegram_handler.py`
  - DELETE `platform/tests/test_telegram_poller.py` (if exists)
  - In `platform/main.py`:
    - Remove `from services.telegram_poller import recover_telegram_polling`
    - Remove the `recover_telegram_polling()` try/except block in lifespan
    - Remove any telegram-related imports
  - In `platform/tasks/__init__.py`:
    - Remove `poll_telegram_credential_task` function/wrapper
    - Remove telegram-related imports
  - In `platform/handlers/__init__.py`:
    - Remove any telegram-specific imports (verify `dispatch_event()` itself is unchanged)
  - Verify no remaining imports of deleted modules

  **Must NOT do**:
  - Do NOT change `dispatch_event()` logic in handlers/__init__.py
  - Do NOT change anything else in main.py beyond telegram removal

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 3)
  - **Parallel Group**: Wave 3 (with T15-T20)
  - **Blocks**: T19 (frontend needs old poll endpoints gone), T21 (test updates)
  - **Blocked By**: T8 (inbound endpoint must be working before removing old handler)

  **References**:
  **Pattern References**:
  - `platform/main.py` — Find `recover_telegram_polling` import and call. Remove both.
  - `platform/tasks/__init__.py` — Find `poll_telegram_credential_task`. Remove it.
  - `platform/handlers/__init__.py` — Verify no telegram imports remain. `dispatch_event()` should be clean.

  **Acceptance Criteria**:
  - [ ] Files deleted: `services/telegram_poller.py`, `handlers/telegram.py`, test files
  - [ ] `grep -r "telegram_poller" platform/ --include="*.py"` → 0 results (except alembic)
  - [ ] `grep -r "recover_telegram" platform/ --include="*.py"` → 0 results
  - [ ] `pytest tests/` → no import errors from deleted modules

  **QA Scenarios**:
  ```
  Scenario: Deleted files no longer exist
    Tool: Bash (ls)
    Steps:
      1. ls platform/services/telegram_poller.py 2>&1
      2. ls platform/handlers/telegram.py 2>&1
    Expected Result: "No such file or directory" for both
    Evidence: .sisyphus/evidence/task-14-files-deleted.txt

  Scenario: No dangling imports
    Tool: Bash (python)
    Steps:
      1. Run: python -c "import main" (from platform/ dir)
    Expected Result: No ImportError
    Evidence: .sisyphus/evidence/task-14-no-import-errors.txt
  ```

  **Commit**: YES
  - Message: `chore: remove telegram_poller + handler + clean main.py`
  - Files: (deleted files), `platform/main.py`, `platform/tasks/__init__.py`, `platform/handlers/__init__.py`
  - Pre-commit: `pytest tests/ -v`

- [ ] 15. Remove Chat Endpoints + Schemas

  **What to do**:
  - In `platform/api/executions.py`:
    - Remove `chat_router` and ALL associated code:
      - `send_chat_message()` endpoint
      - `get_chat_history()` endpoint
      - `delete_chat_history()` endpoint
      - `ChatMessageIn`, `ChatMessageOut` schemas (if defined inline)
    - Keep execution list/detail/cancel/batch-delete endpoints
  - In `platform/main.py` (or `api/__init__.py`):
    - Remove `from api.executions import chat_router` import
    - Remove `app.include_router(chat_router, ...)` line
  - In `platform/schemas/` — Remove `ChatMessageIn`/`ChatMessageOut`/`ChatHistoryOut` if defined in a schema file
  - Remove any tests specifically for chat endpoints
  - Verify no remaining references to chat_router

  **Must NOT do**:
  - Do NOT remove execution endpoints — only chat-related code
  - Do NOT change Conversation model — it stays for now

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 3)
  - **Parallel Group**: Wave 3 (with T14, T16-T20)
  - **Blocks**: T21 (test updates)
  - **Blocked By**: T8 (inbound replaces chat functionality)

  **References**:
  **Pattern References**:
  - `platform/api/executions.py:173-413` — The chat_router section to REMOVE. Read the file first to identify exact line ranges.
  - `platform/main.py` — Find `chat_router` import and `include_router` call.

  **Acceptance Criteria**:
  - [ ] `grep -r "chat_router" platform/ --include="*.py"` → 0 results
  - [ ] `grep -r "send_chat_message\|get_chat_history\|ChatMessageIn" platform/ --include="*.py"` → 0 results (except tests if kept as negative tests)
  - [ ] Execution list/detail/cancel still work

  **QA Scenarios**:
  ```
  Scenario: Chat endpoints removed
    Tool: Bash (curl)
    Steps:
      1. curl -X POST http://localhost:8000/api/v1/workflows/test/chat/ -H "Authorization: Bearer $TOKEN"
      2. Assert: 404 Not Found (endpoint no longer exists)
    Expected Result: 404
    Evidence: .sisyphus/evidence/task-15-chat-removed.txt
  ```

  **Commit**: YES
  - Message: `chore: remove chat endpoints + schemas`
  - Files: `platform/api/executions.py`, `platform/main.py`
  - Pre-commit: `pytest tests/ -v`

- [ ] 16. Remove Telegram Poll Start/Stop Endpoints

  **What to do**:
  - In `platform/api/nodes.py`:
    - Remove `POST /{slug}/nodes/{node_id}/telegram-poll/start/` endpoint
    - Remove `POST /{slug}/nodes/{node_id}/telegram-poll/stop/` endpoint
    - Remove any helper functions specific to these endpoints
    - Remove telegram-related imports
  - These endpoints are replaced by credential activate/deactivate (T9)
  - Remove any tests specifically for poll endpoints

  **Must NOT do**:
  - Do NOT change other node CRUD endpoints
  - Do NOT add new activate/deactivate endpoints here — those are on credentials (T9)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 3)
  - **Parallel Group**: Wave 3 (with T14-T15, T17-T20)
  - **Blocks**: T19 (frontend removes poll buttons)
  - **Blocked By**: T9 (credential API has activate/deactivate)

  **References**:
  **Pattern References**:
  - `platform/api/nodes.py:442-482` — The two poll endpoints to REMOVE. Read the file to confirm exact locations.
  - `platform/frontend/src/api/nodes.ts:30-34` — Frontend hooks that call these endpoints (removed in T19).

  **Acceptance Criteria**:
  - [ ] `grep -r "telegram-poll" platform/api/ --include="*.py"` → 0 results
  - [ ] `curl POST .../telegram-poll/start/` → 404

  **QA Scenarios**:
  ```
  Scenario: Poll endpoints removed
    Tool: Bash (grep)
    Steps:
      1. grep -rn "telegram.poll\|telegram-poll" platform/api/nodes.py
    Expected Result: 0 matches
    Evidence: .sisyphus/evidence/task-16-poll-removed.txt
  ```

  **Commit**: YES
  - Message: `chore: remove telegram poll start/stop endpoints`
  - Files: `platform/api/nodes.py`
  - Pre-commit: `pytest tests/ -k node`

- [ ] 17. Frontend Types + Remove chat.ts

  **What to do**:
  - DELETE `platform/frontend/src/api/chat.ts`
  - In `platform/frontend/src/types/models.ts`:
    - Change `CredentialType` from `"git" | "llm" | "telegram" | "tool"` to `"git" | "llm" | "gateway" | "tool"`
    - Remove `ChatMessage`, `ChatResponse` types (if they exist)
  - In `platform/frontend/src/api/nodes.ts`:
    - Remove `useStartTelegramPoll()` and `useStopTelegramPoll()` hooks (lines ~30-34)
  - Verify `npm run build` passes after changes

  **Must NOT do**:
  - Do NOT change component type definitions yet (trigger_telegram stays)
  - Do NOT change any other frontend files in this task

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 3)
  - **Parallel Group**: Wave 3 (with T14-T16, T18-T20)
  - **Blocks**: None
  - **Blocked By**: None (frontend types can be updated independently)

  **References**:
  **Pattern References**:
  - `platform/frontend/src/types/models.ts` — Find `CredentialType` literal type. Change `"telegram"` to `"gateway"`.
  - `platform/frontend/src/api/chat.ts` — The file to DELETE entirely.
  - `platform/frontend/src/api/nodes.ts` — Find poll hooks to remove.

  **Acceptance Criteria**:
  - [ ] `chat.ts` deleted
  - [ ] `CredentialType` includes `"gateway"`, not `"telegram"`
  - [ ] Poll hooks removed from nodes.ts
  - [ ] `npm run build` → 0 errors

  **QA Scenarios**:
  ```
  Scenario: Frontend builds without chat.ts
    Tool: Bash (npm)
    Preconditions: In platform/frontend/ directory
    Steps:
      1. Run: npm run build
    Expected Result: Build succeeds with 0 errors
    Evidence: .sisyphus/evidence/task-17-frontend-build.txt
  ```

  **Commit**: YES
  - Message: `refactor(frontend): update types + remove chat hooks`
  - Files: (delete chat.ts), `types/models.ts`, `api/nodes.ts`
  - Pre-commit: `npm run build`

- [ ] 18. CredentialsPage: Gateway Credential CRUD UI

  **What to do**:
  - In `platform/frontend/src/features/credentials/CredentialsPage.tsx`:
    - Replace `"telegram"` credential type option with `"gateway"` in the create dialog dropdown
    - Gateway form fields:
      - **Name** (text input, existing)
      - **Adapter Type** (dropdown: `telegram`, `generic`) — maps to `detail.adapter_type`
      - **Token** (password input) — sent to backend, not stored locally
      - **Config** (optional JSON textarea) — maps to `detail.config` for adapter-specific settings
    - After creation: token field disappears (not stored locally), show adapter_type in detail column
    - Table display: Show `adapter_type` from `detail.adapter_type` in the detail column (instead of masked bot_token)
    - Test button: Call existing `POST /credentials/{id}/test/` — show health status result
    - Add Activate/Deactivate buttons:
      - `POST /credentials/{id}/activate/` and `POST /credentials/{id}/deactivate/`
      - Show current status if available
    - Remove old Telegram-specific form fields (`bot_token`, `allowed_user_ids`)
  - Add TanStack Query hooks for activate/deactivate if not already in credentials.ts

  **Must NOT do**:
  - Do NOT show masked token after creation — token is not stored locally
  - Do NOT build per-adapter config schemas — keep Config as free-form JSON
  - Do NOT add gateway status polling — just show result of test/activate actions

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: UI component with form design, state management, conditional rendering
  - **Skills**: [`frontend-ui-ux`]
    - `frontend-ui-ux`: UI form redesign with conditional fields

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 3)
  - **Parallel Group**: Wave 3 (with T14-T17, T19-T20)
  - **Blocks**: None
  - **Blocked By**: T9 (credential API changes must be deployed)

  **References**:
  **Pattern References**:
  - `platform/frontend/src/features/credentials/CredentialsPage.tsx` — The entire file. Study the existing create dialog for LLM credentials (provider_type dropdown + api_key + base_url). Gateway form follows similar pattern but with adapter_type + token + config.
  - `platform/frontend/src/api/credentials.ts` — Existing hooks. May need to add `useActivateCredential()` and `useDeactivateCredential()` hooks calling `POST /credentials/{id}/activate/` and `/deactivate/`.
  **API/Type References**:
  - `platform/frontend/src/types/models.ts:CredentialType` — Now includes `"gateway"` (from T17)
  - Backend `POST /credentials/` — Request: `{name, credential_type: "gateway", detail: {adapter_type, token, config?}}`
  - Backend response detail for gateway: `{adapter_type: "telegram", gateway_credential_id: "my-bot"}`

  **Acceptance Criteria**:
  - [ ] Create dialog shows "Gateway" type with adapter_type dropdown + token + config fields
  - [ ] After creation: no token shown, adapter_type visible in table
  - [ ] Test button works (shows health status)
  - [ ] Activate/Deactivate buttons work
  - [ ] `npm run build` → 0 errors

  **QA Scenarios**:
  ```
  Scenario: Create gateway credential via UI
    Tool: Playwright (playwright skill)
    Preconditions: User logged in, on /credentials page
    Steps:
      1. Click "Create Credential" button
      2. Select type "Gateway" from dropdown
      3. Assert: adapter_type dropdown appears (options: telegram, generic)
      4. Select adapter_type "telegram"
      5. Fill name: "test-bot"
      6. Fill token: "123456:ABC-DEF"
      7. Click Submit
      8. Assert: new row appears in table with name "test-bot", type "gateway", adapter_type "telegram"
      9. Assert: no token value visible in the row
    Expected Result: Credential created, visible in table without token
    Failure Indicators: Token visible in UI, missing adapter_type column
    Evidence: .sisyphus/evidence/task-18-create-credential.png

  Scenario: Test button shows health status
    Tool: Playwright (playwright skill)
    Preconditions: Gateway credential exists and is active
    Steps:
      1. Click test button on gateway credential row
      2. Assert: health status shown (success/error indicator)
    Expected Result: Health check result displayed
    Evidence: .sisyphus/evidence/task-18-test-credential.png
  ```

  **Commit**: YES
  - Message: `feat(frontend): gateway credential CRUD UI`
  - Files: `platform/frontend/src/features/credentials/CredentialsPage.tsx`, `platform/frontend/src/api/credentials.ts`
  - Pre-commit: `npm run build`

- [ ] 19. NodeDetailsPanel: Remove ChatPanel + Poll Buttons

  **What to do**:
  - In `platform/frontend/src/features/workflows/components/NodeDetailsPanel.tsx`:
    - Remove `ChatPanel` component entirely (the function component + all its imports)
    - Remove the conditional render that shows `<ChatPanel>` for trigger_chat nodes
    - Remove imports: `useSendChatMessage`, `useChatHistory`, `useDeleteChatHistory`
    - Remove poll start/stop buttons for trigger_telegram nodes:
      - Remove "Start Polling" and "Stop Polling" buttons
      - Remove `useStartTelegramPoll()` and `useStopTelegramPoll()` hook calls
    - For trigger_telegram and trigger_chat nodes in the side panel:
      - Keep the credential selector dropdown (user assigns gateway credential)
      - Remove any Telegram-specific UI elements
  - Verify no compile errors

  **Must NOT do**:
  - Do NOT change the credential selector — it stays
  - Do NOT change node config editing for other node types
  - Do NOT add new gateway-specific UI elements (activate/deactivate is on credentials page)

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: Component removal with careful cleanup of imports and conditional rendering
  - **Skills**: [`frontend-ui-ux`]

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 3)
  - **Parallel Group**: Wave 3 (with T14-T18, T20)
  - **Blocks**: None
  - **Blocked By**: T14 (old handler removed), T16 (poll endpoints removed)

  **References**:
  **Pattern References**:
  - `platform/frontend/src/features/workflows/components/NodeDetailsPanel.tsx` — Read the FULL file. Find:
    - `ChatPanel` function component definition
    - Conditional render `{selectedNode?.type === 'trigger_chat' && <ChatPanel .../>}`
    - Poll start/stop buttons and their hook imports
    - Remove all of these.
  - `platform/frontend/src/api/chat.ts` — Already deleted in T17. Verify no remaining imports.

  **Acceptance Criteria**:
  - [ ] `ChatPanel` component removed from NodeDetailsPanel.tsx
  - [ ] No imports from `api/chat.ts`
  - [ ] No poll start/stop buttons
  - [ ] `npm run build` → 0 errors

  **QA Scenarios**:
  ```
  Scenario: trigger_chat node panel has no chat widget
    Tool: Playwright (playwright skill)
    Preconditions: Workflow with trigger_chat node, user on editor page
    Steps:
      1. Click on trigger_chat node
      2. Assert: NodeDetailsPanel shows (right sidebar)
      3. Assert: NO chat input/message area visible
      4. Assert: credential selector is still visible
    Expected Result: Clean panel with config only, no chat widget
    Evidence: .sisyphus/evidence/task-19-no-chat-panel.png

  Scenario: trigger_telegram node panel has no poll buttons
    Tool: Playwright (playwright skill)
    Preconditions: Workflow with trigger_telegram node
    Steps:
      1. Click on trigger_telegram node
      2. Assert: NO "Start Polling" or "Stop Polling" buttons
      3. Assert: credential selector is still visible
    Expected Result: Clean panel without poll controls
    Evidence: .sisyphus/evidence/task-19-no-poll-buttons.png
  ```

  **Commit**: YES
  - Message: `refactor(frontend): remove ChatPanel + poll buttons from NodeDetailsPanel`
  - Files: `platform/frontend/src/features/workflows/components/NodeDetailsPanel.tsx`
  - Pre-commit: `npm run build`

- [ ] 20. Frontend Cleanup: Palette Descriptions + Canvas

  **What to do**:
  - In `platform/frontend/src/features/workflows/components/NodePalette.tsx`:
    - Update `trigger_telegram` description to mention gateway
    - Update `trigger_chat` description: "External chat via gateway" (was: "Browser chat interface")
  - In `platform/frontend/src/features/workflows/components/WorkflowCanvas.tsx`:
    - Verify trigger node colors/icons still work for both types
    - No functional changes needed — just verify
  - Verify `npm run build` passes

  **Must NOT do**:
  - Do NOT add new trigger types to the palette
  - Do NOT change node icons or colors — keep existing visual identity

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 3)
  - **Parallel Group**: Wave 3 (with T14-T19)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  **Pattern References**:
  - `platform/frontend/src/features/workflows/components/NodePalette.tsx` — Find GROUPS array with trigger types. Update descriptions.
  - `platform/frontend/src/features/workflows/components/WorkflowCanvas.tsx` — `BORDER_COLORS` and `NODE_ICONS` for triggers. Verify they still work.

  **Acceptance Criteria**:
  - [ ] Palette descriptions updated for both trigger types
  - [ ] `npm run build` → 0 errors

  **QA Scenarios**:
  ```
  Scenario: Updated trigger descriptions in palette
    Tool: Playwright (playwright skill)
    Preconditions: User on workflow editor page
    Steps:
      1. Look at NodePalette (left sidebar)
      2. Find trigger_telegram — assert description mentions gateway
      3. Find trigger_chat — assert description mentions "external chat" or "gateway"
    Expected Result: Updated descriptions visible
    Evidence: .sisyphus/evidence/task-20-palette-descriptions.png
  ```

  **Commit**: YES
  - Message: `chore(frontend): update palette + canvas descriptions for gateway`
  - Files: `platform/frontend/src/features/workflows/components/NodePalette.tsx`
  - Pre-commit: `npm run build`

- [ ] 21. Update conftest + Fixtures + Affected Test Files

  **What to do**:
  - In `platform/tests/conftest.py`:
    - Update `UserProfile` fixture: `telegram_user_id=111222333` → `external_user_id=111222333`
    - Add `GatewayCredential` fixture (if needed for other tests)
    - Remove any `TelegramCredential` fixture
    - Ensure GATEWAY_* settings are set to test values (empty or mock URLs)
  - Scan ALL test files for references to:
    - `telegram_user_id` → `external_user_id`
    - `TelegramCredential` → `GatewayCredential` (or remove)
    - `telegram_chat_id` on PendingTask → `chat_id`
    - `bot_token` in credential detail → remove or replace with gateway detail
    - `chat_router` → remove
    - `poll_telegram` → remove
    - `send_chat_message` → remove
  - Use `ast_grep_search` and `grep` to find ALL affected test files
  - Update each reference to use the new field names / types
  - Run `pytest tests/ -v` and fix ALL failures

  **Must NOT do**:
  - Do NOT delete tests that test still-relevant functionality — update them
  - Do NOT skip test files — ALL must pass

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Bulk updates across ~20 test files, need to be thorough
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (must run after all code changes)
  - **Parallel Group**: Wave 4 (with T22)
  - **Blocks**: F1-F4
  - **Blocked By**: T3 (external_user_id), T14 (telegram removal), T15 (chat removal)

  **References**:
  **Pattern References**:
  - `platform/conftest.py` — The main fixture file. Start here.
  - `platform/tests/test_api.py` — Likely has credential creation tests with `credential_type="telegram"`
  - `platform/tests/test_api_extended.py` — More API tests
  - All files in `platform/tests/` — scan with grep for affected symbols
  **External References**:
  - Use `grep -r "telegram_user_id\|TelegramCredential\|telegram_chat_id\|bot_token\|chat_router\|poll_telegram" platform/tests/ --include="*.py" -l` to find all affected files.

  **Acceptance Criteria**:
  - [ ] `pytest tests/ -v` → ALL tests pass (0 failures)
  - [ ] `grep -r "telegram_user_id" platform/tests/ --include="*.py"` → 0 results
  - [ ] `grep -r "TelegramCredential" platform/tests/ --include="*.py"` → 0 results
  - [ ] `grep -r "telegram_chat_id" platform/tests/ --include="*.py"` → 0 results (except negative tests)

  **QA Scenarios**:
  ```
  Scenario: All tests pass
    Tool: Bash (pytest)
    Steps:
      1. Run: cd platform && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
    Expected Result: All tests pass, 0 failures, 0 errors
    Failure Indicators: Any FAILED or ERROR in output
    Evidence: .sisyphus/evidence/task-21-all-tests-pass.txt

  Scenario: No old references in test files
    Tool: Bash (grep)
    Steps:
      1. Run: grep -r "telegram_user_id\|TelegramCredential\|telegram_chat_id" platform/tests/ --include="*.py" -l
    Expected Result: 0 files found
    Evidence: .sisyphus/evidence/task-21-no-old-refs.txt
  ```

  **Commit**: YES
  - Message: `test: update fixtures + affected test files for gateway migration`
  - Files: `platform/conftest.py`, `platform/tests/*.py` (multiple)
  - Pre-commit: `pytest tests/ -v`

- [ ] 22. Integration Test: Full Inbound → Execution → Outbound Flow

  **What to do**:
  - Create `platform/tests/test_gateway_integration.py`:
  - RED: Write integration test that covers the full message flow:
    1. Setup: Create workflow with trigger_telegram node, mock gateway_client
    2. Send POST to `/api/v1/inbound` with valid payload
    3. Assert: execution created (status pending/running)
    4. Mock LangGraph execution completing with output
    5. Assert: `delivery.deliver()` calls `gateway_client.send_message()` with correct credential_id, chat_id, formatted output
  - RED: Write test for confirmation flow:
    1. Setup: Execution interrupted with PendingTask
    2. Send POST to `/api/v1/inbound` with text `/confirm_{task_id}`
    3. Assert: execution resumes
    4. Assert: confirmation response sent via gateway
  - RED: Write test for file handling:
    1. Send inbound with attachments
    2. Assert: file tags appended to text in event_data
    3. Assert: files list in event_data has correct schema `{filename, mime_type, size_bytes, url}`
  - GREEN: These tests should all pass if T8-T11 are correctly implemented. If any fail, investigate and fix.
  - REFACTOR: Clean up

  **Must NOT do**:
  - Do NOT require a running gateway — all gateway calls are mocked
  - Do NOT test gateway itself — only test pipelit's gateway integration

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Complex integration test spanning multiple services (inbound → dispatch → execution → delivery)
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T21)
  - **Parallel Group**: Wave 4 (with T21)
  - **Blocks**: F1-F4
  - **Blocked By**: T8 (inbound), T10 (delivery), T11 (orchestrator)

  **References**:
  **Pattern References**:
  - `platform/tests/test_api.py` — Existing API test patterns with TestClient and fixtures
  - `platform/conftest.py` — Fixtures for db, user, workflow creation
  **API/Type References**:
  - `platform/api/inbound.py` (from T8) — The endpoint being tested
  - `platform/services/delivery.py` (from T10) — Delivery being verified
  - `platform/services/orchestrator.py` (from T11) — Interrupt flow being verified

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_gateway_integration.py -v` → ALL pass
  - [ ] Full flow tested: inbound → execution → delivery
  - [ ] Confirmation flow tested: interrupt → confirm → resume
  - [ ] File handling tested: attachments → file tags

  **QA Scenarios**:
  ```
  Scenario: Full integration test passes
    Tool: Bash (pytest)
    Steps:
      1. Run: pytest tests/test_gateway_integration.py -v --tb=long
    Expected Result: All integration tests pass
    Failure Indicators: Any FAILED test
    Evidence: .sisyphus/evidence/task-22-integration-tests.txt

  Scenario: Confirmation flow works end-to-end
    Tool: Bash (pytest)
    Steps:
      1. Run: pytest tests/test_gateway_integration.py -k "confirm" -v
    Expected Result: Confirmation test passes — interrupt, confirm, resume all work
    Evidence: .sisyphus/evidence/task-22-confirmation-flow.txt
  ```

  **Commit**: YES
  - Message: `test: add integration test for gateway flow`
  - Files: `platform/tests/test_gateway_integration.py`
  - Pre-commit: `pytest tests/test_gateway_integration.py -v`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE. Rejection → fix → re-run.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest tests/ -v` + any linter. Review all changed files for: `as any`/`@ts-ignore`, empty catches, `console.log` in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names. Verify no `bot_token` stored locally. Verify no `batch_alter_table` in migrations.
  Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill for frontend)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (inbound → execution → outbound delivery). Test edge cases: empty text with files, missing source.from, inactive workflow. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| Order | Message | Files | Pre-commit |
|-------|---------|-------|------------|
| 1 | `feat(config): add gateway settings` | config.py | pytest tests/test_config.py |
| 2 | `feat(models): add GatewayCredential model + migration` | models/credential.py, alembic/... | pytest tests/ -k credential |
| 3 | `refactor(models): rename telegram_user_id to external_user_id` | models/user.py, alembic/... | pytest tests/ -k user |
| 4 | `refactor(models): generalize PendingTask columns` | models/execution.py, alembic/... | pytest tests/ -k pending |
| 5 | `feat(schemas): add inbound schemas + gateway auth` | schemas/inbound.py, auth.py | pytest tests/ |
| 6 | `feat(services): add gateway HTTP client` | services/gateway_client.py, tests/... | pytest tests/test_gateway_client.py |
| 7 | `chore(schemas): update trigger node type descriptions` | schemas/node_type_defs.py | pytest tests/ |
| 8 | `feat(api): add inbound webhook endpoint` | api/inbound.py, tests/... | pytest tests/test_inbound.py |
| 9 | `refactor(api): sync credential CRUD with gateway` | api/credentials.py, tests/... | pytest tests/ -k credential |
| 10 | `refactor(services): replace delivery with gateway outbound` | services/delivery.py, tests/... | pytest tests/ -k delivery |
| 11 | `refactor(services): update orchestrator interrupt flow` | services/orchestrator.py, tests/... | pytest tests/ -k orchestrator |
| 12 | `refactor(components): rename user_context key to chat_id` | components/agent.py, components/deep_agent.py | pytest tests/ |
| 13 | `refactor(triggers): remove telegram entries from resolver` | triggers/resolver.py | pytest tests/ -k resolver |
| 14 | `chore: remove telegram_poller + handler + clean main.py` | (delete files), main.py, tasks/ | pytest tests/ |
| 15 | `chore: remove chat endpoints + schemas` | api/executions.py, schemas/ | pytest tests/ |
| 16 | `chore: remove telegram poll start/stop endpoints` | api/nodes.py | pytest tests/ |
| 17 | `refactor(frontend): update types + remove chat hooks` | types/models.ts, api/chat.ts | npm run build |
| 18 | `feat(frontend): gateway credential CRUD UI` | CredentialsPage.tsx | npm run build |
| 19 | `refactor(frontend): remove ChatPanel + poll buttons` | NodeDetailsPanel.tsx | npm run build |
| 20 | `chore(frontend): update palette + canvas descriptions` | NodePalette.tsx, WorkflowCanvas.tsx | npm run build |
| 21 | `test: update fixtures + affected test files` | tests/conftest.py, tests/... | pytest tests/ -v |
| 22 | `test: add integration test for gateway flow` | tests/test_gateway_integration.py | pytest tests/ -v |

---

## Success Criteria

### Verification Commands
```bash
# All tests pass
cd platform && python -m pytest tests/ -v  # Expected: all pass, 0 failures

# Frontend builds
cd platform/frontend && npm run build  # Expected: 0 errors

# Inbound endpoint works
curl -X POST http://localhost:8000/api/v1/inbound \
  -H "Authorization: Bearer $GATEWAY_INBOUND_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"route":{"workflow_slug":"test","trigger_node_id":"trigger_abc"},...}'
# Expected: 202

# No telegram references in active code
grep -r "TelegramCredential" platform/ --include="*.py" -l  # Expected: 0 results (except alembic)
grep -r "telegram_poller" platform/ --include="*.py" -l  # Expected: 0 results
grep -r "poll_telegram" platform/ --include="*.py" -l  # Expected: 0 results

# No bot_token in DB
sqlite3 platform/pipelit.db "SELECT * FROM credentials WHERE credential_type='telegram'"  # Expected: 0 rows
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass (pytest + npm build)
- [ ] No bot_token stored locally
- [ ] Inbound → Execution → Outbound flow works end-to-end
- [ ] Frontend credential CRUD creates/deletes gateway credentials
- [ ] Dead code fully removed (no telegram_poller, handler, chat endpoints, ChatPanel)
