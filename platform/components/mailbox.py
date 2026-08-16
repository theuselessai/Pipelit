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

DEFAULT_PRUNE_PREFIX = "tmpe2e"
"""Mailboxes are created with an `e2e` prefix and the service prepends its own
`tmp`, so the stored name starts `tmpe2e`. 322 of the 353 addresses on the
instance matched this when the node was written, none of them cleaned up."""


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
    """Delete mailboxes matching a name prefix, oldest first.

    Dry-run by default: this deletes real mailboxes on a shared instance, and the
    prefix is the only thing standing between "our disposable accounts" and
    someone else's. `matched` is always reported so a dry run tells you exactly
    what a real run would remove.
    """
    prefix = extra.get("prefix", DEFAULT_PRUNE_PREFIX)
    dry_run = extra.get("dry_run", True)
    limit = int(extra.get("limit", 100))

    matched: list[dict] = []
    offset = 0
    while len(matched) < limit:
        page = mb.list_addresses(cfg, limit=50, offset=offset)
        if not page:
            break
        matched.extend(a for a in page if str(a.get("name", "")).startswith(prefix))
        offset += 50
    matched = matched[:limit]

    deleted = []
    if not dry_run:
        for row in matched:
            try:
                mb.delete_mailbox(cfg, row["id"])
                deleted.append(row["id"])
            except mb.MailboxError:
                logger.warning("prune: failed to delete mailbox id=%s", row.get("id"), exc_info=True)

    result = {
        "dry_run": bool(dry_run),
        "prefix": prefix,
        "matched": len(matched),
        "deleted": len(deleted),
        "names": [a.get("name") for a in matched[:20]],
    }
    ports = _blank_ports()
    ports["result"] = result
    return ports


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
