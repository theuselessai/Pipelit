"""Mailbox components — disposable inboxes on the self-hosted temp-mail service.

Two nodes, split by privilege:

  mailbox_action  carries the credential and does network I/O. Its `x-admin-auth`
                  secret reads and deletes EVERY mailbox on the instance, so this
                  node belongs in deterministic workflows.
  mailbox_parse   pure. No network, no secret, no credential — safe to hand an
                  agent as a tool.

Failure codes come from the exception class name (the orchestrator uses
`type(exc).__name__`), so `MailboxNoMatch` and `MailboxNotFound` arrive on the
canvas as distinct codes. That distinction is the point: "the mail arrived but
said something else" and "the platform never sent it" need different fixes.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from langchain_core.tools import tool

from components import register
from database import SessionLocal
from models.credential import BaseCredential
from services import mailbox as mb

logger = logging.getLogger(__name__)

PRUNE_MAX_DELETE = 25
"""Ceiling on deletions per run. A sweep that wants to remove more than this
should be run deliberately, more than once, by someone watching."""


def _load_config(credential_id: int | None) -> mb.MailboxConfig:
    """Build a MailboxConfig from a tool credential.

    `base_url` and `domain` live in the plain JSON `config`; `admin_auth` lives
    in the encrypted `secret` column, because `config` is not encrypted at rest.
    """
    if not credential_id:
        raise mb.MailboxError(
            "This node needs a mailbox credential (tool_type='mailbox') selected on its config."
        )
    db = SessionLocal()
    try:
        cred = db.query(BaseCredential).filter(BaseCredential.id == credential_id).first()
        if not cred or not cred.tool_credential:
            raise mb.MailboxError(f"Credential {credential_id} is not a tool credential.")
        conf = cred.tool_credential.config or {}
        return mb.MailboxConfig(
            base_url=conf.get("base_url", ""),
            admin_auth=cred.tool_credential.secret or "",
            domain=conf.get("domain", ""),
        ).resolved()
    finally:
        db.close()


def _blank_ports() -> dict:
    """Every operation emits the same port set.

    A sparse shape would be worse than it looks: `resolve_expressions` swallows
    undefined variables and returns the template text verbatim, so a reference to
    a port an operation didn't emit silently becomes the literal
    `{{ node.port }}` — which then travels onward as if it were a value.
    """
    return {"result": {}, "address": "", "address_id": "", "jwt": "", "token": "", "mails": []}


def _mail_dict(mail: mb.Mail) -> dict:
    return asdict(mail)


# ---------------------------------------------------------------------------
# mailbox_action — credentialed, network
# ---------------------------------------------------------------------------


@register("mailbox_action")
def mailbox_action_factory(node):
    """Return an executable node that performs one temp-mail operation."""
    extra = node.component_config.extra_config or {}
    credential_id = node.component_config.credential_id
    operation = extra.get("operation", "create_mailbox")

    def mailbox_action_node(state: dict) -> dict:
        cfg = _load_config(credential_id)
        ports = _blank_ports()

        # extra_config has already had its {{ }} expressions resolved upstream.
        address = str(extra.get("address", "") or "")
        jwt = str(extra.get("jwt", "") or "") or None
        timeout = float(extra.get("timeout_seconds", mb.DEFAULT_TIMEOUT_SECONDS))
        poll = float(extra.get("poll_seconds", mb.DEFAULT_POLL_SECONDS))

        if operation == "create_mailbox":
            box = mb.create_mailbox(cfg, extra.get("name") or None)
            ports.update(
                address=box.address,
                address_id=str(box.address_id),
                jwt=box.jwt,
                result={"address": box.address, "address_id": box.address_id},
            )

        elif operation == "delete_mailbox":
            address_id = int(extra.get("address_id") or 0)
            mb.delete_mailbox(cfg, address_id)
            ports.update(address_id=str(address_id), result={"deleted": True, "address_id": address_id})

        elif operation == "list_mails":
            mails = mb.list_mails(cfg, address, jwt=jwt)
            ports.update(address=address, mails=[_mail_dict(m) for m in mails],
                         result={"count": len(mails)})

        elif operation in ("wait_for_mail", "wait_for_verification_email", "wait_for_reset_password_email"):
            contains = extra.get("contains") or ""
            matcher = (lambda m: contains in m.raw) if contains else None
            describe = {
                "wait_for_mail": "a message",
                "wait_for_verification_email": "the verification email",
                "wait_for_reset_password_email": "the password-reset email",
            }[operation]
            mail = mb.wait_for_mail(
                cfg, address, matching=matcher, timeout_seconds=timeout,
                poll_seconds=poll, describe_match=describe, jwt=jwt,
            )
            ports.update(address=address, mails=[_mail_dict(mail)], result=_mail_dict(mail))
            if operation == "wait_for_verification_email":
                ports["token"] = mb.extract_verify_email_token(mail.raw)
            elif operation == "wait_for_reset_password_email":
                ports["token"] = mb.extract_reset_password_token(mail.raw)

        elif operation == "list_unknown_mails":
            unknown = mb.list_unknown_mails(cfg)
            ports.update(mails=unknown, result={"count": len(unknown)})

        elif operation == "prune_mailboxes":
            ports.update(_prune(cfg, extra))

        else:
            raise mb.MailboxError(f"Unknown mailbox operation: {operation!r}")

        return ports

    return mailbox_action_node


def _prune(cfg: mb.MailboxConfig, extra: dict) -> dict:
    """Delete mailboxes matching a name prefix. Dry-run unless told otherwise.

    🔴 THE PREFIX CARRIES NO OWNERSHIP. The conventional `e2e` prefix comes from
    a shared id generator used across several repos, so a prefix match sweeps up
    every mailbox any suite has ever created on that instance — including the
    mailboxes of permanent UAT fixtures. At least one of those belongs to the
    only funded, vendor-ready entity in the environment, and its own
    documentation describes it as irreplaceable.

    The damage would be irreversible in a way mailbox deletion usually isn't:
    nothing in the portal API deletes a user, so the account survives its
    mailbox with no channel for password reset or email confirmation —
    permanently half-usable and impossible to recreate.

    AN AGE FLOOR DOES NOT SAVE YOU, measured against the live instance
    2026-08-16: all 322 matching mailboxes were 3-7 days old and the funded
    fixture sat at the median. `older_than=3` would have deleted 307 of them
    including the fixture; `older_than=7` deletes nothing. There is no threshold
    that separates junk from treasure, so age is a secondary guard and the
    protect list is the one that actually discriminates.

    Hence, to delete anything: an explicit prefix, an explicit protect list, and
    confirm=True. And never from a lifecycle hook — a blind prefix match on a
    timer is how the funded fixture disappears at 3am.
    """
    prefix = str(extra.get("prefix") or "")
    dry_run = extra.get("dry_run", True)
    confirm = extra.get("confirm", False)
    protect = {str(p).strip() for p in (extra.get("protect") or []) if str(p).strip()}
    older_than_days = extra.get("older_than_days")
    limit = int(extra.get("limit", 100))

    if not prefix:
        raise mb.MailboxError(
            "prune_mailboxes needs an explicit `prefix`. There is deliberately no default: "
            "the conventional e2e prefix matches every mailbox any suite has ever created on "
            "the instance, including the permanent fixtures your team's inventory lists."
        )

    matched: list[dict] = []
    offset = 0
    while len(matched) < limit:
        page = mb.list_addresses(cfg, limit=50, offset=offset)
        if not page:
            break
        matched.extend(a for a in page if str(a.get("name", "")).startswith(prefix))
        offset += 50
    matched = matched[:limit]

    def _is_protected(row: dict) -> bool:
        name = str(row.get("name", ""))
        return any(p in name for p in protect)

    protected = [r for r in matched if _is_protected(r)]
    candidates = [r for r in matched if not _is_protected(r)]

    skipped_young = 0
    if older_than_days is not None:
        keep = []
        for row in candidates:
            age = _age_days(row.get("created_at", ""))
            if age is None or age > float(older_than_days):
                keep.append(row)
            else:
                skipped_young += 1
        candidates = keep

    deleted: list[int] = []
    refused: str | None = None
    if not dry_run:
        if not confirm:
            refused = "confirm=True is required to delete; nothing was removed"
        elif not protect:
            refused = (
                "a non-empty `protect` list is required to delete. The prefix cannot tell our "
                "disposable mailboxes from the permanent fixtures — reconcile against your "
                "team's permanent-fixture inventory and pass them here"
            )
        elif len(candidates) > PRUNE_MAX_DELETE:
            refused = (
                f"{len(candidates)} mailboxes matched, above the {PRUNE_MAX_DELETE} per-run "
                "ceiling; narrow the prefix or lower `limit`"
            )
        else:
            for row in candidates:
                try:
                    mb.delete_mailbox(cfg, row["id"])
                    deleted.append(row["id"])
                except mb.MailboxError:
                    logger.warning("prune: failed to delete mailbox id=%s", row.get("id"), exc_info=True)

    ports = _blank_ports()
    ports["result"] = {
        "dry_run": bool(dry_run),
        "prefix": prefix,
        "matched": len(matched),
        "protected": len(protected),
        "skipped_too_young": skipped_young,
        "would_delete": len(candidates),
        "deleted": len(deleted),
        "refused": refused,
        "names": [a.get("name") for a in candidates[:20]],
    }
    return ports


def _age_days(created_at: str) -> float | None:
    """Age from the service's own `created_at` ('2026-08-13 02:53:41', UTC, naive)."""
    from datetime import datetime, timezone

    try:
        stamp = datetime.fromisoformat(created_at.strip().replace("Z", "")).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400


