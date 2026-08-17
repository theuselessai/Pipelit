# Plan: binary → node catalog protocol, and the scope of the three binaries

**Status:** design, not started
**Branch:** none yet

## Why this exists

`test-hub/src/catalogue/` holds 113 L1 primitives and **106 curated L2 actions**
across 10 domains, with 46 of 48 known gaps closed and hazards measured against
live UAT. test-hub is being abandoned.

The mailbox nodes were the first extraction from it — 5 of those 106 actions,
and they cost a services module, a 307-line component, a migration, seven
registration sites and three follow-up PRs. Repeating that 101 times is not a
plan. This is the general extraction: three binaries that describe themselves,
and one ingestion path in Pipelit.

**The expensive artefact is the catalogue, not the binaries.** The binaries are
the vehicle.

## Not MCP, deliberately

MCP hands a model a tool list at runtime over a live session. Pipelit's nodes are
typed vertices in a DAG that must exist *before* anything runs — `EdgeValidator`
resolves ports through `get_node_type(component_type)` at edge-creation time, and
the canvas draws them before an execution exists. A schema that arrives at
runtime cannot be validated at design time. The models genuinely conflict.

So: one process per invocation, no session, no negotiation, no server lifetime.

## The protocol — three verbs

```
<bin> catalog                                   # global. no env, no session, no network
<bin> --session <id> call <op>                  # input JSON on stdin, envelope on stdout
<bin> --env <name> --session <id> auth login    # always overwrites. binds slot → env.
<bin> --session <id> auth refresh
<bin> auth session list                         # never prints token material
<bin> auth session remove <id>                  # our copy only — NOT a revocation
<bin> env add <name> --url <base> --kind uat|prod
<bin> env list
<bin> env remove <name>
```

stderr is logs, exclusively. stdout is one JSON envelope.

### Environments

Environments are named, stored state in the same store as the slots — not a URL
passed per call. Pipelit therefore holds neither URLs nor credentials; a node
carries an env name and a session id, and `env list` populates that picker the
same way `auth session list` populates the other one.

**A slot belongs to an environment, and the binding is made at login.** `--env` is
required on `auth login` and meaningless everywhere else: `--session alice`
already implies its environment, because a UAT token is not merely wrong against
production, it is dangerous there. Independent `--env` and `--session` selectors
would make "UAT session, production base URL" expressible, and anything
expressible eventually gets expressed.

**`env add` is where the host assertion moves.** `--kind` is mandatory and has no
default, so declaring an environment production is a deliberate act — but the
kind is *also* cross-checked against the host, and a mismatch is refused at add
time rather than on the hot path. Integral's driver refuses any host without
`uat` in it (`test-hub/src/drivers/integral/config.ts`); that check belongs here,
once, rather than on every call.

**`env remove` refuses while slots reference it.** Remove the sessions first —
two explicit steps, the same shape as re-pointing a session id, and no flag.

**The env schema is per-binary and declared in the catalog.** One base URL is not
always enough: `zc-integral` needs both `/v2/` and the custody root, which live on
different hosts.

**`catalog` is environment-independent.** The operation surface is a property of
the client version, not of where it points. That is what keeps the catalog a
single committed artifact — but it also means **two environments running
different API versions cannot both be described**, and the drift check compares
against the client, not against any deployment. Worth knowing before UAT and prod
diverge.

### Names

| binary | repo | authority |
|---|---|---|
| `zc-integral` | `gen_2/integral_api_client` | trading account |
| `zc-portal` | `gen_2/portal-client` | **customer** |
| `zc-portal-admin` | `gen_2/admin-portal-client` | **admin — 12 irreversible writes, incl. fund release** |

The `zc-` prefix keeps these the org's binaries rather than Pipelit's — the whole
design rests on the binary not knowing Pipelit exists, so a `plit-` prefix would
encode the dependency backwards.

