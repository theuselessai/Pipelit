# Plan: Two static binary node types — `binary_op` and `binary_auth`

**Status:** ready for execution
**Branch:** feat/binary-node-catalog (stage 4)
**Baseline:** commit 4dd15d5, full suite 2191 passing (~3.5 min), frontend builds clean, NodeDetailsPanel carries a baseline of 8 lint problems (5 errors) that must not change.

## Context

Today every (binary, domain) pair and every binary's auth surface becomes its own
SQLAlchemy polymorphic identity, synthesised at import from catalog files. This plan
replaces all of that with two static component types registered directly in
`models/node.py`, with the binary moved into node data (`extra_config["binary"]`) and
ports derived per node from (registered catalog, configured operation). It fixes four
defects at once: (a) the restart-on-registration trap, (b) union ports, (c) the
String(30) overflow skip, (d) design-time validation that cannot see the operation's
real ports.

Decisions already made — do not re-open during execution:

1. Two static types: `binary_op` (catalog operations), `binary_auth` (protocol verbs).
   The verb table's shape (`binary_verbs.py` globals/credential/picker) is NOT reshaped.
2. Ports are DERIVED, never snapshotted. No `declared_ports` column, no `catalog_hash`
   on nodes. The pin is the binary: `verified_plugin()` (services/plugins.py:183-215)
   refuses at call time when the tree no longer hashes to what passed conformance, and
   the catalog file only changes on deliberate re-registration. Drift protection lives
   at the registration boundary (see Task 4a), not on nodes.
3. `EdgeValidator.validate_edge` changes signature to take node objects. Both
   production callers (api/workflows.py:113-115, api/nodes.py:466-471) already hold ORM
   `WorkflowNode` objects.
4. **Palette keeps today's UX.** One sidebar entry per (binary, domain) under a
   per-binary heading — exactly the shape that ships now — plus one identity entry
   per binary. NO three-level operation listing in the sidebar (6 entries for
   acme-portal-admin, not 23; acme-portal and acme-integral are still coming). Clicking
   creates a `binary_op` node with `extra_config: {binary, domain}` and NO operation
   preselected — 14 of acme-portal-admin's 15 operations write real customer state, so
   a silently-defaulted operation is a loaded gun. The operation dropdown stays in
   the right panel (NodeDetailsPanel / SchemaConfigForm), filtered to the node's
   domain. The catalog endpoint already carries per-operation `domain`; no backend
   change follows from this.
5. **Defect (d) closes at VALIDATE time, not at CREATE time.** With no palette
   pre-configuration, every freshly-added binary node starts without an operation,
   so refusing its edges at creation would break the normal sketch-first path, not
   an edge case. `POST /edges/` ALLOWS an edge touching a binary node whose ports
   cannot be resolved; `POST /validate/` REPORTS it with the specific reason. The
   condition must never be invisible from both paths. Type mismatches on
   RESOLVABLE binary nodes still 422 at creation, exactly as today. The
   `verified_plugin` allowlist on `extra_config["binary"]` stays at create/update —
   that is a security control, not a port check.

## Hard constraints (repeat before every task)

- `resolve_expressions` (services/expressions.py:44-46) returns the ORIGINAL template
  string on failure — a vanished port travels downstream as the literal
  `"{{ node.port }}"`. No task may make a port silently vanish for a saved node.
- The `get_node_type() is None → []` forward-compat leniency in
  validation/edges.py:51-53 must NOT silently swallow an unresolvable-ports condition
  on a `binary_op`/`binary_auth` node. The condition is detected as a distinct,
  identifiable error class: filtered out (allowed) at edge creation, reported with
  its specific reason at `/validate/` — allowed at create, reported at validate,
  never absent from BOTH paths.
- `NodeOut.component_type` stays unvalidated; a node stays readable regardless of
  catalog presence.
- Flow-control bypasses survive unchanged: `loop_body`/`loop_return` skip validation
  (validation/edges.py:120-121 AND api/nodes.py:462); sub-component handles
  `model`/`tools`/`output_parser`/`skills` return early (validation/edges.py:57-69).
- `extra_config["binary"]` is agent-writable node data. It MUST be re-validated
  against the server-side allowlist (`verified_plugin` / `services.plugins`) on every
  node create/update. A path must never be storable (`_safe_name` refuses separators).
- `component_type` stays String(30) on both columns. Values change; schema does not.
  No `batch_alter_table` anywhere.
- Migration lands in the SAME commit as the Wave 1 code change, or old rows carry a
  discriminator with no mapped class.
- Migration WHERE clause enumerates known old values by equality. Never pattern-match
  "looks derived" — the naming rule strips hyphens and is lossy.
