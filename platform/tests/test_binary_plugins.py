"""Plugin integrity, and executing an operation through one.

The fake plugin here is a real executable emitting canned envelopes, so the
subprocess path is exercised rather than mocked. A live binary cannot be asked
for an undischarged proof or a malformed envelope on demand — provoking those
against a real backend means causing a real silent refusal — so the failure paths
have to be driven by a fixture. The live run proves the happy path; this proves
everything else.
"""

import json
import subprocess

import pytest

from components.binary_op import binary_op_factory
from schemas.binary_catalogs import load_specs
from schemas.node_types import NODE_TYPE_REGISTRY
from services import plugins
from services.plugins import (
    PluginError,
    Registration,
    resolve,
    tree_checksum,
    verified_plugin,
)

FAKE_BIN = '''#!/usr/bin/env python3
"""A plugin that prints whatever it was told to print.

Its scratch files live OUTSIDE the plugin directory. Writing them inside would
move the tree checksum on every call, and the plugin would refuse to run itself
— which is the integrity check working, and a useful accident to have hit.
"""
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
io = here.parent / "io"
if sys.argv[1:] and sys.argv[-1] == "catalog":
    print(json.dumps({"ok": True, "data": json.loads((here / "catalog.json").read_text()),
                      "proof": None, "slot_patch": None, "error": None}))
    raise SystemExit(0)
(io / "last_argv.json").write_text(json.dumps(sys.argv[1:]))
(io / "last_stdin.json").write_text(sys.stdin.read())
response = (io / "response.json").read_text()
code = int((io / "exit_code").read_text().strip()) if (io / "exit_code").exists() else 0
sys.stdout.write(response)
raise SystemExit(code)
'''


def _catalog(binary="fake-bin"):
    return {
        "protocol": 1,
        "binary": binary,
        "version": "1.0.0",
        "generated_from": {"tree": "example/fake", "commit": "abc1234", "dirty": False},
        "catalog_hash": "sha256:" + "1" * 64,
        "env_schema": {"type": "object"},
        "operations": [{
            "id": "things.doThing",
            "domain": "things",
            "summary": "Do the thing.",
            "session": {"required": True},
            "params": {"type": "object", "properties": {"n": {"type": "string"}},
                       "additionalProperties": False},
            "outputs": [
                {"name": "thing_id", "type": "string", "description": "id"},
                {"name": "extra", "type": "string", "description": "not always emitted"},
            ],
            "timeout_default_s": 5,
        }],
    }


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    """An installed, registered fake plugin."""
    root = tmp_path / "plugins"
    directory = root / "fake-bin"
    directory.mkdir(parents=True)
    (directory / "bin.py").write_text(FAKE_BIN)
    (directory / "plugin.json").write_text(json.dumps({"exec": ["python3", "bin.py"]}))
    (directory / "catalog.json").write_text(json.dumps(_catalog()))

    (root / "io").mkdir()
    registrations = tmp_path / "registrations"
    registrations.mkdir()
    monkeypatch.setattr(plugins, "PLUGIN_DIR", root)
    monkeypatch.setattr(plugins, "REGISTRATION_DIR", registrations)

    p = resolve("fake-bin", root)
    plugins.write_registration(Registration(
        binary="fake-bin", plugin="fake-bin", argv=p.argv,
        checksum=tree_checksum(directory), fingerprint=plugins.tree_fingerprint(directory),
        catalog_hash="sha256:" + "1" * 64, registered_at="2026-08-18T00:00:00+00:00",
    ))

    catalogs = tmp_path / "catalogs"
    catalogs.mkdir()
    (catalogs / "fake-bin.json").write_text(json.dumps(_catalog()))
    before = dict(NODE_TYPE_REGISTRY)
    load_specs(catalogs)
    yield directory
    NODE_TYPE_REGISTRY.clear()
    NODE_TYPE_REGISTRY.update(before)


def io_dir(plugin_dir):
    return plugin_dir.parent / "io"


def respond(directory, envelope, exit_code=0):
    io = io_dir(directory)
    (io / "response.json").write_text(json.dumps(envelope))
    (io / "exit_code").write_text(str(exit_code))


def ok(data=None, proof=None, slot_patch=None):
    return {"ok": True, "data": data or {}, "proof": proof,
            "slot_patch": slot_patch, "error": None}