🔴 **`zc-portal` and `zc-portal-admin` differ by a suffix, and differ by
authority.** Tab-completion, a truncated dropdown, and a hurried glance at a node
config all resolve that difference badly, and the failure is acting with admin
authority where customer authority was meant. A maximally distinct name was
considered and rejected in favour of mirroring the repos, so the mitigation moves
into the UI instead: **the node config must render the authority level
explicitly**, not leave it to be inferred from the tail of a string. Same class of
guard as the `trigger_` prefix stripping on canvas labels — the name is not
allowed to be the only thing carrying the meaning.

Downstream naming follows:

```
binary_id (version-pinned)   zc-portal@1.4.0
catalog file                 platform/catalogs/zc-portal.json
node component_type          portal_funding, portal_identity,
                             portal_admin_verification, integral_orders, …
```

Component types drop `zc-`: inside Pipelit they share a namespace with
`mailbox_action` and `switch`, where an org prefix buys nothing and costs canvas
width.

### Decisions

1. **The catalog is a committed artifact**, refreshed by a script and
   drift-checked in CI — not runtime discovery. If node types were registered
   from whatever the binary reported at startup, a binary upgrade would silently
   mutate every saved workflow's ports, and `resolve_expressions` turns a port
   that vanished into the literal string `{{ node.port }}` travelling onward *as
   if it were a value*. That is what `_blank_ports()` in `components/mailbox.py`
   exists to prevent. portal-client already enforces this rule on itself:
   everything in `src/generated/` is committed so the drift check has something
   to compare against.

2. **The catalog records `generated_from`** — source tree *and* commit. There are
   two copies of the integral client (`gen_2/integral_api_client`, 2026-08-10, is
   authoritative; the standalone repo is a month behind). A catalog generated
   from the stale tree hashes cleanly and describes a surface nobody runs.

3. **The binary path is never node data.** Nodes store `binary_id` +
   `operation`; the id resolves through a server-side allowlist in config,
   checksum-pinned. A `binary_path` field on a node config is a remote-code
   execution primitive for anyone who can edit a node — and agents can create
   nodes (`workflow_create`, `spawn_and_await`). It would also reopen the hole
   `remove-unsandboxed-fallbacks` just closed.

4. **Auth does not fold into `call`.** A refresh is not a workflow step, it is a
   precondition of one: expiry happens at a *time*, not at a place in the graph,
   so there is no static vertex you can draw where it lands. Auth's output is
   also the one secret we must never render — every other operation's output
   goes into a canvas popover and an `ExecutionLog` row.

5. **`call` may return slot mutations.** Both clients refresh *inside* the
   request path (integral proactively at expiry−60s and reactively on 401; portal
   reactively on `UNAUTHENTICATED`), so an ordinary operation can mint a token as
   a side effect. Some operations also rewrite the *credential* — enrolling a
   TOTP device mints a seed, resetting a password invalidates the stored one. The
   envelope therefore carries an optional slot patch on every response, and the
   executor writes it back. Without it we churn tokens, strand freshly minted
   seeds, and silently break every login after a password reset.

6. **`--session <id>` names a slot in a store**, and the store is a directory —
   injectable (the `GNUPGHOME` trick), defaulting to `$XDG_STATE_HOME` so a human
   at a terminal gets one for free. **The binaries own it, uniformly** (decided;
   was open question 5): each slot holds credentials, TOTP seed and session
   tokens, and **Pipelit holds no secrets for any of the three** — only an env
   name and a session handle. One slot is one identity, end to end.

7. **No default session.** Missing `--session` is a usage error, exit-code
   distinct from an auth error. A default is ambient authority, and ambient
   authority is how a workflow ends up acting as admin because admin was the last
   thing that logged in. Required *iff* the catalog says the operation needs one
   — `identity.register` and `confirmEmail` are genuinely public, so the rule
   lives in the data rather than in a special case.

8. **`auth login` always overwrites.** No `--replace`. The binary cannot know
   what a slot name was *supposed* to mean, and the guard would have fired in the
   automated recovery path (401 → refresh rejected → re-login) rather than on
   operator error. Identity stability is enforced a layer up, where session ids
   are namespaced under a credential and a node cannot reference a session its
   credential does not own.