- `mailbox_action` is a built-in on the schema-driven form, NOT a derived type. Never
  migrate or touch it.
- tests/test_edge_validation.py:13-55 (`TestTypeCompatibility`, 15 assertions) stays
  BYTE-IDENTICAL. It is the only untouched evidence that compatibility semantics did
  not drift while ~10 other tests are rewritten.
- No frontend test runner exists. Frontend verification = tsc + eslint + build +
  manual walkthrough.
- Check exit codes without a pipe (zsh): `cmd > /tmp/log 2>&1; echo $?; tail /tmp/log`.
- **No past state of this feature is reconstructible from git alone.** The catalogs,
  plugins and registration records are untracked (.gitignore:55 `platform/catalogs/*.json`,
  :59 `platform/plugins/*/`, :60 `platform/catalogs/registrations/`;
  `git ls-files platform/catalogs platform/plugins` returns only the README). A
  checkout or worktree of any past commit therefore has NO catalogs: old code there
  registers zero derived types and produces clean-looking but meaningless results.
  Anything needing a before/after comparison must be captured LIVE, on the current
  checkout, before the change — hence the Wave 0 baseline below.

## Target architecture (what "done" looks like)

- `schemas/binary_catalogs.py` becomes a catalog ACCESS layer: read a binary's pinned
  catalog file on demand (mtime-cached), expose per-binary operation specs and typed
  output ports. No import-time registration, no dynamic classes, no
  `component_type_for`, no MAX_COMPONENT_TYPE skip (nothing derives names any more).
- `schemas/binary_verbs.py` keeps VERBS and `build_argv` unchanged; `auth_spec_for(binary)`
  becomes `auth_spec()` building the single static `binary_auth` NodeTypeSpec
  (x-operations from VERBS, VERB_MARKER, no `x-binary` — the binary is node data now).
- `schemas/node_type_defs.py` registers `binary_op` and `binary_auth` statically and
  loses its `load_specs()` call (lines 713-715).
- `models/node.py` gains `_BinaryOpConfig` / `_BinaryAuthConfig` static identities and
  loses the dynamic block at lines 397-408. That deletion is the proof goal (a) landed.
- `components/binary_op.py` / `binary_auth.py` register via `@register("binary_op")` /
  `@register("binary_auth")`; binary comes from `extra_config["binary"]`; the
  None-filled port dict is built from the CONFIGURED OPERATION's declared outputs
  (binary_op: catalog; binary_auth: `VERBS[verb]["outputs"]`) — the "unemitted ports
  are null, never absent" behaviour survives, scoped to the operation.
- `validation/edges.py` resolves ports per node; unresolvable binary-node ports are a
  distinctly identifiable error — never the silent `[]` — that edge creation permits
  and `/validate/` reports.
- New API surface: `GET /api/v1/plugins/catalog/` serving each registered binary's
  legacy-shaped config schema (operation enum + x-operations sidecar + per-op domain)
  read from the pinned catalog file.
- Frontend: palette keeps its current shape — one entry per (binary, domain) plus an
  identity entry per binary — creating `binary_op` nodes with `{binary, domain}` and
  no operation; the panel's operation dropdown filters to the domain; config panel /
  variable picker / canvas resolve the effective operation schema per node instead of
  per type; a binary node with no operation is visibly marked on the canvas.

## Task Dependency Graph

```
T0 (baseline capture — strictly before T1's first edit)
T0 → T1 (backend core swap + migration)
T1 → T2a (EdgeValidator + node-create allowlist + planted violation #1)
T1 → T2b (catalog API endpoint)
T2a → T3  (frontend)          T2a → T4a (drift guard + restart demo)
T2b → T3                      T2b → T4a
T3 → T5   (final verification) ← T4a   (T5 step 2 also consumes T0's baseline file)
```

## Execution Waves

### Wave 0 — baseline capture, BEFORE Task 1's first edit

**Task 0: Capture the current validation baseline** — Agent: **sisyphus-junior**
(trivial, but strictly first)

Against the CURRENT code and CURRENT dev DB, run
`POST /workflows/{slug}/validate/` for every existing workflow and save the raw
JSON responses outside the repo, e.g. `/tmp/validate_before.json` (one object keyed
by slug). Also record `GET /workflows/{slug}/edges/` per workflow beside it, so a
later diff can name edges, not just count errors.

This MUST happen before Wave 1 Task 1 modifies anything: the catalogs, plugins and
registrations are untracked (see hard constraints), so once the derivation code is
gone the old behaviour cannot be reconstructed from git — the "before" side of the
Wave 4 ANY-widening diff exists only if it is captured now.

