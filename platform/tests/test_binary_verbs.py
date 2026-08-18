"""The shared verb surface, and design-time checks on binary nodes.

Schemas here are invented, like the catalogs in test_binary_catalogs.py: the
real ones describe one organisation's operations and are gitignored.
"""

import json

import pytest

from schemas.binary_verbs import VERBS, auth_spec, build_argv, compose_verbs, verbs_for

# What a binary might declare its `auth login` credential to be. The contract
# keeps `credential` opaque precisely because this varies: one binary wants a
# username and password plus a tenant, another a bare token.
TENANT_LOGIN = {
    "type": "object",
    "required": ["username", "password", "tenant"],
    "properties": {
        "username": {"type": "string"},
        "password": {"type": "string", "secret": True},
        "tenant": {"type": "string", "description": "Which tenant to log into."},
    },
}

TOKEN_LOGIN = {
    "type": "object",
    "required": ["api_token"],
    "properties": {"api_token": {"type": "string", "secret": True}},
}

WIDE_ENV = {
    "type": "object",
    "required": ["url", "region"],
    "properties": {
        "url": {"type": "string"},
        "region": {"type": "string"},
        "insecure": {"type": "boolean"},
    },
}


class TestArgv:
    def test_global_flags_precede_the_verb(self):
        """`--env` and `--session` are global flags, not arguments to `auth login`."""
        argv, _ = build_argv("auth.login", {"env": "uat1", "session": "a1",
                                            "username": "u", "password": "p"})
        assert argv == ["--env", "uat1", "--session", "a1", "auth", "login"]

    def test_credentials_never_reach_argv(self):
        """A process's command line is readable by other processes for the life
        of the call, which is why the binaries refuse credential-shaped flags."""
        argv, credential = build_argv("auth.login", {
            "env": "uat1", "session": "a1", "username": "u", "password": "hunter2"})
        assert "hunter2" not in " ".join(argv)
        assert credential == {"username": "u", "password": "hunter2"}

    def test_an_absent_totp_seed_is_omitted_rather_than_sent_empty(self):
        _, credential = build_argv("auth.login", {
            "env": "e", "session": "s", "username": "u", "password": "p", "totp_seed": ""})
        assert "totp_seed" not in credential

    def test_positionals_and_flags_follow_the_verb(self):
        argv, _ = build_argv("env.add", {"name": "uat1", "url": "https://x/admin", "kind": "uat"})
        assert argv == ["env", "add", "uat1", "--url", "https://x/admin", "--kind", "uat"]

    def test_a_listing_verb_takes_nothing(self):
        argv, credential = build_argv("auth.sessionList", {"session": "ignored"})
        assert argv == ["auth", "session", "list"]
        assert credential == {}

    def test_remove_passes_the_handle_positionally(self):
        argv, _ = build_argv("auth.sessionRemove", {"session": "a1"})
        assert argv == ["auth", "session", "remove", "a1"]