9. **One store, shared by all three binaries — and it is a vault, not a privilege
    boundary.** An earlier draft proposed a store per binary so the admin identity
    sat apart. That was wrong: the stores would share a filesystem and an OS user,
    so any process that reads one reads all of them. Directory separation buys the
    appearance of a boundary and none of its substance, while splitting a journey
    that legitimately spans customer *and* admin actions across two identity
    spaces.

    A real boundary is an OS user or a separate machine, and that is a deployment
    decision this plan does not make. What actually constrains authority here is
    the env's `kind` assertion (§Environments), explicit authority rendering on the
    node (§Names), and filesystem permissions on the store itself. Anyone who can
    run the binary can act as any identity in it — state that plainly rather than
    implying otherwise.

10. **Pipelit needs no session storage at all**, which is one reason client-side
    custody won. Had it held them, `ToolCredential.secret` could not: it is
    `EncryptedString(500)` and 500 is the *ciphertext* budget — Fernet's base64
    and ~100 bytes of overhead leave roughly 280–300 characters of plaintext, and
    a portal session is a JWT plus a refresh token. A new table was the only
    alternative. Recorded because the constraint outlives the decision.

11. **Single-flight lives above the binary.** `Procfile` runs a 4-worker pool
    plus a scheduler, and nodes of one execution scatter across processes.
    integral's own stampede guard is an `asyncio.Lock`
    (`auth/manager.py:119-130`) — correct, and invisible across four processes.
    Portal is worse: it enforces **one active session per user and a second login
    invalidates the first**, so concurrent logins mutually evict in a loop that
    never converges. Redis lock, keyed by `(binary, store, session id)` — the
    slot, since under the client-side model Pipelit has no credential row naming
    the account.

12. **The session is selected on the node.** `auth session list` is what
    populates that picker — the catalog supplies the operations, `session list`
    supplies the identities, and both are read-only and secret-free by
    construction (`list` prints id, subject, `expires_at`, `created_at`,
    `last_used_at`, never token material). A node therefore carries
    `credential_id` → which store, plus `session_id` → which slot in it. Required
    iff the catalog says the operation needs a session, and enforced at design
    time: `EdgeValidator.validate_required_inputs()` already fails nodes missing a
    required model connection, and this is the same shape of check.

## The catalogue format: adopt L1/L2, do not reinvent

test-hub's `ActionDef` already carries what this needs. Two fields in particular
were not on our list and would have been missed:

- **`proof`** — how a write is known to have worked: `readBack` (an operation
  that reflects it), `behavioural` (nothing reads it back; a later call differs),
  or none for reads. Not optional for mutating actions.
- **`trap`** — a *measured* hazard, per operation. The mailbox plan's
  quoted-printable decoding and URL length bound are traps; this promotes them
  from a paragraph in a doc to a field that travels with the operation.

Also carried: `safety` (read/write/delete/irreversible), `session`, `composes`,
`inputs`/`outputs` as typed domain refs, `params`, `mutating`.

**Revision to an earlier position:** we intended to restrict catalog types to
Pipelit's `DataType` enum so `EdgeValidator` could not become a liar. L2 uses
domain refs — `LegalEntityRef`, `SessionRef`, `CredentialRef`, `MailboxRef` — and
those are far better port types. `LegalEntityRef → LegalEntityRef` is a real
check; `object → object` is not. Teaching the registry named domain types is more
work and worth it.

**Granularity follows from L2:** one node type per *domain*, actions as scoped
operations. Ten node types, not 106 and not 3.

## Shared scope rules

1. **Scope follows purpose, not fear.** Danger is not a reason to exclude an
   operation — for `portal` and `admin` the dangerous paths (withdrawals,
   approvals, KYB gates, fund release) are precisely what these binaries exist to
   exercise, and a catalog that omits them cannot test the thing worth testing.
   Scope is cut by *requirement*: `integral` is 17 operations because the
   business asked for seven capabilities, not because the other 28 were scary.
   Exclude only what **cannot work** (headless-impossible flows) or **is not
   action-shaped** (streaming). Everything else is included and *guarded*.

   The guards, in order of strength:
   - **UAT asserted when the environment is added**, and carried by the slot
     thereafter — the binary cannot reach production unless someone declared a
     production environment on purpose, so an irreversible operation is
     irreversible only against test data.
   - **`effect` + `proof` declared** — so a destructive call is visible on the
     canvas and a write that returns `202`-with-no-body is still verifiable.
   - **A protect list for irreplaceable fixtures** — the one hazard the UAT
     assertion does *not* cover. `prune_mailboxes` nearly deleted the only funded
     vendor-ready entity, and `deleteOrArchiveEntity` reaches the same fixture.
     Unrecoverable on UAT is still unrecoverable.
   - **Blast radius that escapes UAT** — the exception that no host assertion
     fixes. `admin.onboardIntegral` / `onboardElysium` call *real external vendor
     APIs* from the UAT backend; asserting the admin host says nothing about what
     that backend then dials. This is the one category to weigh separately.