# ---------------------------------------------------------------------------
# mailbox_parse — pure. No network, no credential.
# ---------------------------------------------------------------------------


@register("mailbox_parse")
def mailbox_parse_factory(node):
    """Return a LangChain tool that pulls tokens and links out of a raw message.

    Deliberately credential-free: parsing needs no secret, so an agent can be
    given this without also being given a key that reads every mailbox on the
    instance.
    """

    @tool
    def parse_email(raw_message: str, extract: str = "verify_token") -> str:
        """Extract a token or links from a raw RFC-822 email message.

        Args:
            raw_message: The full raw message, as returned by a mailbox node.
            extract: One of "verify_token", "reset_token", "urls", "decoded".

        Returns:
            The extracted token, the URLs one per line, or the decoded message.
        """
        try:
            if extract == "verify_token":
                return mb.extract_verify_email_token(raw_message)
            if extract == "reset_token":
                return mb.extract_reset_password_token(raw_message)
            if extract == "urls":
                return "\n".join(mb.extract_urls(raw_message)) or "(no URLs found)"
            if extract == "decoded":
                return mb.decode_quoted_printable(raw_message)
            return f"Unknown extract mode {extract!r} — use verify_token, reset_token, urls, or decoded."
        except mb.MailboxError as exc:
            return f"Error: {exc}"

    return parse_email
