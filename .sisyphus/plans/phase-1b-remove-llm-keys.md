# Plan: Phase 1(b) — Remove real LLM keys from Pipelit (make the gateway trust boundary real)

## Context
Phase 1(a) routed LLM calls through agentgateway but left it feature-flagged OFF and left raw
provider API keys living in Pipelit's DB with a still-live direct-provider code path. Phase 1(b)
(Pipelit#188) closes that gap: agentgateway becomes the sole holder of LLM credentials, Pipelit's
workflow code holds only a short-lived ES256 JWT, the flag defaults ON, and the direct-key path plus
DB key storage are removed. This is a **hard cutover** — no live user credentials exist, so
rollback/idempotency/zero-downtime are nice-to-have, not P0.

**This migration is largely ALREADY BUILT on `feat/agentgateway-integration` but unfinished.** The job
is audit → fix → harden → land, not author-from-scratch.

## Ground-truth file map (verified against current branches)

**pipelit** (`~/Programs/pipelit.ai/pipelit`, branch `feat/agentgateway-integration`):
- `platform/services/llm.py`
  - `create_llm_from_db` — agentgateway path `147-163`; **direct-provider fallback `165-216`** (reads `credential.api_key`).
  - `_fake_credential_from_route` **`87-102`** (empty `api_key=""` trap) + `_route_provider_to_type` `78-84`.
  - `resolve_llm_for_node` `319-462` — **TWO paths**: `ai_model` component direct (`342-396`) AND AI node via `llm_model_config_id` FK (`398-455`); each has a `backend_route` branch and a legacy credential branch.
  - `resolve_credential_for_node` `465-510` — web-search provider detection; calls `_fake_credential_from_route` at `485`/`500`.
- `platform/services/agentgateway_config.py` — `write_provider_key` `83-98` (Fernet), `add_provider` `112-147`, **`add_model` `180-203` (writes `model: <model_name>` — this is where the model-id bug lands)**, `list_all_available_models` `240-276`.
- `platform/services/agentgateway_client.py` — `create_proxied_llm` `37-101` (base_url = `{gw}/{backend_name}`, JWT bearer; anthropic via `default_headers`), `check_agentgateway_health` `104-131`.
- `platform/services/jwt_issuer.py` — `mint_llm_token` `20-75`, ES256, 60s lifetime, `kid=pipelit-001`, needs `settings.JWT_PRIVATE_KEY`.
- `platform/cli/__main__.py` — `_resolve_provider_name` `284-294`, `_model_to_slug` `297-302`, `_parse_base_url` `305-333`, **`cmd_migrate_credentials` `336-519`** (model name derived from **`cred.base_credentials.name`** at `428` and `452` — the bug), `_rollback_migration` `522-587`, `_set_env_var` `590-606`.
- `platform/models/credential.py` — `LLMProviderCredential` `70-83`; secret is **`api_key: EncryptedString(500)` at line 78** in table **`llm_credentials`** (NOT the shared `credentials` table — the brief's "shared table" wording is imprecise; `credentials` holds only the discriminator/name).
- `platform/api/credentials.py` — multi-type router; LLM-typed logic in `_serialize_credential` `72-80`, `create_credential` `136-145`, `update_credential` `238-242`, and `test_credential` `382-455` (makes **direct provider HTTP calls with `llm.api_key`**).
- `platform/api/available_models.py` — **already reads from agentgateway filesystem** (`list_all_available_models`), returns `[]` when flag off. Pipelit#189 mostly done here.
- `platform/api/providers.py` — admin CRUD over agentgateway config.d (write_provider_key/fetch-models); **already agentgateway-native**, not credential-derived.
- `platform/config.py` — **`AGENTGATEWAY_ENABLED: bool = False` at line 140**; `AGENTGATEWAY_URL` `139`, `AGENTGATEWAY_DIR` `141`, `FIELD_ENCRYPTION_KEY` `110`.
- Extra `.api_key` readers to handle: `components/_agent_shared.py:168-172` (`_resolve_credential_field` reads `cred.llm_credential.api_key`), web-search path in `components/agent.py:85-86` and `components/deep_agent.py:124-125` (consume `resolve_credential_for_node().provider_type`).
- Alembic: single head = **`758cd1ca2aad`** (`add_backend_route_to_component_configs`). New migration's `down_revision` = `758cd1ca2aad`.
- Tests: `platform/tests/test_migrate_credentials.py` (**line 345 asserts `model_data["model"] == "OpenAI (default)"` — encodes the bug**), `test_credentials_glm.py`, `test_credentials_agentgateway.py`, `test_services_llm.py`, `test_llm_agentgateway.py`, `test_agent_web_search.py`.
- Frontend: `platform/frontend/src/features/credentials/CredentialsPage.tsx` (line ~34 already hides LLM form when agentgateway enabled), model picker with credential-fallback in `platform/frontend/src/features/workflows/components/NodeDetailsPanel.tsx`, api hooks `frontend/src/api/credentials.ts` + `frontend/src/api/available_models.ts`.

**plit** (`~/Programs/pipelit.ai/plit`, branch `feat/agentgateway-docker`):
- `docker/entrypoint.sh` (~`26-90`) starts agentgateway; current gating is **soft** (probe ~10s then continue even on failure) and keyed off `AGENTGATEWAY_DIR` presence.
- `docker/Dockerfile` — downloads agentgateway v1.0.1. **NOTE / brief correction: there is NO `ARG INCLUDE_AGENTGATEWAY` gate — the binary is downloaded unconditionally.** So "flip INCLUDE_AGENTGATEWAY default→true" is moot; the real work is making the gateway a **hard** boot dependency.
- Port `:4000` hardcoded in ~2 spots (`docker/entrypoint.sh` and a Rust init/config file) — confirm exact list during Task 2.

**Out of scope repos (do NOT touch):** `plit-gw` (master, message gateway — name-collision hazard with agentgateway), `tela`.

## Librarian finding — BAKED IN (resolves the former verify-then-fix open item)
**CONFIRMED BUG.** agentgateway v1.0.1's per-provider `model:` field is a **hard outbound override**:
if set, it unconditionally replaces the caller's requested model with that literal string before
forwarding upstream. The migration writes the credential **display name** (`cred.base_credentials.name`,
e.g. `"OpenAI (default)"`) into `model:`, so every proxied request ships `"model":"OpenAI (default)"` →
guaranteed `404 model_not_found` at the upstream provider. Fails loudly/consistently.
**Fix:** do NOT write the display name. Leave `model:` **UNSET** so the caller's real model id
(`cc.model_name`) passes through unchanged; only populate `model:` with a **real upstream model id** when
intentionally pinning a route. This is now a **definite fix task (Task 1)**, not a verification task.

## Task Dependency Graph
```
Task 1 (model-id fix + migration hardening) ─┐
Task 2 (plit hard boot dep)                  │
                                             ▼
Task 3 (update migration tests) ── Task 4 (dry-run verify migration)
                                             │
Task 1, Task 2, Task 4 ─────────────────────▼
Task 5 (flip AGENTGATEWAY_ENABLED default → True + pipelit hard boot dep)
                                             │
                                             ▼
Task 6 (remove direct-provider fallback + _fake_credential trap; both resolve paths; extra api_key readers)
                                             │
                            ┌────────────────┼────────────────┐
                            ▼                ▼                 ▼
Task 7 (remove LLM CRUD    Task 8 (alembic  Task 9 (frontend: drop LLM cred
in api/credentials.py)     drop api_key col) form + credential-fallback model picker)
                            │                │                 │
                            └────────────────┼─────────────────┘
                                             ▼
Task 10 (Final Verification Wave)
```

## Execution Waves

### Wave 1 (parallel — foundational, cross-repo)

- **Task 1 — Fix model-id handling + harden migration.** Agent: **hephaestus**
  - Objective: Stop writing display names as model ids; make multi-key collisions fail loud.
  - Files: `platform/services/agentgateway_config.py` (`add_model` `180-203`), `platform/cli/__main__.py` (`cmd_migrate_credentials` `336-519`, esp. `428`/`452`).
  - Sub-task 1a (config shape): confirm which agentgateway config shape the generator/assembled `config.yaml` actually targets. Librarian (v1.0.1 source, `crates/agentgateway/src/llm/mod.rs`) confirms the hard-override field is **`provider.<providerName>.model`** (`Provider { model: Option<Strng> }`); `override_model()` writes it verbatim into the outgoing request body with no validation. Inspect `AGENTGATEWAY_DIR/assemble-config.sh` output and a real assembled `config.yaml` to confirm the assembled key path, then fix whichever field is generated.
  - Sub-task 1b (model-id): change model-file writing so the provider `model:` override is **omitted by default** (pass-through of caller's `cc.model_name` — which `read_body_and_default_model` requires when the override is unset). Only emit a `model:` value when an explicit real upstream model id is supplied. Model **filename/slug** may still derive from the display name (routing key), but the routing-significant `provider.<x>.model` field must not carry the display name. **If a friendly client-facing label is ever wanted, express it via `policies.ai.modelAliases` (client-model → real-model rewrite), NEVER via `provider.<x>.model`** — the two are distinct mechanisms and mixing them has untested precedence at v1.0.1 (override parses before alias resolution).
  - Sub-task 1c (multi-key FAIL LOUD): in `cmd_migrate_credentials`, when >1 `LLMProviderCredential` groups to the same provider name with differing `api_key`, **abort with a non-zero exit and explicit error** naming the colliding credentials — do NOT silently keep only `first_cred` (current `390-448` behavior).
  - Dependencies: none.
  - Acceptance: migrating a credential named `"OpenAI (default)"` produces a provider/model config whose routing-significant model field is empty/pass-through (no `"OpenAI (default)"` literal anywhere in the assembled config's model field); two openai creds with different keys → migration exits non-zero with a collision error; `assemble-config.sh` still succeeds; the targeted config field verified against sub-task 1a.

- **Task 2 — Make agentgateway a hard boot dependency in plit containers.** Agent: **sisyphus-junior**
  - Objective: Gateway must be present and healthy before plit serves; container fails fast if it isn't.
  - Files: `docker/entrypoint.sh` (~`26-90`), `docker/Dockerfile`, plit docker-compose (locate it), the ~2 hardcoded `:4000` spots.
  - Steps: replace the soft "probe ~10s then continue" with a **blocking readiness gate** (poll gateway health; exit non-zero on timeout). Confirm the v1.0.1 binary is unconditionally present (no `INCLUDE_AGENTGATEWAY` ARG exists — do not invent one; if you add an opt-out, default it to ON). Ensure `AGENTGATEWAY_URL`/`AGENTGATEWAY_DIR` are exported so pipelit sees them. Leave `:4000` centralized or documented.
  - Dependencies: none. **Sequencing constraint #1: this must land before Task 5 is safe in containers.**
  - Acceptance: `docker build` succeeds; container with a reachable gateway boots; container with the gateway forced-unreachable **fails its healthcheck / exits non-zero** rather than serving keyless.

### Wave 2 (depends on Task 1)

- **Task 3 — Update migration tests to the fixed model-id contract.** Agent: **sisyphus-junior**
  - Objective: Tests must assert pass-through (no display-name model), not the old bug.
  - Files: `platform/tests/test_migrate_credentials.py` (esp. `345`, plus anthropic/glm/openai_compatible cases and any assertion of `model:` == a display name), add a collision-fails-loud test.
  - Dependencies: Task 1.
  - Acceptance: updated suite asserts routing-significant model field is empty/pass-through; a new test asserts multi-key collision → non-zero exit; `pytest platform/tests/test_migrate_credentials.py` green.

- **Task 4 — Run migration in `--dry-run` and verify (no over-engineered rollback).** Agent: **sisyphus-junior**
  - Objective: Prove the fixed migration produces a correct provider/model tree for all four provider types.
  - Files: run `python -m cli migrate-credentials --dry-run` (and `--populate-routes` dry preview) against a seeded test DB with openai/anthropic/glm/openai_compatible creds.
  - Dependencies: Task 1, Task 3.
  - Acceptance: dry-run output lists correct provider dirs, key files, model files (no display-name in the model field), correct `backend_route` mapping preview; no crash on the openai_compatible/custom-name path; keep the existing `--rollback` working (do not delete it) but do not expand it.

### Wave 3 (depends on Task 1, Task 2, Task 4)

- **Task 5 — Flip `AGENTGATEWAY_ENABLED` default → True and add pipelit hard boot dependency.** Agent: **sisyphus-junior**
  - Objective: Gateway ON by default; Pipelit refuses to start (or fails LLM resolution loudly) if the gateway is required but unreachable.
  - Files: `platform/config.py:140`; a startup hook (locate app startup, e.g. FastAPI lifespan / worker bootstrap) to assert `check_agentgateway_health` when `AGENTGATEWAY_ENABLED`.
  - Dependencies: Task 2 (containers must guarantee gateway presence), Task 4 (migration verified).
  - **Do NOT collapse Tasks 6/7/8 into this task.** This wave only flips the flag + adds the hard dep.
  - Acceptance: fresh boot with gateway up works; gateway down → explicit fatal error at startup (not a silent fall-through to the direct path, which still exists until Task 6).

### Wave 4 (depends on Task 5)

- **Task 6 — Remove the direct-provider fallback and the empty-key trap; handle both resolve paths and all extra `api_key` readers.** Agent: **hephaestus**
  - Objective: There is no code path left that reads a raw LLM `api_key`.
  - Files & specifics:
    - `platform/services/llm.py`: delete the direct-provider branch `165-216` in `create_llm_from_db` (agentgateway becomes the only path; raise clearly if disabled). Remove `_fake_credential_from_route` `87-102` **but preserve provider-type inference** — web-search detection (`agent.py:85`, `deep_agent.py:124`) relies on `resolve_credential_for_node().provider_type`; replace the fake-empty-key object with a provider-type value derived from `backend_route` (reuse `_route_provider_to_type`) carrying **no `api_key` field at all**. Apply identical treatment to **both** `resolve_llm_for_node` paths (`342-396` and `398-455`) and both branches of `resolve_credential_for_node` (`485`, `500`).
    - `platform/components/_agent_shared.py:168-172`: `_resolve_credential_field` returns `cred.llm_credential.api_key` — remove/neuter the `api_key` branch (that secret no longer exists); confirm callers (`225-226`) degrade safely.
    - **`platform/services/dsl_compiler.py:406` (`_fetch_model_ids`, reached via `_discover_model` → `_resolve_model`/`_build_step_config` from `compile_dsl`/`validate_dsl`) — FOURTH raw-key reader (momus-found): does `httpx.get(f"{base_url}/models", headers={"Authorization": f"Bearer {cred.api_key}"})`. LIVE code (imported from `api/workflows.py` and `components/workflow_create.py` for DSL model auto-selection). Replace the credential-key model fetch with agentgateway-native `list_all_available_models()` (already exists, see `api/available_models.py`). Must be handled here in Task 6 — if Task 8 drops `api_key` first, DSL compile raises at runtime.**
  - Dependencies: Task 5.
  - Acceptance: `grep -rn "\.api_key" platform --include=*.py` shows no remaining reads of an LLM credential key in product code — **including `dsl_compiler.py`** (tests updated separately); web-search provider detection still returns correct provider for a `backend_route`-only node; DSL compile/validate model auto-selection works via agentgateway; `test_services_llm.py`, `test_llm_agentgateway.py`, `test_agent_web_search.py` updated and green.

### Wave 5 (parallel — depends on Task 6)

- **Task 7 — Remove LLM-typed credential CRUD from the API.** Agent: **hephaestus**
  - Objective: The API can no longer create/update/store/test raw LLM keys; git/gateway/tool creds untouched.
  - Files: `platform/api/credentials.py` — strip the `llm` branches in `_serialize_credential` (`72-80`), `create_credential` (`136-145`), `update_credential` (`238-242`), and remove the direct-provider `test_credential` LLM logic (`382-455`) or make it reject `llm` type. Keep `git`/`gateway`/`tool` fully intact.
  - Dependencies: Task 6.
  - Acceptance: POST/PATCH of a `credential_type=llm` returns a clear rejection; git/gateway/tool CRUD unaffected; `test_credentials_glm.py` / `test_credentials_agentgateway.py` updated to reflect removal.

- **Task 8 — Alembic: drop the LLM key storage column.** Agent: **sisyphus-junior**
  - Objective: Remove the encrypted `api_key` at rest.
  - Files: new revision under `platform/alembic/versions/` with `down_revision = "758cd1ca2aad"`; edit `platform/models/credential.py` to drop the `api_key` mapped_column (line 78). Decide (document in the revision docstring): drop **only `api_key`** vs the whole `llm_credentials` sub-table. **Recommended: drop the `api_key` column** (and `organization_id`/`custom_headers` only if confirmed unused post-Task 6); keep `provider_type`/`base_url` if any remaining read needs them (audit first). Hard cutover — no data-preservation branch required.
  - Dependencies: Task 6 (no code reads `api_key`), coordinate with Task 7 (model/schema consistency).
  - Acceptance: `alembic upgrade head` clean on a fresh DB; `alembic heads` shows a single head; model imports without the dropped attribute; app boots.

- **Task 9 — Frontend: remove LLM credential form + credential-fallback model picker; agentgateway as model source of truth (Pipelit#189).** Agent: **sisyphus-junior**
  - Objective: No orphaned UI calling removed endpoints; model picker driven solely by `available_models` (agentgateway).
  - Files: `platform/frontend/src/features/credentials/CredentialsPage.tsx` (remove the LLM create/edit form path, not just the hide at ~34), `platform/frontend/src/features/workflows/components/NodeDetailsPanel.tsx` (remove the credential-derived model-picker fallback; keep the agentgateway `useAvailableModels` path), `frontend/src/api/credentials.ts` (drop llm-cred + test/models hooks), `frontend/src/api/available_models.ts`.
  - Dependencies: Task 6/7 (backend endpoints removed). Backend `available_models.py`/`providers.py` are already agentgateway-native — verify no residual credential-derived model listing remains server-side.
  - Acceptance: credentials UI shows only git/gateway/tool; node model picker populates from agentgateway; no frontend call hits a removed LLM endpoint; typecheck/lint pass.

### Final Verification Wave

- **Task 10 — Cross-provider + docker-compose integration.** Agent: **hephaestus** (with **oracle** review pass)
  - Cross-provider unit/integration: openai, anthropic, glm, openai_compatible resolve through agentgateway with the real `cc.model_name` passed through (not overridden). Run full `pytest platform/tests`.
  - **docker-compose integration (constraint #3):** bring up **pipelit + plit together**; assert gateway healthcheck passes, pipelit boots with `AGENTGATEWAY_ENABLED=true`, a workflow node resolves an LLM, mints a JWT, and reaches the gateway (health/JWT/reachability). Do NOT substitute pipelit unit tests for this.
  - Secret-removal proof: `grep -rn "\.api_key" platform --include=*.py` clean in product code; DB has no LLM `api_key` column; no raw key in pipelit `.env`/config.
  - Static sweeps: `alembic heads` single; `ruff`/type checks; frontend typecheck.
  - oracle: post-implementation read-only review of the trust-boundary claim (JWT-only egress, no key leakage).

## Deferred (document as known limitations — do NOT schedule)
- JWT issuance stays in pipelit (self-signed, "circular trust") — moves to plit-gw in **Phase 4**.
- `AGENTGATEWAY_ENCRYPTION_KEY` remains == pipelit `FIELD_ENCRYPTION_KEY` (single Fernet key) — split deferred, note the caveat in `agentgateway_config.py:_get_fernet`.
- MCP federation / CEL RBAC / adapter refactor — **Phase 2/3**; OAuth + credential-schema UX — **Phase 5**.
- Migration of `git`/`gateway`/`tool` credentials — out of scope (only `llm` discriminator migrates).
- No `plit-gw` or `tela` changes.

## Risk Flags
- **Web-search provider detection regression:** `resolve_credential_for_node` feeds `agent.py`/`deep_agent.py`; removing `_fake_credential_from_route` must preserve `provider_type` inference or native web-search silently breaks. (Task 6.)
- **Config-shape mismatch:** if Task 1a mis-identifies the generated field (`model` vs `name`/`params.model`), the model-id fix targets the wrong key and the bug persists. Verify against a real assembled `config.yaml`.
- **Hidden `api_key` reader** in `_agent_shared.py:170` — easy to miss; dropping the column before neutering it crashes credential-field injection. (Order Task 6 before Task 8.)
- **`resolve_credential_for_node` legacy branches** still query `llm_credential`; if Task 8 drops columns those relationships still load — confirm they don't dereference `api_key`.
- **Hard boot dependency deadlock:** if pipelit's startup health-check (Task 5) runs before plit's gateway is ready in compose, boot fails — ensure ordering/retry in compose (Task 2/10).
- **Test fixtures assume the bug:** beyond line 345, other assertions may encode display-name-as-model; sweep the whole migration/agentgateway test set (Task 3).
- Multi-head alembic risk is low (single head `758cd1ca2aad` confirmed) but re-verify `alembic heads` at Task 8 time in case of drift.

## QA Scenarios
- [ ] Migrating a credential named `"OpenAI (default)"` yields a route whose model field is empty/pass-through; a live openai call using `cc.model_name="gpt-4o"` returns 200 (no 404 model_not_found).
- [ ] Two openai credentials with different keys → `migrate-credentials` exits non-zero naming the collision; no key silently dropped.
- [ ] `AGENTGATEWAY_ENABLED` defaults True on a fresh checkout; pipelit refuses to boot when the gateway is unreachable.
- [ ] After Task 6, `grep -rn "\.api_key" platform --include=*.py` shows no LLM-key reads in product code; native web search still detects the right provider for a `backend_route`-only node.
- [ ] After Task 8, the DB has no LLM `api_key` column; `alembic upgrade head` and `alembic heads` (single) are clean.
- [ ] Credentials UI exposes only git/gateway/tool; the workflow model picker lists agentgateway models; no frontend request hits a removed LLM endpoint.
- [ ] docker-compose (pipelit + plit): gateway healthy → workflow node mints a JWT and reaches the gateway; gateway down → containers fail fast.
- [ ] All four provider types (openai/anthropic/glm/openai_compatible) pass through agentgateway end-to-end.
```