2. **Environment is declared, never inferred.** No default base URL; a missing or
   unknown `--env` is a loud error. `--kind uat|prod` is mandatory on `env add`
   and cross-checked against the host there — before the first call, not merely
   before the first write.
3. **`effect` is authored, not derived from the HTTP verb.** See
   `integral.trades.stp_messages` below.
4. **Every write declares its proof.** Several endpoints here return `202` with
   an empty body, or `200` on failure.
5. **Traps are carried across, not rediscovered.**

---

# Binary 1 — `zc-integral`

Source of truth: **`gen_2/integral_api_client`** (2026-08-10). 66 public methods:
45 one-shot REST, 4 polling, 17 streaming.

**Scoped to 7 business requirements → 17 operations.**

| # | Requirement | Operations |
|---|---|---|
| 1 | Tradable pairs | `refdata.list_symbols`, `refdata.get_symbol` |
| 2 | Balances | `custody.get_account_balances` |
| 3 | RFQ + accept | `rfs.get_quote`*, `rfs.accept_quote`, `rfs.get_by_request_id`, `rfs.get_by_cl_order_id`, `rfs.cancel`, `rfs.wait_for_terminal` |
| 4 | Done trades | `trades.get_by_order_id`, `trades.get_by_co_id`, `trades.get_by_id` |
| 5 | Place limit order | `orders.place` |
| 6 | Cancel limit order | `orders.cancel` |
| 7 | Order status | `orders.get_by_id`, `orders.get_by_co_id`, `orders.wait_for_terminal` |

\* `rfs.get_quote` is an L2 composition, not a raw method — see below.

## 🔴 The vendor SDK defaults to PRODUCTION

`test-hub/src/drivers/integral/config.ts`, first line of its documentation:

> *"The vendor SDK defaults `INTEGRAL_BASE_URL` to PRODUCTION, and its accept
> endpoint executes a real trade. This driver therefore takes the base URL by
> argument, has NO default, and refuses any host that is not visibly UAT. A
> missing config is a loud error, never a fallback."*

Requirement 3 *is* that endpoint. The binary must carry the same construction-time
host assertion. Note that `bdd_api_test/.env.example` ships
`INTEGRAL_API_URL=https://api.integral.com` — production, in an example file.
That is the trap, live.

## What is excluded, and why that beats guarding it

- **`orders.cancel_all()`** — `DELETE /v2/orders`, no arguments, cancels
  everything. Nothing in the seven needs it.
- **All STP** (`stp_messages`, both iterators, `stp_resend`) — a `GET` that
  **consumes the queue**. Call it twice and the second call returns nothing.
  Any generator inferring safety from the HTTP verb calls this read-only and
  hands an agent a "just check the messages" tool that eats the data.
- **All custody money movement** — `withdraw`, deposit address, both histories.
  The binary becomes structurally incapable of moving funds.
- **`trades.cancel`** — cancelling a *booked* trade is post-trade ops, not
  requirement 6, and trivially confused with `orders.cancel` on a canvas.
- **All 17 streaming ops** — need a persistent WebSocket. `place_order` and
  `cancel_order` exist over both transports, so excluding streaming costs
  latency, not capability. Streaming that should *start* a workflow is a trigger,
  structurally identical to `trigger_telegram` receiving pushes — a different
  track, not this catalog.
