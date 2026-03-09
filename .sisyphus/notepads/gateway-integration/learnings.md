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