class TestComposedLogin:
    """`auth login`'s form is composed, not guessed.

    The fixed parts (`env`, `session`) are protocol-level; the credential
    fields are the binary's own to declare. A hardcoded list here was more
    restrictive than the contract it implements — the contract keeps
    `credential` opaque deliberately — and a host that guesses renders a form
    with no field for the thing the binary requires.
    """

    def test_a_declared_extra_field_appears_in_the_form(self):
        params = compose_verbs(TENANT_LOGIN)["auth.login"]["params"]
        assert "tenant" in params["properties"]
        assert params["required"] == ["env", "session", "username", "password", "tenant"]

    def test_a_declared_extra_field_travels_on_stdin_not_argv(self):
        verbs = compose_verbs(TENANT_LOGIN)
        argv, credential = build_argv("auth.login", {
            "env": "e1", "session": "a1",
            "username": "u", "password": "hunter2", "tenant": "t-42",
        }, verbs)
        assert credential == {"username": "u", "password": "hunter2", "tenant": "t-42"}
        joined = " ".join(argv)
        assert "hunter2" not in joined and "t-42" not in joined
        assert argv == ["--env", "e1", "--session", "a1", "auth", "login"]

    def test_a_binary_may_replace_the_fields_wholesale(self):
        """A bare-token binary asks for a token, not for a username it ignores."""
        entry = compose_verbs(TOKEN_LOGIN)["auth.login"]
        assert entry["credential"] == ["api_token"]
        assert "username" not in entry["params"]["properties"]
        assert entry["params"]["required"] == ["env", "session", "api_token"]

    def test_a_declared_secret_stays_secret(self):
        params = compose_verbs(TOKEN_LOGIN)["auth.login"]["params"]
        assert params["properties"]["api_token"]["secret"] is True

    def test_the_fixed_parts_survive_composition(self):
        """`env` keeps its picker and `session` stays free text: those are
        protocol-level, not the binary's to redefine."""
        props = compose_verbs(TENANT_LOGIN)["auth.login"]["params"]["properties"]
        assert props["env"]["picker"] == "environments"
        assert "picker" not in props["session"]

    def test_a_binary_declaring_nothing_keeps_todays_fields(self):
        """The regression guard: neither installed binary declares a
        credential_schema yet, so this fallback is what actually runs."""
        entry = compose_verbs()["auth.login"]
        assert entry == VERBS["auth.login"]
        assert entry["credential"] == ["username", "password", "totp_seed"]
        assert entry["params"]["properties"]["password"]["secret"] is True

    def test_a_colliding_declared_field_is_skipped(self):
        declared = {
            "type": "object",
            "required": ["session", "tenant"],
            "properties": {"session": {"type": "string"}, "tenant": {"type": "string"}},
        }
        entry = compose_verbs(declared)["auth.login"]
        assert entry["credential"] == ["tenant"]
        # The protocol's own `session` definition survives, not the declared one.
        assert entry["params"]["properties"]["session"]["title"] == "Session handle"
        assert entry["params"]["required"] == ["env", "session", "tenant"]

    def test_a_schema_declaring_only_platform_keys_falls_back(self):
        declared = {"type": "object", "properties": {"env": {}, "session": {}}}
        assert compose_verbs(declared)["auth.login"] == VERBS["auth.login"]

    def test_the_other_verbs_pass_through_untouched(self):
        composed = compose_verbs(TOKEN_LOGIN, WIDE_ENV)
        assert composed["auth.refresh"] == VERBS["auth.refresh"]
        assert sorted(composed) == sorted(VERBS)


class TestComposedEnvAdd:
    """Same defect one field over: the catalog has always carried a per-binary
    `env_schema`, required at registration, and the form ignored it."""

    def test_declared_fields_become_flags_after_the_positional(self):
        verbs = compose_verbs(env_schema=WIDE_ENV)
        argv, credential = build_argv("env.add", {
            "name": "uat1", "url": "https://x", "region": "ap",
        }, verbs)
        assert argv == ["env", "add", "uat1", "--url", "https://x", "--region", "ap"]
        assert credential == {}

    def test_required_composes_from_the_declaration(self):
        params = compose_verbs(env_schema=WIDE_ENV)["env.add"]["params"]
        assert params["required"] == ["name", "url", "region"]
        assert set(params["properties"]) == {"name", "url", "region", "insecure"}

    def test_a_binary_declaring_nothing_keeps_todays_fields(self):
        entry = compose_verbs()["env.add"]
        assert entry == VERBS["env.add"]
        assert entry["flags"] == {"url": "--url", "kind": "--kind"}

    def test_the_positional_name_is_not_the_binarys_to_redeclare(self):
        declared = {"type": "object", "properties": {"name": {"enum": ["x"]}, "url": {}}}
        props = compose_verbs(env_schema=declared)["env.add"]["params"]["properties"]
        assert props["name"] == VERBS["env.add"]["params"]["properties"]["name"]


class TestVerbsForBinary:
    """Composition keyed by the pinned catalog file, like every other catalog
    question — per call, so a registration needs no restart."""

    @staticmethod
    def _write(directory, **extra):
        doc = {"protocol": 1, "binary": "demo-bin", "operations": [], **extra}
        (directory / "demo-bin.json").write_text(json.dumps(doc))

    def test_a_declaring_catalog_drives_the_table(self, tmp_path):
        self._write(tmp_path, credential_schema=TOKEN_LOGIN, env_schema=WIDE_ENV)
        verbs = verbs_for("demo-bin", tmp_path)
        assert verbs["auth.login"]["credential"] == ["api_token"]
        assert "--region" == verbs["env.add"]["flags"]["region"]

    def test_an_unresolvable_binary_gets_the_fallback_table(self, tmp_path):
        assert verbs_for("ghost-bin", tmp_path) == compose_verbs()