- **All 6 market_data, both positions** — not in the seven. Cheap to add later.
- **The 5 `NotImplementedError` stubs** (`amendment`, `roll`, `allocations`,
  both broker-balance methods) — reflection over public methods yields nodes
  that render, validate, and fail every time. Generation needs an allowlist.

**Nine destructive operations drop to two**, both requiring an explicit id
(`orders.cancel`, `rfs.cancel`). No zero-argument destructive operation survives.

## `rfs.get_quote` — one operation, two possible upstream shapes

`RFSRequest.rfq=True` "turns the streaming request into a one-shot RFQ"
(`models/rfs.py`); `RFSResponse.quotes` may carry them directly, and
`Quote.transactionId` is "populated for RFQ-mode responses". But the resource
docstring describes the streaming flow — *"the caller polls
`get_by_request_id` until a quote arrives"* — and we have no credentials to
settle which happens live.

So the operation absorbs it: request with `rfq=True`; if quotes are present,
return them; otherwise poll until quoted or `expiry` elapses. Same node contract
either way. **Assumption to verify on the first credentialed run**, not a blocker.

Two clocks, easily swapped:

- `RFSRequest.expiry` — **seconds**, how long *you will wait for a quote*.
- `Quote.expiryTime` — a timestamp, how long *the price is good for*.

The second governs whether accept can happen in time. Pipelit's per-node cost
(RQ enqueue → worker → Redis read → process spawn → TLS) must fit inside it,
which is why request-and-quote is one node rather than three.

## Traps to carry

- **Accept returns `202` with an empty body.** `_parse_or_synthesize` mints an
  `RFSResponse` from correlation ids it already had. Accepting a quote tells you
  *nothing* about whether you traded. `proof: readBack` is mandatory here —
  without it a workflow can accept quotes for a week and never notice it never
  traded. The same applies to `orders.cancel` and `rfs.cancel`.
- **`INTEGRAL_ORG` is `ZC_` + the *last* 8 hex of the entity UUID**, while scratch
  credential filenames use the *first* 8 — `…-77cf4035` carries org `ZC_d7a9f5b0`.
  Recorded as having confused two sessions already.
- **`expiry` is seconds, not milliseconds**, and is not auto-converted.
- **`priceType` must be PascalCase `"Spot"`** for spot RFQ; `"OUTRIGHT"` is
  rejected with `InvalidType`.
- **RFS terminal states are unverified.** `_TERMINAL_RFS_STATUSES` carries a
  `TODO: verify exact RFS terminal states with UAT`.

## Auth

`POST /sso/login` with username + password + org; `GET /sso/token/renew`. These
become the `auth` verbs, not catalog operations. `username` and `org` live in
`ToolCredential.config`; `password` in `secret`. Note the auth analysis was done
against the *stale* standalone copy and should be re-confirmed against gen_2.

Balances sit on `/custody/v2/*` with absolute URLs, a different base from `/v2/*`
— confirm one SSO token authorises both.

---

# Binary 2 — `zc-portal`

129 spec operations across 24 tags in `src/generated/operations.ts`, generated
from `openapi.json` with a committed drift check. test-hub emits 113 as L1 (16
scope-excluded) and curates **106 L2 actions**, 63 of them mutating, 15 proven by
read-back.

**Proposed scope: the L2 actions whose platform is `portal`** — identity 22,
compliance 16, funding 18, approvals 10, access 10, settings 5, reference 4
(≈85), excluding `admin` (13, binary 3), `mail` (5, already shipped as
`mailbox_action`), and `trading` (3, binary 1).

**This has not had the trim integral got** — the L2 catalogue is the *candidate*
set, not the scope. But note the trim is by requirement, not by risk: the
withdrawal and approval paths stay in. `createCryptoWithdrawalWorkflowInstance`,
`createFiatWithdrawalWorkflowInstance` and `approveWorkflowInstance` are the
money-moving operations, and they are the ones most worth exercising end to end.

Excluded for capability and shape only:

- the **4 passkey ceremony operations** (`createRegistration`,
  `verifyRegistration`, `createAuthentication`, `verifyAuthentication`) — a
  WebAuthn ceremony needs an authenticator; there is no headless path. The plain
  REST passkey operations (`listCredentials`, `updateCredential`,
  `deleteCredential`) stay.