Verification: the file exists, is valid JSON, and covers every workflow in the DB
(`python3 -c "import json; d=json.load(open('/tmp/validate_before.json')); print(sorted(d))"`).

### Wave 1 — one atomic commit (code + migration together)

**Task 1: Static types replace dynamic derivation** — Agent: **hephaestus**

Files: `schemas/binary_catalogs.py`, `schemas/binary_verbs.py`,
`schemas/node_type_defs.py` (713-715), `schemas/node.py` (STATIC_COMPONENT_TYPES),
`models/node.py` (COMPONENT_TYPE_TO_CONFIG, static config classes, delete 397-408),
`components/binary_op.py`, `components/binary_auth.py`, `components/__init__.py`
(delete the re-derive miss path in `get_component_factory`), new alembic revision,
tests: `tests/test_binary_catalogs.py`, `tests/test_binary_verbs.py`,
`tests/test_binary_plugins.py`. Also confirm `scripts/register_plugin.py` still works
(it imports `CATALOG_DIR` only).

1. **Catalog access layer** (`schemas/binary_catalogs.py`). Keep `_read_catalog` and
   `_TYPE_MAP`. Delete `component_type_for`, `_ports_for` (union), `_spec_for`,
   `load_specs`, `register_config_classes`, `_derived_component_types`,
   `MAX_COMPONENT_TYPE`. Add, all reading `CATALOG_DIR/<binary>.json` (confirm the
   filename convention against what `scripts/register_plugin.py` writes) with a
   per-file mtime cache so a newly registered catalog is visible to a running process
   on its next call:
   - `catalog_for(binary) -> dict | None`
   - `operations_for(binary) -> dict[op_id, entry] | None` — entries shaped like
     today's `x-operations` values (summary, params, session_required,
     timeout_default_s, outputs as names) PLUS `"domain"`.
   - `operation_output_ports(binary, operation) -> list[PortDefinition] | None` —
     typed via `_TYPE_MAP`; `None` when binary/catalog/operation is unresolvable.
   - `config_schema_for(binary) -> dict | None` — legacy-shaped schema covering ALL
     of the binary's operations: `properties.operation.enum` (sorted ids), `session`,
     `env` properties, `required: ["operation"]`, `x-binary`, `x-operations`
     (with per-op `domain`). This is what the Wave 2b endpoint and the frontend form
     consume; keeping the shape means `SchemaConfigForm` barely changes.
   Reserve the config keys `binary`, `domain`, `operation`, `session`, `env`:
   log-and-skip any catalog parameter that collides.
2. **Verbs** (`schemas/binary_verbs.py`): delete `component_type_for`; rename
   `auth_spec_for(binary)` → `auth_spec()` producing component_type `"binary_auth"`,
   keeping `x-operations` (VERBS are static) and `VERB_MARKER`, dropping `x-binary`.
   Add a `binary` property (title "Binary") to its config_schema.
3. **Static registration**: in `schemas/node_type_defs.py` remove the
   `load_specs` import/call; register `auth_spec()` and a new `binary_op` spec:
   category "action", display "Binary Operation", inputs `[input: ANY, optional]`,
   `outputs: []` (ports are per-node), config_schema with `binary` and `operation`
   string properties, `required: ["binary", "operation"]`, and NO `x-operations`
   (they are per-binary; the frontend fetches them from the catalog endpoint).
4. **Models** (`models/node.py`): add `_BinaryOpConfig` / `_BinaryAuthConfig`
   (polymorphic identities `binary_op` / `binary_auth`, plain `BaseComponentConfig`
   subclasses like `_MailboxActionConfig`), add both to `COMPONENT_TYPE_TO_CONFIG`,
   DELETE lines 397-408 (the `_load_binary_specs()` /
   `_register_binary_config_classes` block). Do not add them to
   `CREDENTIALED_NODE_TYPES` — these nodes carry no platform credential by design.
5. **Pydantic** (`schemas/node.py`): add `"binary_op"`, `"binary_auth"` to
   `STATIC_COMPONENT_TYPES`.
6. **Components**: rework `components/binary_op.py` to `@register("binary_op")`;
   read `binary = extra_config["binary"]` (missing → `_error("NO_BINARY", …)`);
   resolve the operation through the catalog layer (`UNKNOWN_OPERATION` /
   `UNKNOWN_BINARY` errors); build the None-filled port dict from
   `operation_output_ports(binary, operation)` — this keeps the load-bearing
   "null, never absent" rule, now scoped to the configured operation.
   Rework `components/binary_auth.py` to `@register("binary_auth")`; binary from
   extra_config; port fill from `VERBS[verb_id]["outputs"]`. Delete
   `register_derived_types` / `register_verb_types` and their call sites, including
   the miss-path re-derivation in `components/__init__.py:get_component_factory`.