class TestSpec:
    def test_one_static_type_serves_every_plugin(self):
        """The verb surface is fixed by the protocol, so it does not come from a
        catalog: a single `binary_auth` type covers a plugin nobody has written
        yet, and which binary a node manages is node data, not part of the type."""
        spec = auth_spec()
        assert spec.component_type == "binary_auth"
        assert "x-binary" not in spec.config_schema
        assert sorted(spec.config_schema["x-operations"]) == sorted(VERBS)

    def test_the_binary_is_declared_as_config(self):
        schema = auth_spec().config_schema
        assert schema["properties"]["binary"]["title"] == "Binary"
        assert "binary" in schema["required"]

    def test_the_password_is_marked_secret(self):
        params = auth_spec().config_schema["x-operations"]["auth.login"]["params"]
        assert params["properties"]["password"]["secret"] is True

    def test_verbs_do_not_ask_for_a_session_picker(self):
        """On these nodes `session` is a handle being WRITTEN, not one chosen."""
        ops = auth_spec().config_schema["x-operations"]
        assert all(op["session_required"] is False for op in ops.values())


class TestDesignTimeChecks:
    """Catching at build time what would otherwise fail against a real backend."""

    @staticmethod
    def _node(**extra):
        from types import SimpleNamespace
        return SimpleNamespace(node_id="n1", component_type="demo_bin_things",
                               component_config=SimpleNamespace(extra_config=extra))

    @staticmethod
    def _spec(session_required=True, required=("thing_id",)):
        from schemas.node_types import NodeTypeSpec
        return NodeTypeSpec(component_type="demo_bin_things", display_name="d", config_schema={
            "x-binary": "demo-bin",
            "x-operations": {"things.doThing": {
                "summary": "", "session_required": session_required,
                "params": {"type": "object", "required": list(required),
                           "properties": {k: {"type": "string"} for k in required}},
            }},
        })

    def test_no_operation_selected(self):
        from validation.edges import _binary_operation_errors
        assert "no operation selected" in _binary_operation_errors(self._node(), self._spec())[0]

    def test_an_operation_the_binary_does_not_offer(self):
        from validation.edges import _binary_operation_errors
        errors = _binary_operation_errors(self._node(operation="things.nope"), self._spec())
        assert "does not offer" in errors[0]

    def test_a_required_identity_that_is_not_set(self):
        from validation.edges import _binary_operation_errors
        errors = _binary_operation_errors(
            self._node(operation="things.doThing", thing_id="t"), self._spec())
        assert any("requires an identity" in e for e in errors)

    def test_a_missing_required_parameter(self):
        from validation.edges import _binary_operation_errors
        errors = _binary_operation_errors(
            self._node(operation="things.doThing", session="s"), self._spec())
        assert any("missing required parameter" in e for e in errors)

    def test_a_complete_node_passes(self):
        from validation.edges import _binary_operation_errors
        assert _binary_operation_errors(
            self._node(operation="things.doThing", session="s", thing_id="t"), self._spec()) == []

    def test_a_node_type_without_operations_is_left_alone(self):
        """Every built-in node type goes through this path too."""
        from schemas.node_types import NodeTypeSpec
        from validation.edges import _binary_operation_errors
        plain = NodeTypeSpec(component_type="agent", display_name="Agent")
        assert _binary_operation_errors(self._node(), plain) == []


class TestDesignTimeComposition:
    """Validation demands what the node's binary declares, composed exactly as
    the component composes it at run time — not the fallback fields a declaring
    binary never asked for."""

    @staticmethod
    def _node(**extra):
        from types import SimpleNamespace
        return SimpleNamespace(node_id="n1", component_type="binary_auth",
                               component_config=SimpleNamespace(extra_config=extra))

    @pytest.fixture
    def token_bin(self, tmp_path, monkeypatch):
        import schemas.binary_catalogs as binary_catalogs
        (tmp_path / "token-bin.json").write_text(json.dumps(
            {"protocol": 1, "binary": "token-bin", "operations": [],
             "credential_schema": TOKEN_LOGIN}))
        monkeypatch.setattr(binary_catalogs, "CATALOG_DIR", tmp_path)

    def test_a_declared_required_field_is_demanded(self, token_bin):
        from validation.edges import _binary_operation_errors
        errors = _binary_operation_errors(
            self._node(binary="token-bin", operation="auth.login", env="e", session="s"),
            auth_spec())
        assert any("api_token" in e for e in errors)

    def test_the_fallback_fields_are_not_demanded_of_a_declaring_binary(self, token_bin):
        """The static spec would demand username and password here — fields
        this binary's login has no use for."""
        from validation.edges import _binary_operation_errors
        assert _binary_operation_errors(
            self._node(binary="token-bin", operation="auth.login",
                       env="e", session="s", api_token="t"),
            auth_spec()) == []
