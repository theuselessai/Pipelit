"""Temp-mail driver — a self-hosted `cloudflare_temp_email` instance.

Ported from an internal TypeScript driver, which was itself ported from an
earlier test-suite adapter. The comments that explain *why* something is done a
particular way are carried across deliberately: they document bugs that were
paid for once already.

─────────────────────────────────────────────────────────────────────────────
USE THIS FOR TRANSITIONS, NEVER FOR ASSERTIONS.

It gets an account into a state (registered / confirmed / invited). What the
client under test then does with that state is asserted elsewhere, against the
product's own API.
─────────────────────────────────────────────────────────────────────────────

Two authentication surfaces, and the difference is the whole security story:

    /admin/*   `x-admin-auth`, a static shared secret, reaching EVERY mailbox
               on the instance — list, read, delete.
    /api/*     a per-mailbox JWT handed back by `POST /admin/new_address`,
               reaching that one mailbox.

Verified against the live instance 2026-08-16: a mailbox JWT reads its own
`/api/mails` and `/api/settings` (200) and is refused (401) on
`/admin/mails?address=<other>`, `/admin/mails_unknow`, `/admin/address`, and
`DELETE /admin/delete_address/<other>`. So polling — the call that runs every
two seconds for up to two minutes — uses the scoped token, and the admin secret
is reserved for create, delete, enumerate, and the unknown-mail diagnostic.
"""

from __future__ import annotations

import logging
import quopri
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote, unquote

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 150.0
"""Observed verification latency is 60-120s, so the TypeScript driver's 60s
default sits exactly where it flakes. Still inside Pipelit's 5-minute node
timeout."""

DEFAULT_POLL_SECONDS = 2.0