7. **Migration** (same commit). First `alembic heads` — expect the single head
   `3870bee8886b`; stop and report if not. New revision, no batch mode, following the
   read/rewrite/delete loop precedent of
   `alembic/versions/b2c3d4e5f6a7_add_switch_node_condition_value.py:16-64`:
   - Build the old→new mapping at migration runtime from THIS machine's registration
     records (`catalogs/registrations/*.plugin.json`) and catalog files: for each
     registered binary `B`, old auth type = `f"{B}_auth".replace("-", "_")` →
     (`binary_auth`, B); for each domain in B's catalog, old op type =
     `f"{B}_{domain}".replace("-", "_")` → (`binary_op`, B), skipping any name over
     30 chars (those never registered) and any name colliding with
     `STATIC_COMPONENT_TYPES` (never touch `mailbox_action` or any built-in).
   - `UPDATE` both `workflow_nodes.component_type` and (joined via
     `component_config_id`) `component_configs.component_type`
     `WHERE component_type IN (<enumerated list>)` — equality only. For each matched
     config row, read `extra_config` JSON, set `"binary": B` (and for op-type rows
     also `"domain": D` — the enumeration already knows it per old name, and it makes
     migrated nodes identical in shape to palette-created ones), write back.
   - Afterwards, SELECT distinct component_type values that are neither static nor
     `binary_op`/`binary_auth` and print a loud warning for each — rows left
     untouched are exactly as unloadable as they are today, no worse.
   - `downgrade()`: reverse using `extra_config["binary"]`; auth →
     `{binary}_auth` flattened; op → old name needs the domain, resolved by looking
     the configured operation up in the binary's catalog; if the catalog is absent,
     leave the row and warn. Remove the `"binary"` and `"domain"` keys it added.
8. **Tests**: rewrite `test_binary_catalogs.py` around the access layer (keep the
   spirit of: protocol != 1 refuses the WHOLE catalog; malformed file skips itself
   only; absent dir yields nothing; port type conflict — now a non-issue since ports
   are per-operation, drop the widen-to-ANY test with the union code). Delete the
   String(30) overflow test with the machinery it pinned. Rewrite
   `test_binary_verbs.py` (`auth_spec`, no `component_type_for`) and
   `test_binary_plugins.py` (fixtures now create `binary_op` nodes with
   `extra_config={"binary": "demo-bin", "operation": ...}`).

Verification (all must pass before the wave closes):
```
cd platform && source ../.venv/bin/activate
export FIELD_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python3 -m pytest tests/ -q > /tmp/w1.log 2>&1; echo $?; tail -5 /tmp/w1.log
grep -rn "register_config_classes\|register_derived_types\|register_verb_types\|_derived_component_types" --include="*.py" . | grep -v alembic/versions   # must print nothing
python3 -c "import models.node; import components; print('import ok')"
alembic heads   # exactly one head, the new revision
```

### Wave 2 — parallel (both depend on Wave 1 only)

**Task 2a: Per-node edge validation and the node-create allowlist** — Agent: **hephaestus**

Files: `validation/edges.py`, `validation/__init__.py` (re-export unchanged),
`api/nodes.py` (edge caller 466-473 AND create_node/update_node), `api/workflows.py`
(113-115 caller passes through unchanged shape), tests:
`tests/test_edge_validation.py`, `tests/test_coverage_gaps.py`,
`tests/test_skill_node.py`, `tests/test_orchestrator_e2e.py` (16 direct
`validate_edge(` call sites across the four).

1. Change `EdgeValidator.validate_edge(source_node, target_node, source_handle=None,
   target_handle=None)` to take node objects (needs `.component_type` and
   `.component_config.extra_config`; tests may pass stubs). Internal
   `_output_ports(node)`: `binary_op` → `operation_output_ports(binary, operation)`
   (operation from extra_config or the schema-declared default); `binary_auth` →
   the configured verb's `VERBS[...]["outputs"]`; everything else →
   `get_node_type(component_type).outputs`.
