# Plan: Mailbox nodes — temp-mail driver as Pipelit actions

**Status:** in progress
**Branch:** `feat/mailbox-nodes`

## Why

Automations against the Gen2 stack begin with registration, and registration
needs a disposable mailbox: create an address, wait for the verification email,
read the token out of it. That capability exists today as TypeScript in
`test-hub/src/drivers/mail` (~746 lines incl. tests), and test-hub is being
abandoned. This ports it to Python and exposes it as workflow actions.

The driver's own framing is worth keeping: **use this for transitions, never for
assertions.** It moves an account into a state; what the product then does is
asserted elsewhere, against the product's own API.

## The service

A self-hosted [`cloudflare_temp_email`](https://github.com/dreamhunter2333/cloudflare_temp_email)
instance. Two authentication surfaces, and the difference matters:

| surface | credential | reach |
|---|---|---|
| `/admin/*` | `x-admin-auth` header, static shared secret | **every mailbox on the instance** — list, read, delete |
| `/api/*` | per-mailbox JWT from `POST /admin/new_address` | that one mailbox only |

Verified live 2026-08-16: mailbox A's JWT reads its own `/api/mails` and
`/api/settings` (200) and is refused (401) on `/admin/mails?address=B`,
`/admin/mails_unknow`, `/admin/address`, and `DELETE /admin/delete_address/<B>`.

So the polling loop — the call that runs every 2s for up to two minutes — uses
the scoped JWT, and the admin secret is reserved for create, delete, enumerate,
and the unknown-mail diagnostic.

## Decisions

1. **Credential storage.** `ToolCredential.config` is a plain JSON column, so it
   cannot hold `admin_auth`. Add an encrypted `secret` column to
   `ToolCredential` (Fernet, via the existing `EncryptedString`). One migration,
   and it serves every future tool credential — today `ToolCredential` has
   nowhere safe to put a secret at all.
2. **Two nodes, split by privilege.** `mailbox_action` carries the credential and
   does network I/O. `mailbox_parse` is pure — no network, no secret — so it is
   safe to expose to an agent.
3. **Least privilege from the start.** Poll with the mailbox JWT; escalate to the
   admin credential only for the "nothing arrived anywhere" diagnostic.
4. **The JWT is a port output, not `_state_patch`.** Pipelit's Jinja context is
   exactly `node_outputs` plus `trigger` (`services/expressions.py`), so a value
   sent via `_state_patch` never reaches `{{ }}` — which would defeat both
   intended consumers, subagents and humans reading the canvas. Revocation is
   `delete_mailbox`, not log hygiene.

## Two hazards to carry across the port

Both are documented in the TypeScript and were paid for once already.

- **Decode quoted-printable before extracting URLs.** A real captured message
  splits its own link, and the `text/plain` and `text/html` parts break in
  *different* places — so an undecoded regex yields a truncated host from one
  part and a 24-character prefix of a 32-character token from the other. Both
  look plausible. `fixtures/confirm-email.eml` pins this.
- **The URL length bound is load-bearing.** It was 300 once and silently
  truncated real tokens: a capped greedy quantifier returns a prefix rather than
  failing, so the caller gets a plausible token and the blame lands on the
  endpoint. Keep it well above any token this platform issues.

And one gotcha the service itself imposes: **it strips every non-alphanumeric
character from the mailbox name** and prepends its own `tmp`. `e2e-1234-ab`
becomes `tmpe2e1234ab@…`. The returned `address` is authoritative and must never
be reconstructed from the name — which also means an `e2e_` prefix convention
loses its underscore, and anything grepping for the punctuated form matches
nothing.

## Actions

`mailbox_action` (credentialed):

| operation | notes |
|---|---|
| `create_mailbox` | → `address`, `address_id`, `jwt` as separate ports |
| `delete_mailbox` | keyed on the numeric id, not the address |
| `list_mails` | JWT where available, else admin |
| `wait_for_mail` | bounded poll; three distinct failure codes |
| `wait_for_verification_email` | `wait_for_mail` + token extraction, one node |
| `wait_for_reset_password_email` | same shape |
| `list_unknown_mails` | admin-only diagnostic |
| `prune_mailboxes` | enumerate by prefix/age, delete; **dry-run by default** |

`mailbox_parse` (pure): `extract_verify_email_token`, `extract_reset_password_token`,
`extract_urls`, `decode_quoted_printable`.

`wait_for_mail`'s three-way failure is the valuable part and must survive as
distinct `error_code`s: matched / arrived-but-nothing-matched / nothing-arrived
(plus the unknown-address hint). "The platform never sent it" and "we are
watching the wrong address" need different responses.

Default timeout is **150s** — observed verification latency is 60–120s, so the
driver's 60s default sits exactly where it flakes. That stays inside Pipelit's
5-minute node timeout.

## Lifecycle — and why prune is the dangerous one

353 addresses exist on the instance; 322 start with `tmpe2e`, and nothing has
ever cleaned up. But **the prefix carries no ownership**: `e2e` is
portal-client's `e2eId()`, shared across repos, so a prefix match sweeps up
every mailbox any suite has created — including the permanent fixtures in
`portal-client/docs/funded-entity-handover.md`. `tmpe2e178623933674lfew@mcp.kiwi`
belongs to the only funded, vendor-ready entity, described there as
irreplaceable, and it matches.

The damage would be irreversible in an unusual way: nothing in the portal API
deletes a user, so the account outlives its mailbox with no channel for password
reset or email confirmation — permanently half-usable, impossible to recreate.

**An age floor does not solve it.** Measured 2026-08-16: all 322 matching
mailboxes were 3-7 days old and the funded fixture sat at the median.
`older_than=3` would delete 307 including the fixture; `older_than=7` deletes
nothing. No threshold separates junk from treasure, so age is a secondary guard
and the protect list is what actually discriminates.

So `prune_mailboxes` requires an explicit `prefix` (no default), an explicit
non-empty `protect` list, and `confirm=True` before deleting anything; caps a
run at 25; and defaults to dry-run. It must never be called from a lifecycle
hook — a blind prefix match on a timer is how the funded fixture disappears at
3am.

## Registration checklist

`component_configs` uses single-table inheritance, so **no migration is needed
for node types** — only for the credential column.

1. `models/node.py` — config class with `polymorphic_identity` + entry in `COMPONENT_TYPE_TO_CONFIG`
2. `components/__init__.py` — import
3. `schemas/node.py` — `Literal` member
4. `schemas/node_type_defs.py` — `register_node_type` with ports
5. `frontend/src/types/models.ts` — union member
6. `frontend/.../NodePalette.tsx` — `ICONS` entry
7. `frontend/.../NodePalette.tsx` — `NODE_CATEGORIES` entry

CLAUDE.md lists the first five. **Six and seven are real and were missing from
it**: a type absent from `NODE_CATEGORIES` exists in the API and renders on the
canvas but can never be *added* from the palette, which is indistinguishable
from the node not existing. `ICONS` is a `Record<ComponentType, …>` so the
compiler always caught that one; `NODE_CATEGORIES` was a plain array and had
drifted — `router` was unreachable from the UI. Both are now compiler-enforced,
and the exhaustiveness check was verified to fail by removing a type and
watching tsc name it.

## Out of scope / parked

- Where the credential store lives on disk, its permissions, and whether any of
  this is mounted into the agent sandbox — parked by decision.
- The portal-client bin and its session/account model — separate track, under
  discussion with the peer working in that repo.
