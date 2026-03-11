# Gateway Integration Architectural Decisions

## Session 1 Decisions
1. Pipelit manages credentials via gateway admin API — bot tokens never stored in Pipelit
2. Chat trigger exists but browser chat UI removed
3. Outbound via POST /gateway/api/v1/send
4. One-shot migration, no gradual rollout
5. Frontend does NOT know about gateway — single Pipelit WebSocket only
6. Gateway unavailable = error (block operations like credential CRUD)
7. No inline keyboard / callback_query — out of scope
8. Remove browser chat completely
9. Inbound auth: GATEWAY_INBOUND_TOKEN service token, separate verify_gateway_token() dependency
10. Outbound failure: silent failure + log warning
11. UserProfile: telegram_user_id → external_user_id (BigInteger, same type)
12. thread_id: {user_id}:{chat_id}:{workflow_id}
13. Keep both trigger_telegram + trigger_chat (no merge)
14. Credential UI: Name + Adapter Type + Token + optional Config JSON
15. Test button: GET /admin/health for active credentials
16. No auto-create credentials on trigger node creation
17. TDD strategy

## Key API Contracts (msg-gateway)
- POST /admin/credentials: {id, adapter, token, active?, config?, route?} → {id, status:"created"}
- PUT /admin/credentials/{id}: all optional → {id, status:"updated"}
- DELETE /admin/credentials/{id}: → {id, status:"deleted"}
- PATCH /admin/credentials/{id}/activate → {id, status:"activated|already_active"}
- PATCH /admin/credentials/{id}/deactivate → {id, status:"deactivated|already_inactive"}
- POST /api/v1/send: {credential_id, chat_id, text, reply_to_message_id?, extra_data?, file_ids?}
- POST /api/v1/files: multipart {file, filename?, mime_type?} → {file_id, filename, ...}
- GET /admin/health: includes adapters array with {credential_id, adapter, health, failures}
- Error format: {"error": "string"} with HTTP 4xx/5xx
