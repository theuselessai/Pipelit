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
