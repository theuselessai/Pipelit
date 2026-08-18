"""Tests for the mailbox node components."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Force node_type_defs to load so NODE_TYPE_REGISTRY is populated
import schemas.node_type_defs  # noqa: F401
from components import COMPONENT_REGISTRY
from services.mailbox import Mail, Mailbox, MailboxError, MailboxNotFound


@pytest.fixture
def app(db):
    from main import app as _app
    from database import get_db

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def auth_client(app, api_key):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


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


class TestCredentialPersistsThroughTheAPI:
    """Selecting a credential in the UI must actually save it.

    `credential_id` lives on the shared component_configs table but was written
    only for triggers, so a mailbox node's credential was dropped on PATCH: 200
    back, extra_config persisted, credential silently gone. Nothing in the logs,
    and from the UI it just looked like Save not working.
    """

    def test_credential_id_survives_a_patch(self, auth_client, workflow, db):
        from models.credential import BaseCredential, ToolCredential

        cred = BaseCredential(user_profile_id=1, name="mailbox", credential_type="tool")
        db.add(cred)
        db.flush()
        db.add(ToolCredential(base_credentials_id=cred.id, tool_type="mailbox",
                              config={"base_url": "https://mail.invalid", "domain": "mail.invalid"},
                              secret="s"))
        db.commit()

        created = auth_client.post(
            f"/api/v1/workflows/{workflow.slug}/nodes/",
            json={"component_type": "mailbox_action", "config": {}},
        )
        assert created.status_code == 201
        node_id = created.json()["node_id"]

        resp = auth_client.patch(
            f"/api/v1/workflows/{workflow.slug}/nodes/{node_id}/",
            json={"config": {"credential_id": cred.id,
                             "extra_config": {"operation": "create_mailbox"}}},
        )

        assert resp.status_code == 200
        assert resp.json()["config"]["credential_id"] == cred.id, "credential was dropped on save"
        assert resp.json()["config"]["extra_config"]["operation"] == "create_mailbox"

    def test_a_non_credentialed_type_still_cannot_set_one(self):
        """The gate stays shut for everything that has not opted in — the panel
        posts the whole config object on every save."""
        from api.nodes import CREDENTIALED_NODE_TYPES

        assert "mailbox_action" in CREDENTIALED_NODE_TYPES
        assert "code" not in CREDENTIALED_NODE_TYPES
        assert "agent" not in CREDENTIALED_NODE_TYPES


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
    """Prune is the one destructive operation, and the prefix it matches on is
    NOT ours — the conventional `e2e` prefix comes from a shared id generator
    used across several repos. A permanent, funded, vendor-ready UAT fixture
    matches it too, and nothing in the upstream API deletes a user, so removing
    that mailbox strands an account that cannot be recreated.

    The address below is a stand-in; the real one lives in the fixture inventory
    and deliberately does not appear in this repo.
    """

    FUNDED_FIXTURE = "tmpe2ekeepme0000@mail.invalid"

    def _addresses(self):
        return [
            {"id": 1, "name": "tmpe2eaaa@mail.invalid", "created_at": "2020-01-01 00:00:00"},
            {"id": 2, "name": "tmpsomeoneelse@mail.invalid", "created_at": "2020-01-01 00:00:00"},
            {"id": 3, "name": self.FUNDED_FIXTURE, "created_at": "2020-01-01 00:00:00"},
        ]

    def _run(self, **extra):
        with patch(CONFIG_PATCH), \
                patch("components.mailbox.mb.list_addresses", side_effect=[self._addresses(), []]), \
                patch("components.mailbox.mb.delete_mailbox") as delete:
            out = _build(_node("prune_mailboxes", **extra))({})
        return out["result"], delete

    def test_no_default_prefix(self):
        """A default of 'tmpe2e' would sweep up every suite's mailboxes."""
        with patch(CONFIG_PATCH):
            with pytest.raises(MailboxError, match="explicit `prefix`"):
                _build(_node("prune_mailboxes"))({})

    def test_dry_run_is_the_default(self):
        result, delete = self._run(prefix="tmpe2e")
        assert result["dry_run"] is True
        assert result["deleted"] == 0
        delete.assert_not_called()

    def test_delete_refuses_without_confirm(self):
        result, delete = self._run(prefix="tmpe2e", dry_run=False, protect=[self.FUNDED_FIXTURE])
        assert "confirm=True is required" in result["refused"]
        delete.assert_not_called()

    def test_delete_refuses_without_a_protect_list(self):
        """The prefix cannot distinguish disposable mailboxes from fixtures, so
        whoever deletes must have reconciled against the handover register."""
        result, delete = self._run(prefix="tmpe2e", dry_run=False, confirm=True)
        assert "protect" in result["refused"]
        delete.assert_not_called()

    def test_protected_entries_are_excluded(self):
        result, delete = self._run(
            prefix="tmpe2e", dry_run=False, confirm=True, protect=[self.FUNDED_FIXTURE],
        )
        assert result["protected"] == 1
        assert result["deleted"] == 1
        assert [c.args[1] for c in delete.call_args_list] == [1], "only the unprotected mailbox"

    def test_the_funded_fixture_is_never_deleted_when_protected(self):
        _, delete = self._run(
            prefix="tmpe2e", dry_run=False, confirm=True, protect=[self.FUNDED_FIXTURE],
        )
        deleted_ids = [c.args[1] for c in delete.call_args_list]
        assert 3 not in deleted_ids, "deleted the irreplaceable funded fixture"

    def test_age_floor_skips_young_mailboxes(self):
        """Secondary guard only: measured against the live instance, every
        matching mailbox was 3-7 days old with the fixture at the median, so no
        threshold separates junk from treasure."""
        with patch(CONFIG_PATCH), \
                patch("components.mailbox.mb.list_addresses",
                      side_effect=[[{"id": 9, "name": "tmpe2enew@mail.invalid",
                                     "created_at": "2999-01-01 00:00:00"}], []]), \
                patch("components.mailbox.mb.delete_mailbox") as delete:
            out = _build(_node("prune_mailboxes", prefix="tmpe2e", dry_run=False,
                               confirm=True, protect=["x"], older_than_days=30))({})

        assert out["result"]["skipped_too_young"] == 1
        delete.assert_not_called()

    def test_refuses_a_sweep_above_the_ceiling(self):
        many = [{"id": i, "name": f"tmpe2e{i}@mail.invalid", "created_at": "2020-01-01 00:00:00"}
                for i in range(60)]
        with patch(CONFIG_PATCH), \
                patch("components.mailbox.mb.list_addresses", side_effect=[many, []]), \
                patch("components.mailbox.mb.delete_mailbox") as delete:
            out = _build(_node("prune_mailboxes", prefix="tmpe2e", dry_run=False,
                               confirm=True, protect=["nothing"]))({})

        assert "ceiling" in out["result"]["refused"]
        delete.assert_not_called()

    def test_a_failed_delete_does_not_abort_the_sweep(self):
        with patch(CONFIG_PATCH), \
                patch("components.mailbox.mb.list_addresses", side_effect=[self._addresses(), []]), \
                patch("components.mailbox.mb.delete_mailbox",
                      side_effect=[MailboxError("gone"), None]):
            out = _build(_node("prune_mailboxes", prefix="tmpe2e", dry_run=False,
                               confirm=True, protect=["nothing-matches"]))({})

        assert out["result"]["would_delete"] == 2
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