2. Close the leniency hole EXPLICITLY, at validate time: unknown component_type
   still returns `[]` (forward compat, preserved), but a `binary_op`/`binary_auth`
   node whose ports cannot be resolved — no binary set, binary not registered,
   catalog absent, operation unset or unknown — is detected and returned as a
   DISTINCTLY IDENTIFIABLE error (its own class or code, e.g. an
   `unresolved_ports`-tagged entry) saying which of those failures it is. The two
   callers then diverge deliberately:
   - `POST /workflows/{slug}/edges/` (api/nodes.py) FILTERS that class out and
     creates the edge — sketch-first keeps working. It must NOT do this by
     skipping validation wholesale: type mismatches on RESOLVABLE binary nodes
     still 422 at creation, exactly as today.
   - `POST /workflows/{slug}/validate/` (api/workflows.py) KEEPS it, with the
     specific reason.
   Allowed at create, reported at validate — the condition is never invisible
   from both paths. Preserve untouched: conditional-edge rules, loop bypasses,
   sub-component handle early return, `validate_required_inputs` outward
   behaviour.
3. `_binary_operation_errors`: resolve the operations table per node — built-ins
   with `x-operations` in their spec (mailbox_action) unchanged; `binary_op` via
   `operations_for(extra_config["binary"])`; `binary_auth` via VERBS. A binary node
   whose table cannot be resolved gets an explicit error, not a silent skip.
4. Allowlist on write (api/nodes.py create_node AND update_node): when
   component_type is `binary_op`/`binary_auth` and the payload sets or changes
   `extra_config["binary"]`, resolve it through `services.plugins.verified_plugin`;
   `PluginError` → 422. This is what keeps "the binary path is never node data"
   true now that agents can write the field. Reads (`NodeOut`) stay unvalidated.
5. Tests: rewrite the ~10 direct `validate_edge` unit tests to node stubs; update
   the other call sites. **Planted violation #1** (prove the guard bites, in the
   two-path shape): for three `binary_op` nodes — one with NO operation, one with
   an UNKNOWN operation, one with an UNREGISTERED binary — prove all of:
   (i) an edge from each is ACCEPTED at `POST /edges/` (201);
   (ii) `POST /workflows/{slug}/validate/` REPORTS each one, with the specific
   reason (which of the failure classes it is);
   (iii) the condition is never absent from both paths — assert deliberately that
   the /validate/ report is present for exactly the edges creation permitted, so
   a regression that silently swallows the condition in both places fails the test.
   Separately, the allowlist assertions stay: node create/update with
   `binary: "../../usr/bin"` → 422; unknown binary → 422; registered fake binary → 201.

Task-level check, run before finishing:
```
diff <(git show 4dd15d5:platform/tests/test_edge_validation.py | sed -n '13,55p') \
     <(sed -n '13,55p' tests/test_edge_validation.py)   # must be empty — TestTypeCompatibility byte-identical
python3 -m pytest tests/test_edge_validation.py tests/test_coverage_gaps.py tests/test_skill_node.py tests/test_orchestrator_e2e.py -q > /tmp/w2a.log 2>&1; echo $?; tail -3 /tmp/w2a.log
```

**Task 2b: Catalog endpoint** — Agent: **sisyphus-junior**

Files: `api/plugins.py`, new tests (extend `tests/test_binary_plugins.py` or a new
API test module).

`GET /api/v1/plugins/catalog/` (Bearer-authenticated like the rest of the router):
for every REGISTERED binary, return
`{"items": [{"binary", "plugin", "schema": config_schema_for(binary)}], "total": N}`.
Read from the pinned catalog files via the Wave 1 access layer — NEVER by running the
binary (design decision: the catalog file is the pin). Unregistered plugin
directories are absent. A registered binary whose catalog file is unreadable appears
with `"schema": null` rather than failing the whole listing. Tests: registered fake
plugin appears with operation enum + domains; unregistered absent; auth required.

Verification: `python3 -m pytest tests/test_binary_plugins.py -q > /tmp/w2b.log 2>&1; echo $?`

### Wave 3 — parallel (T3 needs 2a+2b; T4a needs 2a+2b, not T3)

**Task 3: Frontend — palette, panel, picker, canvas** — Agent: **hephaestus**

Files: `frontend/src/api/plugins.ts`, `frontend/src/types/models.ts`,
`frontend/src/lib/operationSchema.ts`, `frontend/src/components/SchemaConfigForm.tsx`,
`frontend/src/components/VariablePicker.tsx` (53-55),
`frontend/src/features/workflows/components/NodePalette.tsx` (91-165),
`frontend/src/features/workflows/components/NodeDetailsPanel.tsx` (266, 1467-1475),
`frontend/src/features/workflows/components/WorkflowCanvas.tsx` (457),
`frontend/src/api/nodes.ts` + `schemas/node.py` NodeIn only if node creation cannot
already carry config (check first).

