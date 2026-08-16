"""Tests for the mailbox node components."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Force node_type_defs to load so NODE_TYPE_REGISTRY is populated
import schemas.node_type_defs  # noqa: F401
from components import COMPONENT_REGISTRY
from services.mailbox import Mail, Mailbox, MailboxError, MailboxNotFound


def _node(operation: str = "create_mailbox", credential_id: int | None = 1, **extra):
    cfg = SimpleNamespace(
        extra_config={"operation": operation, **extra},
        credential_id=credential_id,
    )
    return SimpleNamespace(component_config=cfg, node_id="mailbox_1", workflow_id=1)


def _build(node):
    return COMPONENT_REGISTRY["mailbox_action"](node)


CONFIG_PATCH = "components.mailbox._load_config"


class TestRegistration:
    def test_both_node_types_are_registered_everywhere(self):
        """The four-place checklist: factory, config class, schema literal, registry."""
        from typing import get_args

        from models.node import COMPONENT_TYPE_TO_CONFIG
        from schemas.node import ComponentTypeStr
        from schemas.node_types import NODE_TYPE_REGISTRY

        for name in ("mailbox_action", "mailbox_parse"):
            assert name in COMPONENT_REGISTRY, f"{name} has no component factory"
            assert name in COMPONENT_TYPE_TO_CONFIG, f"{name} has no polymorphic config"
            assert name in NODE_TYPE_REGISTRY, f"{name} is not in the node type registry"
            assert name in get_args(ComponentTypeStr), f"{name} is not an accepted API literal"

    def test_parse_node_is_not_executable(self):
        """It is a sub-component tool, not a flow node."""
        from schemas.node_types import NODE_TYPE_REGISTRY

        assert NODE_TYPE_REGISTRY["mailbox_parse"].executable is False


class TestCredentialLoading:
    def test_missing_credential_says_so(self):
        node = _node(credential_id=None)
        with pytest.raises(MailboxError, match="needs a mailbox credential"):
            _build(node)({})

    def test_secret_comes_from_the_encrypted_column_not_config(self):
        """base_url/domain live in plain JSON config; admin_auth must not."""
        from components.mailbox import _load_config

        cred = MagicMock()
        cred.tool_credential.config = {"base_url": "https://mail.invalid", "domain": "mail.invalid"}
        cred.tool_credential.secret = "the-admin-secret"
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = cred

        with patch("components.mailbox.SessionLocal", return_value=db):
            cfg = _load_config(1)

        assert cfg.admin_auth == "the-admin-secret"
        assert cfg.base_url == "https://mail.invalid"


class TestOperations:
    def test_create_mailbox_emits_address_id_and_jwt(self):
        box = Mailbox(address="tmpe2eabc@mail.invalid", address_id=7, jwt="scoped-token")
        with patch(CONFIG_PATCH), patch("components.mailbox.mb.create_mailbox", return_value=box):
            out = _build(_node("create_mailbox"))({})

        assert out["address"] == "tmpe2eabc@mail.invalid"
        assert out["address_id"] == "7"
        assert out["jwt"] == "scoped-token"

    def test_every_operation_emits_the_same_port_set(self):
        """A sparse shape is a trap: resolve_expressions returns the template
        text verbatim for an undefined variable, so a missing port travels on as
        the literal '{{ node.port }}'."""
        box = Mailbox(address="a@mail.invalid", address_id=1, jwt="j")
        expected = {"result", "address", "address_id", "jwt", "token", "mails"}

        with patch(CONFIG_PATCH), patch("components.mailbox.mb.create_mailbox", return_value=box):
            create_out = _build(_node("create_mailbox"))({})
        with patch(CONFIG_PATCH), patch("components.mailbox.mb.list_mails", return_value=[]):
            list_out = _build(_node("list_mails", address="a@mail.invalid"))({})

        assert set(create_out) == expected
        assert set(list_out) == expected

    def test_verification_email_returns_the_token(self):
        mail = Mail(id=1, message_id="m", source="s", address="a@mail.invalid",
                    raw="link https://host.example/verify-email/TOKEN123", created_at="now")
        with patch(CONFIG_PATCH), patch("components.mailbox.mb.wait_for_mail", return_value=mail):
            out = _build(_node("wait_for_verification_email", address="a@mail.invalid"))({})

        assert out["token"] == "TOKEN123"
        assert out["mails"][0]["raw"] == mail.raw

    def test_wait_passes_the_scoped_jwt_through(self):
        """The polling loop must be able to run without the admin secret."""
        mail = Mail(id=1, message_id="m", source="s", address="a", raw="x", created_at="now")
        with patch(CONFIG_PATCH), patch("components.mailbox.mb.wait_for_mail", return_value=mail) as w:
            _build(_node("wait_for_mail", address="a@mail.invalid", jwt="scoped"))({})
        assert w.call_args.kwargs["jwt"] == "scoped"

    def test_failure_codes_survive_as_exception_types(self):
        """The orchestrator uses type(exc).__name__ as error_code, so the
        three-way distinction reaches the canvas for free."""
        with patch(CONFIG_PATCH), \
                patch("components.mailbox.mb.wait_for_mail", side_effect=MailboxNotFound("nothing")):
            with pytest.raises(MailboxNotFound):
                _build(_node("wait_for_mail", address="a@mail.invalid"))({})

    def test_unknown_operation_is_rejected(self):
        with patch(CONFIG_PATCH):
            with pytest.raises(MailboxError, match="Unknown mailbox operation"):
                _build(_node("teleport"))({})


class TestPrune:
    def _addresses(self):
        return [
            {"id": 1, "name": "tmpe2eaaa", "created_at": "old"},
            {"id": 2, "name": "tmpsomeoneelse", "created_at": "old"},
            {"id": 3, "name": "tmpe2ebbb", "created_at": "old"},
        ]

    def test_dry_run_is_the_default_and_deletes_nothing(self):
        """This deletes real mailboxes on a shared instance, and the prefix is
        all that separates ours from someone else's."""
        with patch(CONFIG_PATCH), \
                patch("components.mailbox.mb.list_addresses", side_effect=[self._addresses(), []]), \
                patch("components.mailbox.mb.delete_mailbox") as delete:
            out = _build(_node("prune_mailboxes"))({})

        assert out["result"]["dry_run"] is True
        assert out["result"]["matched"] == 2
        assert out["result"]["deleted"] == 0
        delete.assert_not_called()

    def test_only_the_prefix_matches(self):
        with patch(CONFIG_PATCH), \
                patch("components.mailbox.mb.list_addresses", side_effect=[self._addresses(), []]), \
                patch("components.mailbox.mb.delete_mailbox") as delete:
            out = _build(_node("prune_mailboxes", dry_run=False))({})

        assert out["result"]["deleted"] == 2
        assert sorted(c.args[1] for c in delete.call_args_list) == [1, 3]

    def test_a_failed_delete_does_not_abort_the_sweep(self):
        with patch(CONFIG_PATCH), \
                patch("components.mailbox.mb.list_addresses", side_effect=[self._addresses(), []]), \
                patch("components.mailbox.mb.delete_mailbox",
                      side_effect=[MailboxError("gone"), None]):
            out = _build(_node("prune_mailboxes", dry_run=False))({})

        assert out["result"]["matched"] == 2
        assert out["result"]["deleted"] == 1


class TestParseTool:
    def _tool(self):
        return COMPONENT_REGISTRY["mailbox_parse"](_node(credential_id=None))

    def test_extracts_a_verify_token(self):
        raw = "click https://host.example/verify-email/ABC123XYZ please"
        assert self._tool().invoke({"raw_message": raw, "extract": "verify_token"}) == "ABC123XYZ"

    def test_lists_urls(self):
        raw = "one https://a.example/xxxxxxxxxx two https://b.example/yyyyyyyyyy"
        out = self._tool().invoke({"raw_message": raw, "extract": "urls"})
        assert out.splitlines() == ["https://a.example/xxxxxxxxxx", "https://b.example/yyyyyyyyyy"]

    def test_returns_a_readable_error_rather_than_raising(self):
        """An agent gets a message it can act on, not a stack trace."""
        out = self._tool().invoke({"raw_message": "nothing here", "extract": "verify_token"})
        assert out.startswith("Error:")

    def test_needs_no_credential(self):
        """The whole point of the split — no secret reaches this node."""
        tool = self._tool()
        assert tool.invoke({"raw_message": "https://h.example/verify-email/T0KEN12345"}) == "T0KEN12345"