- **`streamNotificationEvents`** — SSE. Trigger-shaped, like integral's
  WebSocket surface, and belongs to that track rather than this catalog.
- **`verifyMfaRecoveryCode`** is *in* the catalog but must never be called by an
  automation: recovery codes burn on use.

## The binary owns the credentials, and the TOTP

**Pipelit holds no portal secrets.** The store is the client's own and each slot
is a whole identity — label, username, password, TOTP seed, and the session
tokens minted from them. `--session <id>` selects the slot, and one slot means
one identity end to end.

That inverts four things from the shared decisions above:

- **TOTP is the client's.** `auth login` derives the code from the seed in its own
  store. `components/get_totp_code.py` is not in this path; Pipelit never sees a
  seed and never computes a code.
- **`auth login` takes username and password, and saves them.** First login for a
  slot supplies them; the slot keeps them, so later logins may omit them and
  reuse what is stored. That is what makes unattended re-login possible after a
  refresh is rejected — the recovery path needs no external secret.
- **Pipelit's `ToolCredential` for portal carries no secret at all** — base URL,
  environment, and which store to resolve. `EncryptedString(500)` stops being a
  constraint here.
- **A Pipelit database dump contains no portal credentials.** The platform's blast
  radius shrinks to the store path.

### MFA management is operations, not auth verbs

**Only login and refresh leave the catalog.** Everything else in the auth family
stays a catalog operation, on the canvas, with ports — enrolling a TOTP device,
removing one, listing methods, regenerating recovery codes, resetting a password,
confirming an email. That is 18 MFA-tagged operations in portal's registry
(`auth-mfa-otp` 5, `auth-mfa-passkey` 7, `auth-mfa-recovery` 4,
`auth-mfa-challenge` 1, `auth-mfa` 1) plus most of the 10 under `auth`. Three
operations become verbs; the rest are nodes.

The reasoning that took `login` out of the catalog does not reach these. A
refresh is a precondition of an operation with no place to stand in the graph.
Enrolling a device is a step someone deliberately performs, in an order that
matters, with a result worth seeing — which is the definition of a node.

**Some of these operations write to the slot.** Enrolling a TOTP device *mints
the seed*; resetting a password *invalidates the stored one*. So the envelope's
slot channel is not only for sessions: `call` may return credential mutations
too, and the executor writes them back the same way. Without that, an enrolment
node produces a seed nothing can use, and a password reset silently breaks every
later login from that slot.

**Secrets these operations mint go to the slot, never to a port.** A node output
renders in a canvas popover and persists in an `ExecutionLog` row. The mailbox
plan put the mailbox JWT on a port deliberately, because downstream nodes needed
it through `{{ }}` — a TOTP seed has no such consumer. Its only reader is the
binary, which already has the store.

**Step-up MFA stays inside `call`.** `src/lib/mfa/challenge.ts` handles
per-operation challenges for withdrawals and API-key creation. Those are
preconditions of the specific call, satisfied from the slot's seed in-process —
the same argument as refresh, not the same as enrolment.

### Auth is two-legged; the binary hides the seam

`POST /api/auth/login` returns a temp token with `mfa_required: true`,
`expires_in: 300`, empty refresh token; `POST /api/auth/mfa-verify/otp` completes
it. **`auth login` performs both legs internally**, so the 300-second-fuse temp
token never leaves the process and there is no second verb to sequence.

Only `APP_OTP` works. SMS needs a request-code round trip and a human's phone;
passkey needs a WebAuthn ceremony; recovery codes burn and must never be spent by
an automation. **Accounts used by Pipelit must be enrolled in APP_OTP**, and the
other methods are declared unsupported rather than half-attempted.

### `auth login` is never interactive

No prompts, no tty, no browser, no "press enter". It runs from an RQ worker with
no controlling terminal. A missing field is a loud error — the binary must never
fall back to asking, the same discipline as the absent base-URL default.

### Populating the store

Two ways in, and no extra verb for either:

- **`auth login`** — supply username and password for a slot that has none, and
  the credential is saved as a side effect of the first successful login. This
  covers accounts that already exist and cannot be registered, including the
  permanent UAT fixtures in `portal-client/docs/funded-entity-handover.md`.