1. `useBinaryCatalogs()` hook for `GET /plugins/catalog/`.
2. `types/models.ts`: add `"binary_op" | "binary_auth"` to `BuiltinComponentType`.
3. `lib/operationSchema.ts`: add an effective-schema resolver
   `operationSchemaForNode(componentType, extraConfig, spec, catalogs)`:
   spec.config_schema when it carries `x-operations` (mailbox_action; binary_auth —
   spread in `"x-binary": extraConfig.binary` so the session/environment pickers in
   `SchemaConfigForm` keep working); the catalog entry's schema for `binary_op`
   keyed by `extraConfig.binary`; else null. Route `emittedPortNames` and the
   VariablePicker/WorkflowCanvas call sites through it. A `binary_op` node with no
   binary or no recognised operation offers NO ports to the picker — edges to it
   are permitted (decision B), but there is nothing truthful to offer until the
   operation is chosen.
4. `NodePalette.tsx`: keep TODAY'S sidebar shape — one entry per (binary, domain)
   grouped under a per-binary heading (6 entries for acme-portal-admin), plus one
   "identity" entry per binary. The (binary, domain) pairs come from
   `useBinaryCatalogs()` (each operation carries `domain`), replacing the
   registry-derived `derivedGroups` whose `x-binary` source is gone. Clicking
   creates `component_type: "binary_op"` with `extra_config: {binary, domain}` —
   NO operation preselected, ever (14 of admin's 15 operations write real customer
   state; a defaulted operation is a loaded gun). Identity entries create
   `binary_auth` + `{binary}`. Satisfy the exhaustiveness check honestly: either
   give the two types a category home or exclude them explicitly in the `Exclude<>`
   expression with a comment that they are reachable through the plugin groups.
   Add the two `ICONS` entries the compiler will demand.
5. `NodeDetailsPanel.tsx` / `SchemaConfigForm.tsx`: the operation dropdown STAYS in
   this right panel — current UX, unmoved. `binary_op` nodes get their schema from
   `useBinaryCatalogs()` by `extra_config.binary`, with the operation enum FILTERED
   to the node's `extra_config.domain` (fall back: if `domain` is absent — e.g. a
   node created raw through the API — derive it from the configured operation's
   catalog entry, else show all operations). Add a Binary select (registered
   plugins from `GET /plugins/`) for binary nodes missing one. Make the required,
   unset operation OBVIOUS in the panel (the field is already `required` in the
   schema; ensure the rendering says so rather than presenting an innocent empty
   select). Do NOT touch anything else in this file: 8 lint problems is the
   baseline, exactly.
6. `WorkflowCanvas.tsx:457`: operation label and `narrowOutput`/`emittedPortNames`
   go through the resolver. AND: a `binary_op`/`binary_auth` node with no operation
   set must be VISIBLY MARKED on the canvas — reuse the existing node badge/status
   affordance rather than inventing a new one. This is what makes decision B safe
   rather than merely permissive: edges to unconfigured nodes are allowed, so the
   unconfigured state cannot be invisible.

Verification:
```
cd platform/frontend
npm run build > /tmp/fe.log 2>&1; echo $?; tail -5 /tmp/fe.log
npx eslint src/features/workflows/components/NodeDetailsPanel.tsx > /tmp/lint.log 2>&1; grep -c "problem" /tmp/lint.log   # baseline: 8 problems, 5 errors — no more, no fewer
```

**Task 4a: Drift guard at the registration boundary + planted violation #2 + restart-trap demonstration** — Agent: **sisyphus-junior**

Files: `scripts/register_plugin.py` (or a helper in `services/plugins.py` it calls),
new tests (extend `tests/test_binary_plugins.py` / new module).

1. **Drift guard**: at re-registration, when the new catalog differs from the pinned
   one, report every saved `binary_op` node whose configured operation vanished or
   whose operation lost declared output ports (workflow slug, node_id, what
   changed). This is where decision 2 says drift protection belongs. Report loudly;
   do not block (re-registration is already a deliberate act).
2. **Planted violation #2** (catalog change semantics for a saved node): fixture
   catalog v1 declares op X with outputs `[a, b]`; save a `binary_op` node on X.
   Prove: (i) execution fills `b: None` when the binary's envelope omits it — the
   null-never-absent rule, so `{{ node.b }}` downstream resolves to null, never the
   literal template; (ii) overwrite the catalog so X's outputs become `[a]` — the
   drift guard names the node and the lost port; (iii) overwrite so X is gone
   entirely — `POST /workflows/{slug}/validate/` fails the node ("names operation
   … which this node type does not offer" path, now per-node; edge creation still
   permits per decision B, so the validate report is the guard that must bite).
   A port cannot vanish silently anywhere in that sequence.
