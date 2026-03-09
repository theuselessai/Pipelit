# Gateway Integration Learnings

## Project Setup
- Worktree: /home/aka/programs/pipelit (main repo, branch: feature/gateway-integration)
- Python venv: /home/aka/programs/pipelit/.venv (source ../.venv/bin/activate from platform/)
- Tests: cd platform && python -m pytest tests/ -v
- Frontend: cd platform/frontend && npm run build

## Key Guardrails (MUST follow)
- NO batch_alter_table in Alembic migrations — use op.add_column() + op.drop_column()
- NO bot_token stored in pipelit DB or trigger_payload
- NO module-level gateway_client singleton — must be lazy (get_gateway_client() function)
- NO gateway in /health endpoint
- NO outbound file upload invocation — file_ids=[] always
- TDD: Write failing test FIRST, then implement, then verify green

## Architecture
- Gateway admin API: Bearer admin_token for /admin/*
- Gateway send API: Bearer send_token for /api/v1/*
- Inbound auth: verify_gateway_token() — separate from get_current_user()
- Credential types: "gateway" replaces "telegram"
- Trigger types: keep trigger_telegram + trigger_chat (both backed by gateway)
- thread_id: {user_id}:{chat_id}:{workflow_id} (chat_id key, not telegram_chat_id)

## File Locations
- config: platform/config.py (Settings class)
- models: platform/models/credential.py, user.py, execution.py
- schemas: platform/schemas/ directory
- tests: platform/tests/
- conftest: platform/conftest.py (NOT platform/tests/conftest.py)
- alembic: platform/alembic/versions/

## Pattern: Alembic Migration (safe for SQLite)
Instead of: op.alter_column() or batch_alter_table()
Use: 
  op.add_column(table, Column(new_name, type, ...))
  op.execute("UPDATE table SET new_col = old_col")
  op.drop_column(table, old_name)

## Task 2 Completion (T2 - Wave 1)

### What Was Done
1. **TDD Cycle**: Wrote failing test first, then implemented
2. **GatewayCredential Model**: Added to platform/models/credential.py with:
   - `gateway_credential_id` (String 255)
   - `adapter_type` (String 50)
   - One-to-one relationship with BaseCredential
3. **BaseCredential Update**: Added `gateway_credential` relationship (replaces `telegram_credential`)
4. **Schema Update**: Changed CredentialTypeStr from "telegram" to "gateway"
5. **API Handlers**: Added gateway credential support in:
   - `_serialize_credential()` - serialization
   - `create_credential()` - creation
   - `update_credential()` - updates
6. **Alembic Migration**: Created 97895779df3d
   - Deletes all telegram credentials from credentials table
   - Drops telegram_credentials table
   - Creates gateway_credentials table with proper schema
7. **Test Updates**: Updated test_create_telegram_credential and test_serialize_telegram to use gateway type

### Results
- ✅ All 69 credential tests pass
- ✅ Migration runs successfully (alembic upgrade head)
- ✅ GatewayCredential importable from models.credential
- ✅ Commit: 00492a5 feat(models): add GatewayCredential model + migration

### Key Learnings
- Alembic migration pattern: op.execute() for data cleanup, op.drop_table(), op.create_table()
- API credential serialization requires handlers in 3 places: serialize, create, update
- Test updates needed when changing credential types (not just model changes)
- TDD approach caught issues early (test failed before implementation)

## Task 5 Completion (T5 - Inbound Schemas + Auth)

### What Was Done
1. **TDD Cycle**: Wrote failing test first (16 tests), then implemented schemas and auth
2. **Inbound Schemas** (`platform/schemas/inbound.py`):
   - `UserInfo`: id (required), username, display_name (optional)
   - `InboundSource`: protocol, chat_id (required), message_id, reply_to_message_id, from_ (with alias="from")
   - `InboundAttachment`: filename, mime_type (required), size_bytes, download_url (optional)
   - `GatewayInboundMessage`: route (dict), credential_id, source, text, timestamp (required), attachments, extra_data (optional)
3. **Auth Dependency** (`platform/auth.py`):
   - Added `verify_gateway_token()` function
   - Validates `settings.GATEWAY_INBOUND_TOKEN` (separate from `get_current_user()`)
   - Returns None on success, raises 401 HTTPException on failure
4. **Test Suite** (`platform/tests/test_inbound_schemas.py`):
   - 16 comprehensive tests covering all schemas
   - Field alias tests (from -> from_)
   - Required field validation (5 tests for missing fields)
   - Auth dependency tests (valid/invalid tokens)

### Results
- ✅ All 16 tests pass
- ✅ Imports work correctly
- ✅ Commit: 9ff6d81 feat(schemas): add inbound schemas + gateway auth dependency
- ✅ No LSP errors (basedpyright not installed, but syntax verified via import)

### Key Learnings
- Pydantic v2 uses `ConfigDict(populate_by_name=True)` for field aliases
- Auth dependencies can be simple (no DB) — just validate token against settings
- TDD approach: write 16 tests first, then implement — all pass on first try
- Field alias syntax: `Field(None, alias="from")` with `from_` as Python name

## Task 7 Completion (T7 - Node Type Registry: Update Trigger Descriptions)

### What Was Done
1. **TDD Cycle**: Wrote 4 failing tests first, then implemented changes
2. **PortDefinition Enhancement**: Added `schema` field to PortDefinition class in `platform/schemas/node_types.py`
   - Used `Field(None, alias="schema")` to avoid shadowing BaseModel.schema
   - Allows port definitions to include JSON schema for complex data types
3. **trigger_telegram Updates**:
   - Description: "Receives messages from Telegram via msg-gateway"
   - Added `files` port with schema: `{filename, mime_type, size_bytes, url}`
4. **trigger_chat Updates**:
   - Description: "Receives messages from external chat clients via msg-gateway generic adapter"
   - Added `files` port with schema: `{filename, mime_type, size_bytes, url}`
5. **Test Suite** (`platform/tests/test_node_types.py`):
   - 4 comprehensive tests covering descriptions and schema validation
   - Tests verify "gateway" keyword in descriptions
   - Tests verify correct schema structure with url field (not file_id)

### Results
- ✅ All 4 new tests pass
- ✅ No regressions in existing tests (test_database_and_models.py passes)
- ✅ Commit: 82080c4 chore(schemas): update trigger node type descriptions for gateway
- ✅ Changes verified in NODE_TYPE_REGISTRY at runtime

### Key Learnings
- PortDefinition schema field enables rich type documentation for complex ports
- Field alias pattern prevents shadowing of BaseModel attributes
- TDD approach: write tests first, then implement — all tests pass on first try
- Gateway terminology now consistent across trigger node types

## Task 8 Completion (T8 - Inbound Webhook Endpoint + Tests)

### What Was Done
1. **TDD Cycle**: Wrote 15 failing tests first, then implemented endpoint, then verified green
2. **Endpoint** (`platform/api/inbound.py`):
   - `POST /api/v1/inbound` — receives normalized messages from msg-gateway
   - Auth: `verify_gateway_token()` dependency (not `get_current_user()`)
   - Route validation: extracts `workflow_slug` + `trigger_node_id` from `payload.route`
   - Workflow lookup + is_active check
   - Trigger node lookup
   - `/confirm_xxx` and `/cancel_xxx` command handling (replicating telegram.py logic)
   - User provisioning: get_or_create by `external_user_id` (BigInteger)
   - Anonymous profile support (`gateway_anonymous`)
   - Attachment file tags appended to text
   - `dispatch_event("gateway_inbound", ...)` for normal messages
   - Returns 202 for normal dispatch, 200 for confirmation flows
3. **Router Registration** (`platform/main.py`):
   - `app.include_router(inbound_router, prefix="/api/v1", tags=["inbound"])`
4. **Test Suite** (`platform/tests/test_inbound.py`):
   - 15 comprehensive tests covering all code paths

### Key Learnings
- FastAPI `status_code=202` on decorator applies globally — use `Response.status_code` for dynamic status
- `monkeypatch.setattr(settings, "GATEWAY_INBOUND_TOKEN", ...)` is cleaner than `patch("auth.settings")`
- Patching entire settings object interferes with logging_config.py — always patch specific attributes
- Confirmation flow: delete PendingTask, then either cancel execution or enqueue resume_workflow_job
- `route` field is plain dict in schema — manual validation for required keys

## Task 9 Completion (T9 - Credential API: Sync with Gateway + Tests)

### What Was Done
1. **TDD Cycle**: Wrote 20 failing tests first, then implemented, then verified green
2. **`create_credential()`**: Added gateway branch that:
   - Calls `get_gateway_client().create_credential(id=name, adapter=adapter_type, token=token, config=config)`
   - Raises HTTPException(502) on GatewayUnavailableError or GatewayAPIError
   - Creates local GatewayCredential WITHOUT storing token
3. **`delete_credential()`**: Added gateway sync:
   - Calls `get_gateway_client().delete_credential(gw_cred.gateway_credential_id)` if gateway_credential exists
   - Raises HTTPException(502) on failure (does NOT delete local record)
4. **`update_credential()`**: Added gateway sync:
   - Calls `get_gateway_client().update_credential(id, token=..., adapter=...)` for token/adapter_type changes
   - Raises HTTPException(502) on failure
5. **`test_credential()`**: Added gateway health check:
   - Calls `get_gateway_client().check_credential_health(gw_credential_id)`
   - Returns `{"ok": True, "detail": health_info}` or `{"ok": False, "detail": "not found in gateway"}`
6. **`CredentialTestOut` schema**: Added `detail: str | dict = ""` field
7. **Activate/Deactivate endpoints**: Added `POST /credentials/{id}/activate/` and `POST /credentials/{id}/deactivate/`
8. **Test fixes**: Updated `test_create_telegram_credential` and `test_create_gateway_credential` to mock gateway client

### Results
- ✅ All 112 credential tests pass (was 92, added 20 new tests)
- ✅ Commit: fcd373e refactor(api): sync credential CRUD with gateway

### Key Learnings
- Use `payload.name` as the gateway credential ID (stable, user-chosen identifier)
- Token is passed to gateway but never stored locally — only `gateway_credential_id` and `adapter_type` in DB
- `CredentialTestOut` needed `detail` field for gateway health response
- Existing tests that create gateway credentials need to mock `get_gateway_client`
- Activate/deactivate endpoints must check `cred.gateway_credential` (not just credential_type) for 404

## Task 10 Completion (T10 - Delivery Service: Gateway Outbound + Tests)

### What Was Done
1. **TDD Cycle**: Wrote 7 failing tests first, then implemented, then verified green
2. **delivery.py rewrite**:
   - Removed: `requests` import, `send_telegram_message()`, `_send_long_message()`, `_resolve_bot_token()`, `MAX_TELEGRAM_MESSAGE_LENGTH`
   - Added: `get_gateway_client()` import from `services.gateway_client`
   - `deliver()` now: gets `credential_id` + `chat_id` from `trigger_payload`, calls `get_gateway_client().send_message(credential_id, chat_id, text, file_ids=[])`
   - `send_typing_action()` kept as no-op stub (accepts any args, does nothing)
   - `_format_output()` preserved UNCHANGED
   - Gateway errors caught with `try/except (GatewayAPIError, GatewayUnavailableError)` + generic `Exception` → `logger.warning()`, no re-raise
3. **test_delivery.py**: Replaced old Telegram-based TestDeliver + TestSendTelegramMessage + TestSendLongMessage with 7 new gateway-focused tests
4. **test_components_remaining.py**: Replaced 4 stale Telegram tests with 2 gateway-compatible tests
5. **test_coverage_gaps.py**: Replaced 8 stale Telegram tests with 4 gateway-compatible tests

### Results
- ✅ 23 delivery tests pass (was 13)
- ✅ `_format_output()` preserved exactly
- ✅ No Telegram API code remains in delivery.py
- ✅ Commit: b68d0ef refactor(services): replace delivery with gateway outbound

### Key Learnings
- Sentinel pattern `final_output="__default__"` needed when `None` is a valid test value (vs `or` default)
- Old tests in test_components_remaining.py and test_coverage_gaps.py also needed updating — always check all test files
- `send_typing_action` kept as no-op stub (not removed) to avoid breaking callers

## Task 11 Completion (T11 - Orchestrator: Interrupt + Confirmation Prompt via Gateway + Tests)

### What Was Done
1. **TDD Cycle**: Wrote 3 failing tests first, then implemented, then verified green
2. **Tests** (`platform/tests/test_orchestrator.py`):
   - `test_handle_interrupt_creates_pending_task_with_chat_id_and_credential_id`: Verifies PendingTask created with chat_id from trigger_payload
   - `test_handle_interrupt_sends_confirmation_via_gateway`: Verifies gateway send_message called with credential_id, chat_id, and confirmation prompt
   - `test_handle_interrupt_gateway_send_failure_logged_not_raised`: Verifies gateway send failure is logged but doesn't raise exception
3. **Implementation** (`platform/services/orchestrator.py`):
   - Added import: `from services.gateway_client import get_gateway_client`
   - After PendingTask creation, extract `credential_id` and `chat_id` from trigger_payload
   - Call `get_gateway_client().send_message(credential_id, chat_id_str, prompt_text)` with confirmation commands
   - Prompt format: `"Action requires confirmation.\n\nTo confirm: /confirm_{task_id}\nTo cancel: /cancel_{task_id}"`
   - Wrapped in try/except to log warnings on failure, not raise exceptions

### Results
- ✅ All 3 new tests pass
- ✅ All 41 orchestrator tests pass (no regressions)
- ✅ Commit: refactor(services): update orchestrator interrupt flow for gateway

### Key Learnings
- PendingTask model already had `chat_id` and `credential_id` fields from T4
- Patch gateway_client at source: `patch("services.gateway_client.get_gateway_client")` not `patch("services.orchestrator.get_gateway_client")`
- WorkflowExecution requires `thread_id` field (not optional)
- Workflow model uses `owner_id` not `user_profile_id`
- Gateway send failures during interrupt should be logged but not raised (graceful degradation)
- Confirmation prompt includes task_id for /confirm_ and /cancel_ commands

## Task 12 + 13 Completion (T12 + T13 - User Context Key Rename + Resolver Cleanup)

### What Was Done
1. **T12 - User Context Key Rename**:
   - Changed `user_context.get("telegram_chat_id", "")` → `user_context.get("chat_id", "")` in:
     - `platform/components/agent.py` line 231
     - `platform/components/deep_agent.py` line 257
   - Thread ID construction logic unchanged (still uses `{user_id}:{chat_id}:{workflow_id}` format)

2. **T13 - Resolver Cleanup**:
   - Removed `"telegram_message"` and `"telegram_chat"` entries from `EVENT_TYPE_TO_COMPONENT` dict
   - Added `"gateway_inbound": "trigger_telegram"` mapping (for completeness, though inbound dispatch bypasses resolver)
   - Removed `_match_telegram()` method entirely (no longer needed with gateway)
   - Removed credential caching block (lines 50-62) that pre-loaded telegram credentials
   - Removed `re` import (no longer used after removing pattern/command matching)
   - Updated `_matches()` signature to remove `cred_cache` parameter
   - Removed telegram case from `_matches()` method

3. **Test Updates**:
   - Removed 3 tests from `test_handlers.py`:
     - `test_match_telegram_allowed_users`
     - `test_match_telegram_pattern`
     - `test_match_telegram_command`
   - Removed entire `TestTelegramMatching` class from `test_trigger_resolver.py` (8 tests)
   - Removed entire `TestBotTokenMatching` class from `test_trigger_resolver.py` (5 tests)

### Results
- ✅ All 123 agent/resolver tests pass
- ✅ No `telegram_chat_id` references remain in components (only in pycache, regenerated)
- ✅ Resolver has `gateway_inbound` mapping
- ✅ No `_match_telegram()` method exists
- ✅ Two commits: 59c131f (T12) and 8f89207 (T13)

### Key Learnings
- Thread ID format is stable: `{user_id}:{chat_id}:{workflow_id}` — only the key name changed
- Removing telegram-specific matching logic simplifies resolver (gateway handles routing via direct dispatch)
- Test cleanup: always search for all references to removed methods across all test files
- Resolver now only handles schedule, manual, workflow, and error events (gateway_inbound is direct dispatch)