def failed(code, message="it failed", slot_patch=None):
    return {"ok": False, "data": None, "proof": None, "slot_patch": slot_patch,
            "error": {"code": code, "message": message, "retryable": False, "details": {}}}


def node(**extra):
    from types import SimpleNamespace
    extra.setdefault("operation", "things.doThing")
    return SimpleNamespace(
        component_type="fake_bin_things",
        component_config=SimpleNamespace(extra_config=extra, credential_id=None),
    )


def run(directory, **extra):
    return binary_op_factory(node(**extra))({})


class TestIntegrity:
    def test_a_changed_plugin_is_refused(self, plugin):
        """Conformance is checked once, so the verdict must be bound to the code."""
        (plugin / "bin.py").write_text(FAKE_BIN + "\n# changed\n")
        with pytest.raises(PluginError, match="has changed since it was registered"):
            verified_plugin("fake-bin", plugin.parent)

    def test_an_unchanged_plugin_is_accepted(self, plugin):
        assert verified_plugin("fake-bin", plugin.parent)[0].name == "fake-bin"

    def test_a_deleted_file_moves_the_checksum(self, plugin):
        """Hashing paths as well as contents is what makes a deletion visible."""
        before = tree_checksum(plugin)
        (plugin / "catalog.json").unlink()
        assert tree_checksum(plugin) != before

    def test_dev_mode_skips_verification(self, plugin):
        plugins.write_registration(Registration(
            binary="fake-bin", plugin="fake-bin", argv=["python3", "bin.py"],
            checksum="sha256:" + "0" * 64, fingerprint="fp:stale",
            catalog_hash="x", registered_at="2026-08-18T00:00:00+00:00", dev_mode=True,
        ))
        assert verified_plugin("fake-bin", plugin.parent)[1].dev_mode is True

    def test_a_name_cannot_escape_the_plugins_directory(self, plugin):
        """The name comes from node config, so it is caller-controlled."""
        for name in ("../etc", "a/b", "..", ""):
            with pytest.raises(PluginError):
                resolve(name, plugin.parent)

    def test_a_plugin_without_a_manifest_is_not_a_plugin(self, tmp_path):
        (tmp_path / "bare").mkdir()
        with pytest.raises(PluginError, match="no plugin.json"):
            resolve("bare", tmp_path)