3. **Restart-trap demonstration** (the headline claim needs a demonstration): one
   test, single process. Start the app (TestClient) with an empty catalog dir; then
   write a fake plugin dir + registration record + catalog file (reuse the
   test_binary_plugins.py fixtures) WITHOUT reimporting anything; assert in the
   same process: `GET /plugins/catalog/` lists it; `POST` a `binary_op` node naming
   it passes the allowlist; the saved node's `component_config` row loads back
   through SQLAlchemy (static identity — the "No such polymorphic_identity" failure
   is impossible by construction); `/validate/` resolves its ports; executing the
   node through the component returns the envelope's data on the operation's ports.

Verification: `python3 -m pytest tests/test_binary_plugins.py tests/test_binary_catalogs.py -q > /tmp/w4a.log 2>&1; echo $?`

### Wave 4 — Final verification

**Task 5: Migration rehearsal, full suite, walkthrough** — Agent: **sisyphus-junior**
(atlas verifies)

1. **Migration rehearsal against real data** (house rule: never only empty DBs).
   Locate the sqlite file from `config.py`'s DATABASE_URL; copy it to the scratchpad;
   run `alembic upgrade head` against the COPY via a DATABASE_URL override
   (`cmd > /tmp/mig.log 2>&1; echo $?`). Then, against the copy, assert with a short
   python snippet: the one former `acme_portal_admin_auth` node now loads as
   `binary_auth` with `extra_config["binary"] == "acme-portal-admin"` (both
   `workflow_nodes` and `component_configs` rows updated); the 2 `mailbox_action`
   nodes and 1 `trigger_manual` node are byte-untouched; 3 edges intact; the
   workflow serialises through `serialize_node`. Then `alembic downgrade -1` on the
   copy and confirm the reverse mapping restores the old name. Never touch the live
   dev DB.
2. **ANY-widening regression check.** The deleted `_ports_for()` widened
   conflicting port types to `DataType.ANY`, and ANY is compatible with everything
   in both directions — so per-operation resolution gives ports concrete types, and
   an edge that previously passed ONLY because its type had been widened can now
   legitimately fail. The "before" side is the Wave 0 baseline
   (`/tmp/validate_before.json`), captured live before Task 1's first edit — it
   CANNOT be produced now: the catalogs are untracked, so a worktree of any old
   commit registers zero derived types and validates clean for the wrong reason.
   Re-run `POST /workflows/{slug}/validate/` for the same workflows on the new
   code + migrated DB, diff against the baseline, and report any edge that newly
   fails. Expected locally: 1 workflow, 3 edges — cheap. A new failure is a
   FINDING to report, not necessarily a defect: those edges were never type-safe.
   (The migration rehearsal in step 1 keeps its own DB copy; this check needs no
   copy and no worktree.)
3. Full suite + frontend build:
```
cd platform && source ../.venv/bin/activate
export FIELD_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python3 -m pytest tests/ -q > /tmp/final.log 2>&1; echo $?; tail -5 /tmp/final.log   # ≥ 2191 passing, plus the new tests
cd frontend && npm run build > /tmp/febuild.log 2>&1; echo $?
```
4. Absence proofs (goal (a) landed by deletion, not dormancy):
```
grep -rn "register_config_classes\|register_derived_types\|register_verb_types\|load_specs\|component_type_for" --include="*.py" platform/ | grep -v alembic/versions | grep -v tests/
# must print nothing (tests may keep the names only in comments explaining history)
```
5. Manual walkthrough (honcho running, fake or real plugin registered):
   - [ ] Palette shows one entry per (binary, domain) under a per-binary heading,
         plus a per-binary identity entry — today's shape, not an operation list
   - [ ] Adding an entry creates a node with binary + domain and NO operation; the
         node is visibly marked unconfigured on the canvas
   - [ ] Config panel's operation dropdown is filtered to the node's domain;
         choosing an operation renders its params; session/env pickers populate
   - [ ] Variable picker offers only the configured operation's ports
   - [ ] Output popover after a run shows only the operation's ports
   - [ ] Edge from a binary node with no operation → ALLOWED at creation; the
         workflow's Validate reports it with the reason; the node stays visibly marked
   - [ ] Register a NEW plugin while honcho stays up: palette offers it, a node of it
         saves, validates and executes — server, scheduler and workers all untouched

## Migration rollback note

