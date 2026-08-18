"""Plugin integrity, and executing an operation through one.

The fake plugin here is a real executable emitting canned envelopes, so the
subprocess path is exercised rather than mocked. A live binary cannot be asked
for an undischarged proof or a malformed envelope on demand — provoking those
against a real backend means causing a real silent refusal — so the failure paths
have to be driven by a fixture. The live run proves the happy path; this proves
everything else.
"""

import json
import os
import subprocess

import pytest

import schemas.binary_catalogs as binary_catalogs
from components.binary_op import binary_op_factory
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


def _catalog(binary="fake-bin", **overrides):
    doc = {
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
    doc.update(overrides)
    return doc


def declare(catalog_dir_module, **overrides):
    """Rewrite the pinned catalog with per-binary declarations.

    The components read the catalog per call through the mtime cache, so a
    rewrite is visible on the very next call — the same property registration
    relies on.
    """
    path = catalog_dir_module.CATALOG_DIR / "fake-bin.json"
    path.write_text(json.dumps(_catalog(**overrides)))
    # Two quick writes may share an mtime tick, and the cache is mtime-keyed.
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


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
    # The components resolve the catalog per call through the access layer, so
    # pointing the directory somewhere else is all a test needs — no node types
    # to register, no registry to restore.
    monkeypatch.setattr(binary_catalogs, "CATALOG_DIR", catalogs)
    yield directory


def io_dir(plugin_dir):
    return plugin_dir.parent / "io"


def respond(directory, envelope, exit_code=0):
    io = io_dir(directory)
    (io / "response.json").write_text(json.dumps(envelope))
    (io / "exit_code").write_text(str(exit_code))


def ok(data=None, proof=None, slot_patch=None):
    return {"ok": True, "data": data or {}, "proof": proof,
            "slot_patch": slot_patch, "error": None}


def failed(code, message="it failed", slot_patch=None, retryable=False):
    return {"ok": False, "data": None, "proof": None, "slot_patch": slot_patch,
            "error": {"code": code, "message": message, "retryable": retryable, "details": {}}}


def node(**extra):
    from types import SimpleNamespace
    extra.setdefault("binary", "fake-bin")
    extra.setdefault("operation", "things.doThing")
    return SimpleNamespace(
        component_type="binary_op",
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

    def test_a_failure_carries_the_binarys_retryable_verdict(self, plugin):
        """The envelope's `retryable` rides the exception so the orchestrator
        can refuse to repeat a write whose first attempt may have landed."""
        respond(plugin, failed("WRITE_UNVERIFIED", retryable=False), exit_code=6)
        with pytest.raises(Exception) as exc:
            run(plugin, session="s1")
        assert exc.value.retryable is False

    def test_a_failure_the_binary_calls_repeatable_says_so(self, plugin):
        respond(plugin, failed("BACKEND_BUSY", retryable=True), exit_code=6)
        with pytest.raises(Exception) as exc:
            run(plugin, session="s1")
        assert exc.value.retryable is True

    def test_a_failure_without_a_verdict_claims_none(self, plugin):
        """Absent must not be flattened into 'yes, repeat me'."""
        envelope = failed("MYSTERY")
        del envelope["error"]["retryable"]
        respond(plugin, envelope, exit_code=6)
        with pytest.raises(Exception) as exc:
            run(plugin, session="s1")
        assert getattr(exc.value, "retryable", None) is None

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


class TestStaticTypes:
    """binary_op / binary_auth are static: registered at import, whatever the
    machine's catalogs hold. The binary is node data, resolved per call."""

    def test_the_factories_are_registered_under_the_static_names(self):
        from components import get_component_factory
        from components.binary_auth import binary_auth_factory

        assert get_component_factory("binary_op") is binary_op_factory
        assert get_component_factory("binary_auth") is binary_auth_factory

    def test_the_config_mapping_pins_the_static_identities(self):
        """COMPONENT_TYPE_TO_CONFIG is the registry of mapped component
        types. Loading happens to survive via `__mapper_args__` polymorphic
        identity if an entry vanishes, so no production path pins these two
        lines — only this assertion does."""
        from models.node import (
            COMPONENT_TYPE_TO_CONFIG,
            _BinaryAuthConfig,
            _BinaryOpConfig,
        )

        assert COMPONENT_TYPE_TO_CONFIG["binary_op"] is _BinaryOpConfig
        assert COMPONENT_TYPE_TO_CONFIG["binary_auth"] is _BinaryAuthConfig

    def test_a_node_naming_no_binary_is_refused(self, plugin):
        with pytest.raises(Exception) as exc:
            run(plugin, binary="", session="s1")
        assert type(exc.value).__name__ == "NO_BINARY"

    def test_a_node_naming_an_uncatalogued_binary_is_refused(self, plugin):
        with pytest.raises(Exception) as exc:
            run(plugin, binary="no-such-bin", session="s1")
        assert type(exc.value).__name__ == "UNKNOWN_BINARY"

    def test_an_identity_node_naming_no_binary_is_refused(self, plugin):
        from types import SimpleNamespace

        from components.binary_auth import binary_auth_factory
        n = SimpleNamespace(
            component_type="binary_auth",
            component_config=SimpleNamespace(
                extra_config={"operation": "auth.sessionList"}, credential_id=None),
        )
        with pytest.raises(Exception) as exc:
            binary_auth_factory(n)({})
        assert type(exc.value).__name__ == "NO_BINARY"


class TestIdentityNode:
    """The verb surface as a node — one component serves every plugin."""

    @staticmethod
    def _run(op, **cfg):
        from types import SimpleNamespace

        from components.binary_auth import binary_auth_factory
        n = SimpleNamespace(
            component_type="binary_auth",
            component_config=SimpleNamespace(
                extra_config={"binary": "fake-bin", "operation": op, **cfg},
                credential_id=None),
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

    def test_a_refusal_carries_the_retryable_verdict_too(self, plugin):
        """binary_auth failures ride the same envelope contract as binary_op."""
        respond(plugin, failed("STORE_LOCKED", retryable=False), exit_code=4)
        with pytest.raises(Exception) as exc:
            self._run("auth.login", env="e1", session="a1", username="u", password="p")
        assert exc.value.retryable is False

    def test_a_declared_credential_travels_on_stdin_and_not_on_argv(self, plugin):
        """The keys on stdin are the keys the BINARY declares, not a fixed
        list: a bare-token binary gets its token, is not asked for a username,
        and the secret still never touches the command line."""
        declare(binary_catalogs, credential_schema={
            "type": "object",
            "required": ["api_token"],
            "properties": {"api_token": {"type": "string", "secret": True}},
        })
        respond(plugin, ok({"session": {"id": "a1"}}))
        self._run("auth.login", env="e1", session="a1", api_token="sekrit-9")
        argv = json.loads((io_dir(plugin) / "last_argv.json").read_text())
        stdin = json.loads((io_dir(plugin) / "last_stdin.json").read_text())
        assert stdin["credential"] == {"api_token": "sekrit-9"}
        assert "sekrit-9" not in " ".join(argv)
        assert argv[:4] == ["--env", "e1", "--session", "a1"]

    def test_a_declared_required_field_is_caught_before_spawning(self, plugin):
        """The reported bug, inverted: a login the binary cannot accept — a
        declared required field left empty — must fail here, not at the
        backend."""
        declare(binary_catalogs, credential_schema={
            "type": "object",
            "required": ["username", "password", "tenant"],
            "properties": {"username": {"type": "string"},
                           "password": {"type": "string", "secret": True},
                           "tenant": {"type": "string"}},
        })
        respond(plugin, ok())
        with pytest.raises(Exception) as exc:
            self._run("auth.login", env="e1", session="a1", username="u", password="p")
        assert type(exc.value).__name__ == "MISSING_PARAM"
        assert "tenant" in str(exc.value)
        assert not (io_dir(plugin) / "last_argv.json").exists()

    def test_declared_env_fields_are_passed_as_flags(self, plugin):
        """`env add` composes from the env_schema the catalog has ALWAYS
        carried — required at registration, and unread until now."""
        declare(binary_catalogs, env_schema={
            "type": "object",
            "required": ["url", "region"],
            "properties": {"url": {"type": "string"}, "region": {"type": "string"}},
        })
        respond(plugin, ok({"environment": {"name": "uat1"}}))
        self._run("env.add", name="uat1", url="https://x", region="ap")
        argv = json.loads((io_dir(plugin) / "last_argv.json").read_text())
        assert argv == ["env", "add", "uat1", "--url", "https://x", "--region", "ap"]


class TestCatalogEndpoint:
    """GET /api/v1/plugins/catalog/ — each REGISTERED binary's legacy-shaped
    config schema, read from the pinned catalog file via the Wave 1 access
    layer. Never by running the binary: the file is the pin."""

    @pytest.fixture
    def app(self, db):
        from database import get_db
        from main import app as _app

        def _override_get_db():
            try:
                yield db
            finally:
                pass

        _app.dependency_overrides[get_db] = _override_get_db
        yield _app
        _app.dependency_overrides.clear()

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    @pytest.fixture
    def auth_client(self, client, api_key):
        client.headers["Authorization"] = f"Bearer {api_key.key}"
        return client

    def test_a_registered_plugin_appears_with_operation_enum_and_domains(self, plugin, auth_client):
        resp = auth_client.get("/api/v1/plugins/catalog/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == len(body["items"])
        items = {item["binary"]: item for item in body["items"]}
        entry = items["fake-bin"]
        assert entry["plugin"] == "fake-bin"
        assert entry["schema"]["properties"]["operation"]["enum"] == ["things.doThing"]
        assert entry["schema"]["required"] == ["operation"]
        assert entry["schema"]["x-binary"] == "fake-bin"
        assert entry["schema"]["x-operations"]["things.doThing"]["domain"] == "things"

    def test_the_declared_schemas_ride_along_raw(self, plugin, auth_client):
        """The two objects the contract keeps opaque — what `auth login` reads
        as `credential`, and the environment record — are served as the binary
        declared them, so the frontend can compose the identity node's form."""
        declare(binary_catalogs, credential_schema={
            "type": "object",
            "properties": {"api_token": {"type": "string", "secret": True}},
        })
        resp = auth_client.get("/api/v1/plugins/catalog/")
        entry = {item["binary"]: item for item in resp.json()["items"]}["fake-bin"]
        assert entry["credential_schema"]["properties"]["api_token"]["secret"] is True
        assert entry["env_schema"] == {"type": "object"}

    def test_a_binary_declaring_no_credential_schema_serves_null(self, plugin, auth_client):
        """Null means "not describing one", never "none needed" — the form
        falls back to the platform's default fields."""
        resp = auth_client.get("/api/v1/plugins/catalog/")
        entry = {item["binary"]: item for item in resp.json()["items"]}["fake-bin"]
        assert entry["credential_schema"] is None
        assert entry["env_schema"] == {"type": "object"}

    def test_an_unregistered_plugin_directory_is_absent(self, plugin, auth_client):
        """Installed (a directory with a plugin.json) is not the same as
        registered (has passed conformance and has a registration record)."""
        other = plugin.parent / "other-bin"
        other.mkdir()
        (other / "plugin.json").write_text(json.dumps({"exec": ["python3", "bin.py"]}))

        resp = auth_client.get("/api/v1/plugins/catalog/")
        binaries = {item["binary"] for item in resp.json()["items"]}
        assert binaries == {"fake-bin"}
        assert "other-bin" not in binaries

    def test_auth_is_required(self, plugin, client):
        resp = client.get("/api/v1/plugins/catalog/")
        assert resp.status_code in (401, 403)

    def test_an_invalid_bearer_token_is_rejected(self, plugin, client):
        client.headers["Authorization"] = "Bearer not-a-real-key"
        resp = client.get("/api/v1/plugins/catalog/")
        assert resp.status_code == 401

    def test_a_registered_binary_with_an_unreadable_catalog_yields_schema_null(self, plugin, auth_client):
        """A missing/unreadable catalog disables just that one entry — it must
        not take down the rest of the listing."""
        plugins.write_registration(Registration(
            binary="ghost-bin", plugin="fake-bin", argv=["python3", "bin.py"],
            checksum="sha256:" + "0" * 64, fingerprint="fp:whatever",
            catalog_hash="x", registered_at="2026-08-18T00:00:00+00:00",
        ))

        resp = auth_client.get("/api/v1/plugins/catalog/")
        assert resp.status_code == 200
        items = {item["binary"]: item for item in resp.json()["items"]}
        assert items["ghost-bin"]["schema"] is None
        assert items["fake-bin"]["schema"] is not None