class MailboxError(Exception):
    """Raised by every function here. Never carries a credential value."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class MailboxNotFound(MailboxError):
    """Waited, and nothing arrived for this address anywhere on the service."""


class MailboxNoMatch(MailboxError):
    """Mail did arrive, but none of it matched — a wrong expectation, not a
    delivery failure."""


@dataclass(frozen=True)
class MailboxConfig:
    """Connection details. Pure — nothing here reads the environment.

    `admin_auth` is the highest-blast-radius secret this driver touches. It is
    never logged and never included in an exception message: validation names
    the missing *field* only, so a raised MailboxError is safe to log.
    """

    base_url: str
    admin_auth: str
    domain: str

    def resolved(self) -> "MailboxConfig":
        """Validate loudly and strip the trailing slash.

        A misconfigured caller must fail before any request is made, rather than
        silently driving whatever host an empty string resolves to.
        """
        for field in ("base_url", "admin_auth", "domain"):
            if not (getattr(self, field) or "").strip():
                raise MailboxError(
                    f"MailboxConfig.{field} is required and was empty. This driver has no "
                    "environment fallback and no default host — build the config explicitly "
                    "from wherever the caller keeps its secrets."
                )
        return MailboxConfig(
            base_url=self.base_url.rstrip("/"),
            admin_auth=self.admin_auth,
            domain=self.domain,
        )


@dataclass(frozen=True)
class Mailbox:
    address: str
    """Authoritative. NEVER reconstruct this from the name — see create_mailbox."""
    address_id: int
    """Numeric id. Every `/admin/*/:id` route keys on this, not the address."""
    jwt: str
    """Per-mailbox token, scoped to this mailbox alone."""


@dataclass(frozen=True)
class Mail:
    id: int
    message_id: str
    source: str
    address: str
    raw: str
    """A full RFC-822 message, not a parsed body."""
    created_at: str

    @classmethod
    def from_row(cls, row: dict) -> "Mail":
        return cls(
            id=row.get("id", 0),
            message_id=row.get("message_id", ""),
            source=row.get("source", ""),
            address=row.get("address", ""),
            raw=row.get("raw", ""),
            created_at=row.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _call(
    cfg: MailboxConfig,
    path: str,
    method: str = "GET",
    json_body: dict | None = None,
    jwt: str | None = None,
    timeout: float = 30.0,
) -> dict:
    """One request. Uses the scoped JWT when given, the admin secret otherwise."""
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    else:
        headers["x-admin-auth"] = cfg.admin_auth

    resp = httpx.request(method, f"{cfg.base_url}{path}", headers=headers, json=json_body, timeout=timeout)
    if resp.status_code >= 400:
        # resp.text, not the request — the request carries the credential.
        raise MailboxError(f"{method} {path} failed: {resp.text[:200]}", resp.status_code)
    try:
        return resp.json()
    except ValueError:
        raise MailboxError(f"{path} returned non-JSON: {resp.text[:200]}", resp.status_code) from None


# ---------------------------------------------------------------------------
# Mailbox lifecycle (admin credential)
# ---------------------------------------------------------------------------


def generate_mailbox_name(prefix: str = "e2e") -> str:
    """A random, greppable, punctuation-free mailbox name.

    Alphanumeric only — see create_mailbox for why. The prefix is what
    prune_mailboxes and any manual cleanup match on, so it has to survive the
    service's own mangling intact.

    This is only ever a mailbox local-part. It is deliberately unrelated to the
    account's `name` field at registration: the sibling TypeScript suite reuses
    one generated id for both so a single grep finds every artifact, but that is
    a harness convention, not a property of either system.
    """
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    suffix = "".join(secrets.choice(alphabet) for _ in range(10))
    name = f"{prefix}{suffix}"
    if not name.isalnum():
        raise MailboxError(f"prefix {prefix!r} must be alphanumeric — the service strips the rest")
    return name


def create_mailbox(config: MailboxConfig, name: str | None = None) -> Mailbox:
    """Create a fresh mailbox. Generates a random name when none is given.

    `enablePrefix` makes the service prepend its configured prefix, so a name of
    `zcabc` becomes `tmpzcabc@domain`.

    The service **strips every non-alphanumeric character from `name`** —
    verified against the live instance 2026-08-08, where `e2e-1234-ab` came back
    as `tmpe2e1234ab@…`, no dashes anywhere, and reconfirmed 2026-08-16. So a
    punctuated name is rejected here rather than silently mangled: what you asked
    for would differ from what exists, and prefix-based pruning would match
    nothing. The returned `address` is authoritative regardless — never rebuild
    it from the name.
    """
    cfg = config.resolved()
    if name is None:
        name = generate_mailbox_name()
    elif not name.isalnum():
        raise MailboxError(
            f"Mailbox name {name!r} contains non-alphanumeric characters, which this service "
            "silently strips (verified live: 'e2e-1234-ab' -> 'tmpe2e1234ab@…'). Pass an "
            "alphanumeric name so the address matches what you asked for and stays greppable."
        )
    created = _call(
        cfg,
        "/admin/new_address",
        method="POST",
        json_body={"enablePrefix": True, "name": name, "domain": cfg.domain},
    )
    return Mailbox(
        address=created["address"],
        address_id=created["address_id"],
        jwt=created.get("jwt", ""),
    )


def delete_mailbox(config: MailboxConfig, address_id: int) -> None:
    cfg = config.resolved()
    _call(cfg, f"/admin/delete_address/{address_id}", method="DELETE")


def list_addresses(config: MailboxConfig, limit: int = 50, offset: int = 0) -> list[dict]:
    """Enumerate mailboxes. Rows carry id, name, created_at, updated_at, mail_count."""
    cfg = config.resolved()
    res = _call(cfg, f"/admin/address?limit={limit}&offset={offset}")
    return res.get("results", [])


# ---------------------------------------------------------------------------
# Reading mail (scoped JWT where possible)
# ---------------------------------------------------------------------------


def list_mails(
    config: MailboxConfig,
    address: str,
    limit: int = 20,
    offset: int = 0,
    jwt: str | None = None,
) -> list[Mail]:
    """List a mailbox's mail.

    With *jwt*, reads `/api/mails`, which is scoped to that mailbox and needs no
    admin secret. Without it, falls back to the admin surface.
    """
    cfg = config.resolved()
    if jwt:
        res = _call(cfg, f"/api/mails?limit={limit}&offset={offset}", jwt=jwt)
    else:
        res = _call(cfg, f"/admin/mails?limit={limit}&offset={offset}&address={quote(address)}")
    return [Mail.from_row(r) for r in res.get("results", [])]


def list_unknown_mails(config: MailboxConfig, limit: int = 20, offset: int = 0) -> list[dict]:
    """Mail addressed to mailboxes that do not exist (admin only).

    This is what distinguishes "the platform never sent it" from "we registered a
    different address than the one we are watching".
    """
    cfg = config.resolved()
    res = _call(cfg, f"/admin/mails_unknow?limit={limit}&offset={offset}")
    return res.get("results", [])


def wait_for_mail(
    config: MailboxConfig,
    address: str,
    matching=None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    describe_match: str = "a message",
    jwt: str | None = None,
) -> Mail:
    """Wait for a message, with a bounded wait and failure messages that tell the
    three cases apart.

    A suite that polls a third party otherwise reports every failure identically,
    and "the email never arrived" and "it arrived but said something else" need
    completely different fixes:

      * MailboxNoMatch   — mail is being delivered; the expectation is wrong.
      * MailboxNotFound  — nothing arrived. `/admin/mails_unknow` is then
                           consulted, because mail sitting there for a *different*
                           address means the platform is sending and we are
                           watching the wrong mailbox.

    Polls with *jwt* when supplied, so the loop never needs the admin secret. The
    unknown-mail diagnostic does need it, but only once, on the failure path.
    """
    cfg = config.resolved()
    deadline = time.monotonic() + timeout_seconds
    seen = 0

    while time.monotonic() < deadline:
        mails = list_mails(cfg, address, jwt=jwt)
        seen = len(mails)
        if matching is None:
            match = mails[0] if mails else None
        else:
            match = next((m for m in mails if matching(m)), None)
        if match is not None:
            return match
        time.sleep(poll_seconds)

    if seen > 0:
        raise MailboxNoMatch(
            f"Waited {timeout_seconds:.0f}s for {describe_match} at {address}. "
            f"{seen} message(s) DID arrive, but none matched — the mail is being "
            "delivered, so this is a wrong expectation, not a delivery failure."
        )

    try:
        unknown = list_unknown_mails(cfg)
    except MailboxError:
        logger.debug("unknown-mail diagnostic unavailable", exc_info=True)
        unknown = []
    nearby = sorted({r.get("address", "") for r in unknown} - {address, ""})
    if nearby:
        raise MailboxNotFound(
            f"Waited {timeout_seconds:.0f}s for {describe_match} at {address} and NOTHING "
            f"arrived. But mail arrived for unknown addresses [{', '.join(nearby[:5])}] — "
            "the platform is sending; the address it was given likely differs from the one "
            "being watched."
        )
    raise MailboxNotFound(
        f"Waited {timeout_seconds:.0f}s for {describe_match} at {address} and NOTHING arrived. "
        "No mail reached the service for any unknown address either, so the platform probably "
        "never sent it."
    )


# ---------------------------------------------------------------------------
# Parsing — pure. No network, no config, no credential.
# ---------------------------------------------------------------------------


def decode_quoted_printable(text: str) -> str:
    """Decode quoted-printable.

    **Soft line breaks must be removed BEFORE `=XX` decoding**, and this is not a
    detail. A confirmation email captured from the live service splits its link,
    and because quoted-printable wraps purely on line length, the two MIME parts
    break in *different* places:

        text/plain   …Confirm Email https://fe1-stv.uat.example.=
                     invalid/verify-email/A7HK2QMXR4TB9WVZ6NDJ3PLC5FGS8YE1

        text/html    …href="https://fe1-stv.uat.example.invalid/verify-email/A7HK2QMXR4TB9WVZ6NDJ3PLC=
                     5FGS8YE1" target="_blank"…

    So an undecoded `https?://…` regex gets an unusable host from the plain part
    and a **24-character prefix of a 32-character token** from the html part —
    perfectly plausible, completely wrong. The plain part happens to carry the
    token intact, so a naive regex works *by luck*: the break lands where it does
    because of line length, so a longer email address moves it.
    """
    without_soft_breaks = re.sub(r"=\r?\n", "", text)
    return quopri.decodestring(without_soft_breaks.encode("utf-8", "replace")).decode(
        "utf-8", "replace"
    )


_URL_RE = re.compile(r"https?://[^\s\"'<>]{10,1200}")
"""The upper bound is load-bearing. It was 300 in an earlier version of this
parser and silently TRUNCATED real tokens (found 2026-08-09 by the upstream
suite's live passkey-reset scenario). A capped greedy quantifier does not fail
on an over-long URL — it returns a prefix, so the caller gets a token that looks
entirely plausible and is rejected downstream, pointing the blame at the endpoint
rather than at here. The bound is kept, because an unbounded match in a mail body
is its own hazard, but sized well above any token this platform issues."""


def extract_urls(raw_message: str) -> list[str]:
    """Every http(s) URL in a message, after decoding. Order as encountered."""
    decoded = decode_quoted_printable(raw_message)
    seen: dict[str, None] = {}
    for match in _URL_RE.finditer(decoded):
        seen.setdefault(match.group(0), None)
    return list(seen)


def extract_verify_email_token(raw_message: str) -> str:
    """The email-confirmation token from a registration message.

    The link points at the SPA host (`…/verify-email/{token}`), not the API host.
    The token is then spent against `POST /api/auth/confirm-email/{token}`.

    The token is URL-decoded before being returned. The source this was ported
    from decoded only in the sibling reset-password extractor, and that asymmetry
    is a real hazard rather than a style choice: an opaque path token can carry
    percent-encoded characters, and an unencoded `/` in a path segment silently
    names a different resource once substituted into a request path.
    """
    urls = extract_urls(raw_message)
    url = next((u for u in urls if "/verify-email/" in u), None)
    if url is None:
        raise MailboxError(
            "No /verify-email/ link in the message. Either this is not the confirmation "
            f"email, or the link format changed. URLs seen: {', '.join(urls) or '(none)'}"
        )
    token = url.split("/verify-email/", 1)[1]
    if not token:
        raise MailboxError(f"Found {url} but could not read a token from it.")
    return unquote(token)


def extract_reset_password_token(raw_message: str) -> str:
    """The password-reset token from a `POST /api/auth/forgot-password` message.

    Same SPA host and path-parameter shape as the verification link. The `?token=`
    arm is not speculative generality: it costs one line and turns "the backend
    switched to a query parameter" from a baffling empty-token failure into a
    working read. The error path is the part that matters — it prints the URLs the
    message did carry, so a format change reads as a format change.
    """
    urls = extract_urls(raw_message)
    url = next((u for u in urls if "reset-password" in u), None)
    if url is None:
        raise MailboxError(
            "No reset-password link in the message. Either this is not the password-reset "
            f"email, or the link format changed. URLs seen: {', '.join(urls) or '(none)'}"
        )
    token: str | None = None
    if "/reset-password/" in url:
        after_path = url.split("/reset-password/", 1)[1]
        if after_path:
            token = re.split(r"[?#]", after_path)[0]
    if not token:
        query_match = re.search(r"[?&]token=([^&#]+)", url)
        if query_match:
            token = query_match.group(1)
    if not token:
        raise MailboxError(f"Found {url} but could not read a token from it.")
    return unquote(token)