Upgrade is a value rewrite on two columns plus one JSON key added — no DDL, so
rollback is `alembic downgrade -1`, which reverses using `extra_config["binary"]` and
the machine's catalogs (operation → domain). Two caveats to record in the revision's
docstring: (1) downgrade needs the same registrations/catalogs present that upgrade
used — on a machine without them, affected rows are left as `binary_op`/`binary_auth`
with a warning (they are then unloadable under the OLD code, which is the pre-existing
absent-catalog failure, not a new one); (2) a DB restored from another machine may
hold derived names the enumeration cannot claim — upgrade leaves them untouched and
warns; they were already unloadable without their catalog. Take a file copy of the
sqlite DB before upgrading in any environment that matters.

## Risk flags

- **Edges do not carry port names** (`WorkflowEdge` has no handle/port column), so
  defect (d) manifests through the first-output type check and `{{ }}` expressions,
  not through a per-port edge field. The new signature validates against the
  operation's REAL port list; if a source-handle field is ever added, per-port
  checks slot into the node-object signature without another migration.
- **Validate-time trade-off, deliberate**: an edge touching an unresolvable binary
  node is permitted at creation so sketch-first keeps working, and is reported by
  `/validate/` with the specific reason. The safety of this rests on two legs that
  MUST both land: the distinct error class is filtered only at the edge-creation
  caller (never inside the validator), and the unconfigured state is visibly
  marked on the canvas (Task 3 step 6). If either leg slips, the condition becomes
  invisible — the exact defect this plan closes.
- **Concrete port types can newly fail legacy edges**: removing the ANY-widening
  means an edge that only ever passed because of widening can legitimately fail
  validation after migration. Task 5 step 2 diffs before/after `/validate/` output
  and reports findings; do not "fix" such an edge silently — it was never type-safe.
- **`extra_config["binary"]` key collision**: a catalog could declare a parameter
  named `binary`. The access layer reserves `binary`/`operation`/`session`/`env` and
  skips colliding params with a logged error.
- **binary_auth pickers** depend on the node's `binary` being set before
  sessions/environments can populate — a hand-created node shows the Binary select
  first; that is the intended flow, not a bug.
- **Migration is machine-relative**: the enumeration comes from this machine's
  registrations. Verified dev DB surface: exactly one derived-type node
  (`acme_portal_admin_auth`), 2 `mailbox_action`, 1 `trigger_manual`, 3 edges, single
  alembic head `3870bee8886b`.
- **Per-file mtime caching** is process-local; the 4 workers + scheduler + server
  each read the catalog file themselves, so no cross-process invalidation is needed
  — which is precisely why registration no longer requires restarts.

## QA scenarios

- [ ] Planted violation #1: edges from binary nodes with no / unknown operation or
      unregistered binary are ACCEPTED at POST /edges/ AND each is REPORTED by
      /validate/ with its specific reason — proven never absent from both paths
      (Task 2a); allowlist still 422s path-separator and unregistered binaries at
      node create/update
- [ ] Planted violation #2: catalog output change is loud at the registration
      boundary and at `/validate/`; a saved node's unemitted port resolves to null,
      never the literal `{{ node.port }}` (Task 4a)
- [ ] Restart trap: plugin registered into a running process is fully usable —
      palette, save, load, validate, execute — with zero restarts (Task 4a + walkthrough)
- [ ] `TestTypeCompatibility` byte-identical to commit 4dd15d5 (Task 2a diff check)
- [ ] Unconfigured binary node is visibly marked on the canvas and the panel makes
      the required operation obvious (Task 3)
- [ ] Wave 0 baseline captured BEFORE any edit (/tmp/validate_before.json, every
      workflow) — the untracked catalogs make it unreproducible afterwards
- [ ] ANY-widening diff: post-migration /validate/ output compared against the
      Wave 0 baseline; newly-failing edges reported as findings (Task 5 step 2)
- [ ] Dev DB migrates and downgrades cleanly on a copy; mailbox/trigger rows untouched
- [ ] `component_type` columns still String(30); no batch_alter_table in the new revision
- [ ] NodeDetailsPanel lint baseline unchanged at 8 problems / 5 errors

## Optional add-on (NOT critical path)

While NodeDetailsPanel is open in Task 3: render the authority level for binary nodes
(design doc §Names — `acme-portal` vs `acme-portal-admin` differ by a suffix and by
authority; the name must not be the only carrier of the meaning). Cheap now because
the panel already shows a Binary field; requires only a label derived from the
catalog/registration. If it threatens the lint baseline or the schedule, drop it
without discussion — it has its own line in the design doc and can land separately.

## Explicitly out of scope

BinaryPlugin DB table, registration-as-endpoint, upgrade-as-a-diff, uninstall policy,
sandboxed install, the real conformance kit, per-plugin store isolation, the Redis
single-flight lock. No task above depends on any of them.
