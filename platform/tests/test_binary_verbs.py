"""The shared verb surface, and design-time checks on binary nodes."""

import pytest

from schemas.binary_verbs import VERBS, auth_spec, build_argv


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