- **`identity.register`** — an *operation*, not an auth verb. test-hub's action
  already takes `saveAs: "j1-ubo"` and outputs a `CredentialRef`, so an e2e
  workflow registers an account and the binary saves the identity locally. This
  is how ephemeral personas are born.

**Secrets do not travel on argv.** `/proc/<pid>/cmdline` is world-readable, so a
password passed as a flag is visible to every local process for the life of the
call. `--session` and `--username` are flags; the password and the TOTP seed
arrive on stdin with the rest of the input envelope. This is the same rule the
`call` verb already follows and there is no reason for `auth` to differ.

### 🔴 Both factors in one file

A slot holds the password *and* the TOTP seed, so anything that can read the
store is a complete account takeover — the second factor is not a second factor
when a machine holds both. This is inherent to unattended automation rather than
a flaw in the design, but it must be written down rather than glossed:

- the store is a credential file with the blast radius of a password vault;
- **whether it is visible inside the agent sandbox is now a blocking question,
  not a parked one** — `SandboxedShellBackend` makes `/home` invisible for
  exactly this class of reason, and an agent that can read this store can act as
  every identity in it;
- slots must be dedicated automation accounts, never a human's, and never one
  with more authority than its journeys need.

## 🔴 One active session per user

`src/lib/auth/session.ts:36-45` — a second login invalidates the first, and the
evicted session's next request gets a 401 saying *"You have logged in from
another location."*

- `auth login` is **destructive**: it destroys another party's working state.
- The eviction 401 needs its own error code, distinct from bad credentials.
- If an operator is logged into the portal UI as the same account a workflow
  uses, the workflow kicks them out.
- **Each slot must be a dedicated account, never a human's.** Whether one account
  serves all lanes or N are provisioned is parked — the mailbox plan already recorded the portal session/account model as
  a separate track under discussion with the peer in that repo.

## Logout is not a kill switch

`POST /api/auth/logout` clears the client's copy and does **not** revoke
server-side; the access token still authenticates and the refresh token still
mints sessions (refresh tokens are not rotated, `refresh.ts:187`). Hence there is
no `auth revoke` verb — a verb that looks like a kill switch and isn't one is
worse than none. Deleting a Pipelit credential does not neutralise a leaked
session. This belongs in the docs, loudly.

## A trap already measured

Names are split word-by-word into a `varchar(32)` username column; an overflow is
an **unhandled 500, not a 422**, and invitee emails already run 31 of 32
characters (`identity.register`). Vendor balances are on Zerocap's books — a
negative `net_bal` means Zerocap *owes* the client, and the displayed balance is
`-1 * (net_bal - payments_bal)`; use portal-client's
`computeAvailableBalance(mergeBalancesByProduct(rows))` rather than re-deriving
it (`funding.readBalances`).

## One repo-shape decision up front

portal-client's core is deliberately framework-free, with a measured boundary
graph (`scripts/boundary-graph.mjs`, `src/lib/platform-boundary.test.ts`). A CLI
entrypoint is a third export condition and will appear in that graph. Decide the
split before writing it, so the binary does not drag React into the core.

---

# Binary 3 — `zc-portal-admin`