class TestInvocation:
    def test_success_fills_declared_ports(self, plugin):
        respond(plugin, ok({"thing_id": "t-1"}))
        assert run(plugin, session="s1") == {"thing_id": "t-1", "extra": None}

    def test_a_port_the_operation_did_not_emit_is_none_not_absent(self, plugin):
        """Absent becomes the literal '{{ node.extra }}' downstream."""
        respond(plugin, ok({"thing_id": "t-1"}))
        assert "extra" in run(plugin, session="s1")

    def test_the_session_is_passed_and_env_is_not(self, plugin):
        """--env binds an environment at login; alongside a session it would make
        'this identity, that environment' expressible, and binaries refuse it."""
        respond(plugin, ok({"thing_id": "t"}))
        run(plugin, session="s1", env="uat1")
        argv = json.loads((io_dir(plugin) / "last_argv.json").read_text())
        assert argv == ["--session", "s1", "call", "things.doThing"]

    def test_only_declared_params_are_sent(self, plugin):
        respond(plugin, ok({"thing_id": "t"}))
        run(plugin, session="s1", n="value", not_a_param="ignored")
        assert json.loads((io_dir(plugin) / "last_stdin.json").read_text()) == {"params": {"n": "value"}}

    def test_a_failure_surfaces_under_the_binarys_own_code(self, plugin):
        """So a caller can branch on it rather than string-matching a message."""
        respond(plugin, failed("WRITE_NOT_REFLECTED"), exit_code=6)
        with pytest.raises(Exception) as exc:
            run(plugin, session="s1")
        assert type(exc.value).__name__ == "WRITE_NOT_REFLECTED"

    def test_an_undischarged_proof_is_a_failure_not_a_flag(self, plugin):
        respond(plugin, ok({"thing_id": "t"}, proof={
            "discharged": False, "via": "readBack", "detail": "the row did not change"}))
        with pytest.raises(Exception) as exc:
            run(plugin, session="s1")
        assert type(exc.value).__name__ == "PROOF_NOT_DISCHARGED"
        assert "the row did not change" in str(exc.value)

    def test_a_failure_carrying_a_slot_patch_says_the_identity_may_be_stale(self, plugin):
        """The recovery case: the operation ran and its state could not be written."""
        respond(plugin, failed("STORE_UNAVAILABLE", slot_patch={"session": {"evicted": True}}),
                exit_code=5)
        with pytest.raises(Exception, match="stored identity may be stale"):
            run(plugin, session="s1")

    def test_output_that_is_not_one_json_object_fails(self, plugin):
        (io_dir(plugin) / "response.json").write_text('{"ok": true}\nchatty log line\n')
        (io_dir(plugin) / "exit_code").write_text("0")
        with pytest.raises(Exception) as exc:
            run(plugin, session="s1")
        assert type(exc.value).__name__ == "MALFORMED_ENVELOPE"

    def test_a_missing_session_is_caught_before_spawning(self, plugin):
        respond(plugin, ok({"thing_id": "t"}))
        with pytest.raises(Exception) as exc:
            run(plugin)
        assert type(exc.value).__name__ == "MISSING_SESSION"
        assert not (io_dir(plugin) / "last_argv.json").exists()

    def test_an_unknown_operation_is_refused(self, plugin):
        respond(plugin, ok())
        with pytest.raises(Exception) as exc:
            run(plugin, session="s1", operation="things.nope")
        assert type(exc.value).__name__ == "UNKNOWN_OPERATION"

    def test_a_hanging_plugin_is_killed_and_reported_as_unknown(self, plugin, monkeypatch):
        respond(plugin, ok())

        def hang(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="x", timeout=1)

        monkeypatch.setattr(subprocess, "run", hang)
        with pytest.raises(Exception) as exc:
            run(plugin, session="s1")
        assert type(exc.value).__name__ == "TIMEOUT"
        assert "unknown" in str(exc.value)


class TestIdentityNode:
    """The verb surface as a node — one component serves every plugin."""

    @staticmethod
    def _run(op, **cfg):
        from types import SimpleNamespace

        from components.binary_auth import binary_auth_factory
        n = SimpleNamespace(
            component_type="fake_bin_auth",
            component_config=SimpleNamespace(
                extra_config={"operation": op, **cfg}, credential_id=None),
        )
        return binary_auth_factory(n)({})

    def test_a_listing_verb_returns_its_port(self, plugin):
        respond(plugin, ok({"sessions": [{"id": "a1", "env": "e1"}]}))
        assert self._run("auth.sessionList")["sessions"][0]["id"] == "a1"

    def test_the_password_travels_on_stdin_and_not_on_argv(self, plugin):
        respond(plugin, ok({"session": {"id": "a1"}}))
        self._run("auth.login", env="e1", session="a1", username="u", password="hunter2")
        argv = json.loads((io_dir(plugin) / "last_argv.json").read_text())
        stdin = json.loads((io_dir(plugin) / "last_stdin.json").read_text())
        assert "hunter2" not in " ".join(argv)
        assert stdin["credential"]["password"] == "hunter2"
        assert argv[:4] == ["--env", "e1", "--session", "a1"]

    def test_a_missing_required_parameter_is_caught_before_spawning(self, plugin):
        respond(plugin, ok())
        with pytest.raises(Exception) as exc:
            self._run("auth.login", env="e1")
        assert type(exc.value).__name__ == "MISSING_PARAM"
        assert not (io_dir(plugin) / "last_argv.json").exists()

    def test_an_unknown_verb_is_refused(self, plugin):
        respond(plugin, ok())
        with pytest.raises(Exception) as exc:
            self._run("auth.teleport")
        assert type(exc.value).__name__ == "UNKNOWN_VERB"

    def test_a_binary_refusal_surfaces_under_its_own_code(self, plugin):
        respond(plugin, failed("LOGIN_REJECTED"), exit_code=4)
        with pytest.raises(Exception) as exc:
            self._run("auth.login", env="e1", session="a1", username="u", password="p")
        assert type(exc.value).__name__ == "LOGIN_REJECTED"