TypeScript library, v0.1.0, headless client for the Django admin back office. No
OpenAPI spec, no generated registry — hand-coded, so the catalog is
hand-declared with a drift test (test-hub's pattern for the same driver).

**14 operations: 2 read, 12 write. Every write alters real customer state, and
there is no undo path for most of them.**

Auth is Django session cookie + CSRF, not JWT — a different session shape
entirely, which is exactly why the session blob is opaque to Pipelit.

## All 14 are in scope

Including the ones that look worst. `castDestinationVote` and its wrappers
`reviewBankAccount` / `reviewWithdrawalAddress` are a **two-person vote that
releases customer funds with no unapproval path** — and approving a destination
is a step every funding journey has to pass through, so a catalog without it
cannot test funding at all. Same for `reviewVerificationRequest`, where
`APPROVED` gates trading and withdrawals and is irreversible in the UI.

**"Read-only v1" was considered and rejected as dishonest**: there are only two
reads, and an admin binary that cannot approve anything cannot drive the
onboarding journeys that justify its existence.

The guard is the *environment*, not the operation list: **UAT-only, asserted at
construction**, exactly as `config.ts` does for integral. Running admin against
production is a separate decision this plan does not make.

## Two that need more than the host assertion

- **`onboardIntegral`, `onboardElysium`, `createIntegralMapping`,
  `completeVendorMapping`** — these call **real external vendor APIs** and create
  accounts in Integral and Elysium. A UAT admin host constrains what *we* dial,
  not what the backend dials onward. They also **fail silently** (200 with no
  error, detectable only by re-reading), so `proof: readBack` is mandatory rather
  than advisory.
- **`submitChangeForm`** — "POST arbitrary fields to any Django admin model",
  round-tripping every existing field because omitting one *clears* it in Django.
  Included, because it is the escape hatch that makes arbitrary state reachable
  for a test — but it is **structurally unclassifiable**: no fixed `effect`, no
  `proof`, no stable ports, since all three depend on the model being written.
  If it stays in the catalog it needs its safety declared per *call* rather than
  per operation, which no other entry requires. Flagged as the one place the
  catalogue format does not fit.

## The fixture problem the host assertion does not solve

`deleteOrArchiveEntity` (portal) and the admin review paths reach the permanent
UAT fixtures in `portal-client/docs/funded-entity-handover.md` —
`tmpe2e178623933674lfew@mcp.kiwi` belongs to the only funded, vendor-ready entity
and is described there as irreplaceable. Unrecoverable on UAT is still
unrecoverable. This is the `prune_mailboxes` lesson: a protect list, not an age
floor and not a host check.

Note `reviewVerificationRequest` requires the `verification.change_verificationrequest`
Django permission and a view-only account silently 403s — an authorization
failure distinct from an auth failure, and a distinct error code.

---

## Cross-cutting open questions

1. **Proof can cross binaries.** `admin.reviewKybRequest` runs against admin and
   is proven by `getLatestKybVerificationRequest` on *portal* — two binaries, two
   sessions, one action. Either proof is advisory metadata Pipelit records, or
   the executor performs the read-back and needs both binaries wired. The second
   is much more valuable and much more work.
2. **Portal's account model** — one account for all lanes, or N provisioned.
   Parked with the peer in that repo.
3. **Named domain types in the node registry** — how `LegalEntityRef` and friends
   reach `PortDefinition` without flattening to `object`.
4. **Per-node ports.** `get_node_type()` is currently the only port source in
   validation (`validation/edges.py:48-49`). Domain-scoped node types with an
   operation dropdown work without changing that; per-operation ports do not.
5. ~~Does the client-side credential model become uniform?~~ **DECIDED: yes,
   client-side for all three.** Pipelit holds no secrets for any binary. The
   trade accepted with it: secrets live outside `FIELD_ENCRYPTION_KEY`, with no
   platform backup and no rotation path.
6. 🔴 **Is the store visible in the agent sandbox? Now blocking for all three.**
   One shared store, holding every identity's password and TOTP seed, is a full
   takeover for anything that can read it — and `SandboxedShellBackend` makes
   `/home` invisible for exactly this class of reason. See "Both factors in one
   file". This is the highest-priority unresolved item in the plan.

## Spike order

1. **`integral`** — 17 operations, no CLI to disturb (no `[project.scripts]`, no
   `__main__.py`), and the destructive surface already cut to two. Prove the
   three verbs, the session store, the drift check, and port synthesis.
2. **`portal`** — largest catalogue, generated L1 already exists, needs the
   requirements trim first.
3. **`admin`** — smallest surface, highest blast radius, hand-declared catalog.
   Last, and behind a UAT assertion.

## Out of scope

- Streaming, on all three. It is trigger-shaped, not action-shaped.
- Running any binary against production. Every binary in v1 asserts UAT at
  construction.
- ~~Whether the session store is mounted into the agent sandbox~~ — no longer
  parkable for `portal`, since the store holds credentials and TOTP seeds. Open
  question 6.
