"""Task 4a: the drift guard at the registration boundary, planted violation #2
(catalog-change semantics for a saved node), and the restart-trap demonstration.

Fixtures are invented — `fake-bin`, `things.doThing` — never a real
operator-supplied catalog: those are gitignored and unreconstructible, so a test
that hardcoded it would put back exactly what the gitignore is keeping out.

`binary_op` / `binary_auth` are STATIC polymorphic identities (models/node.py):
registered once, at import, whatever this machine's catalogs happen to hold.
Ports are resolved PER NODE, per call, from the catalog FILE
(schemas.binary_catalogs, mtime-cached, nothing read at import). Together this
is what makes registering a new plugin mid-process usable with zero restarts —
the property TestRestartTrap below proves directly — and it is also why
protecting a saved node from a catalog change has to happen at the
registration boundary (decision 2 of the plan): there is no per-node snapshot
to compare against.
"""

from __future__ import annotations

import json
import sys

import pytest
from fastapi.testclient import TestClient

import schemas.binary_catalogs as binary_catalogs
import scripts.register_plugin as register_plugin
from components.binary_op import binary_op_factory
from services import plugins as plugins_module
from services.plugins import (
    Registration,
    detect_drift,
    resolve,
    tree_checksum,
    tree_fingerprint,
    write_registration,
)
from services.expressions import resolve_expressions
from tests.test_binary_catalogs import _catalog, _op
from tests.test_binary_plugins import FAKE_BIN, io_dir, ok

DOTHING_OUTPUTS_AB = [
    {"name": "thing_id", "type": "string", "description": "a"},
    {"name": "extra", "type": "string", "description": "b"},
]
DOTHING_OUTPUTS_A = [
    {"name": "thing_id", "type": "string", "description": "a"},
]


def _write_catalog(catalogs_dir, outputs=None, operations=None, **overrides):
    doc = _catalog(
        binary="fake-bin",
        operations=operations if operations is not None else [_op(outputs=outputs)],
        **overrides,
    )
    (catalogs_dir / "fake-bin.json").write_text(json.dumps(doc))
    return doc


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """An installed + registered fake plugin, and a catalog directory this
    test overwrites across steps — the shape one real re-registration takes."""
    root = tmp_path / "plugins"
    directory = root / "fake-bin"
    directory.mkdir(parents=True)
    (directory / "bin.py").write_text(FAKE_BIN)
    (directory / "plugin.json").write_text(json.dumps({"exec": ["python3", "bin.py"]}))
    (directory / "catalog.json").write_text(json.dumps(_catalog(binary="fake-bin")))
    (root / "io").mkdir()

    registrations = tmp_path / "registrations"
    registrations.mkdir()
    monkeypatch.setattr(plugins_module, "PLUGIN_DIR", root)
    monkeypatch.setattr(plugins_module, "REGISTRATION_DIR", registrations)

    p = resolve("fake-bin", root)
    write_registration(Registration(
        binary="fake-bin", plugin="fake-bin", argv=p.argv,
        checksum=tree_checksum(directory), fingerprint=tree_fingerprint(directory),
        catalog_hash="sha256:" + "1" * 64, registered_at="2026-08-18T00:00:00+00:00",
    ))

    catalogs = tmp_path / "catalogs"
    catalogs.mkdir()
    monkeypatch.setattr(binary_catalogs, "CATALOG_DIR", catalogs)
    return directory, catalogs


@pytest.fixture
def app(db):
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
def auth_client(app, api_key):
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


def _post_node(client, slug, node_id, component_type="binary_op", **extra_config):
    return client.post(f"/api/v1/workflows/{slug}/nodes/", json={
        "node_id": node_id,
        "component_type": component_type,
        "config": {"extra_config": extra_config},
    })


def _post_edge(client, slug, source, target):
    return client.post(f"/api/v1/workflows/{slug}/edges/", json={
        "source_node_id": source, "target_node_id": target, "edge_type": "direct",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Deliverable 1 — the drift guard, unit-level and at the actual registration
# boundary (scripts/register_plugin.py).
# ─────────────────────────────────────────────────────────────────────────────


class TestDriftGuard:
    """services.plugins.detect_drift — the function the registration boundary
    calls. Never blocks: it always returns a list, never raises."""

    def test_no_previous_catalog_is_no_drift(self, db):
        assert detect_drift(db, "fake-bin", None, _catalog(binary="fake-bin")) == []

    def test_a_node_with_no_saved_operation_is_ignored(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowNode

        cc = BaseComponentConfig(component_type="binary_op",
                                  extra_config={"binary": "fake-bin"})
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="bin_bare",
                             component_type="binary_op", component_config_id=cc.id))
        db.commit()

        old = _catalog(binary="fake-bin", operations=[_op(outputs=DOTHING_OUTPUTS_AB)])
        new = _catalog(binary="fake-bin", operations=[_op(outputs=DOTHING_OUTPUTS_A)])
        assert detect_drift(db, "fake-bin", old, new) == []

    def test_names_the_node_and_the_lost_port(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowNode

        cc = BaseComponentConfig(component_type="binary_op", extra_config={
            "binary": "fake-bin", "operation": "things.doThing"})
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="bin_1",
                             component_type="binary_op", component_config_id=cc.id))
        db.commit()

        old = _catalog(binary="fake-bin", operations=[_op(outputs=DOTHING_OUTPUTS_AB)])
        new = _catalog(binary="fake-bin", operations=[_op(outputs=DOTHING_OUTPUTS_A)])
        drift = detect_drift(db, "fake-bin", old, new)

        assert len(drift) == 1
        entry = drift[0]
        assert entry.workflow_slug == workflow.slug
        assert entry.node_id == "bin_1"
        assert entry.change == "output_ports_lost"
        assert "extra" in entry.detail

    def test_names_a_vanished_operation(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowNode

        cc = BaseComponentConfig(component_type="binary_op", extra_config={
            "binary": "fake-bin", "operation": "things.doThing"})
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="bin_gone",
                             component_type="binary_op", component_config_id=cc.id))
        db.commit()

        old = _catalog(binary="fake-bin", operations=[_op(outputs=DOTHING_OUTPUTS_AB)])
        new = _catalog(binary="fake-bin", operations=[_op(id="things.other", outputs=[])])
        drift = detect_drift(db, "fake-bin", old, new)

        assert len(drift) == 1
        assert drift[0].change == "operation_removed"
        assert drift[0].node_id == "bin_gone"

    def test_a_different_binarys_nodes_are_not_reported(self, db, workflow):
        """The comparison is scoped to the binary being re-registered."""
        from models.node import BaseComponentConfig, WorkflowNode

        cc = BaseComponentConfig(component_type="binary_op", extra_config={
            "binary": "other-bin", "operation": "things.doThing"})
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="bin_other",
                             component_type="binary_op", component_config_id=cc.id))
        db.commit()

        old = _catalog(binary="fake-bin", operations=[_op(outputs=DOTHING_OUTPUTS_AB)])
        new = _catalog(binary="fake-bin", operations=[_op(outputs=DOTHING_OUTPUTS_A)])
        assert detect_drift(db, "fake-bin", old, new) == []


class TestDriftGuardAtRegistration:
    """The guard as it actually runs — scripts/register_plugin.py — invoked
    against a fake plugin, re-registering over a catalog a saved node depends
    on. Report loudly; never block: exit code stays 0."""

    def test_re_registration_reports_the_saved_node_by_name_and_never_blocks(
            self, plugin_env, workflow, db, monkeypatch, capsys):
        directory, catalogs = plugin_env

        # First registration: catalog v1, outputs [thing_id, extra].
        (directory / "catalog.json").write_text(json.dumps(
            _catalog(binary="fake-bin", operations=[_op(outputs=DOTHING_OUTPUTS_AB)])
        ))
        monkeypatch.setattr(register_plugin, "CATALOG_DIR", catalogs)
        monkeypatch.setattr(sys, "argv", ["register_plugin.py", "fake-bin"])
        assert register_plugin.main() == 0
        capsys.readouterr()  # discard first-registration output

        # A saved node depending on 'extra', the port about to disappear.
        from models.node import BaseComponentConfig, WorkflowNode

        cc = BaseComponentConfig(component_type="binary_op", extra_config={
            "binary": "fake-bin", "operation": "things.doThing", "session": "s1"})
        db.add(cc)
        db.flush()
        db.add(WorkflowNode(workflow_id=workflow.id, node_id="bin_drift",
                             component_type="binary_op", component_config_id=cc.id))
        db.commit()

        # Point register_plugin's own db session at the SAME in-memory engine
        # the `db` fixture uses, so it sees the node just committed.
        import database
        from conftest import TestSession
        monkeypatch.setattr(database, "SessionLocal", TestSession)

        # Re-registration: catalog v2 drops 'extra'.
        (directory / "catalog.json").write_text(json.dumps(
            _catalog(binary="fake-bin", catalog_hash="sha256:" + "2" * 64,
                     operations=[_op(outputs=DOTHING_OUTPUTS_A)])
        ))
        monkeypatch.setattr(sys, "argv", ["register_plugin.py", "fake-bin"])
        rc = register_plugin.main()
        out = capsys.readouterr().out

        # Report loudly; do NOT block — re-registration is a deliberate act.
        assert rc == 0
        assert workflow.slug in out
        assert "bin_drift" in out
        assert "extra" in out
        # The corrected message: no restart is required any more.
        assert "No restart needed" in out
        assert "RESTART" not in out


# ─────────────────────────────────────────────────────────────────────────────
# Deliverable 2 — planted violation #2: catalog-change semantics for a saved
# node. A port can never vanish silently anywhere in this sequence.
# ─────────────────────────────────────────────────────────────────────────────


class TestPlantedViolationTwo:
    def test_the_full_sequence(self, plugin_env, auth_client, workflow, db):
        directory, catalogs = plugin_env
        slug = workflow.slug

        catalog_v1 = _write_catalog(catalogs, outputs=DOTHING_OUTPUTS_AB)

        resp = _post_node(auth_client, slug, "bin_1", binary="fake-bin",
                           operation="things.doThing", session="s1")
        assert resp.status_code == 201, resp.json()

        from models.node import WorkflowNode
        saved = db.query(WorkflowNode).filter_by(
            workflow_id=workflow.id, node_id="bin_1").one()

        # ── (i) execution fills b: None when the envelope omits it ──────────
        # This is the null-never-absent rule, and it is load-bearing:
        # resolve_expressions (services/expressions.py:44-46) returns the
        # ORIGINAL template string on failure, so a MISSING key would send the
        # LITERAL "{{ bin_1.extra }}" downstream instead of a null.
        io = io_dir(directory)
        (io / "response.json").write_text(json.dumps(ok({"thing_id": "t-1"})))
        (io / "exit_code").write_text("0")

        result = binary_op_factory(saved)({})
        assert result == {"thing_id": "t-1", "extra": None}
        assert "extra" in result  # present, not merely absent-and-defaulted

        resolved = resolve_expressions("{{ bin_1.extra }}", {"bin_1": result})
        assert resolved == "None"
        assert resolved != "{{ bin_1.extra }}"

        # ── (ii) overwrite so X's outputs become [a] — the drift guard NAMES
        #         the node and the lost port ─────────────────────────────────
        catalog_v2 = _write_catalog(catalogs, outputs=DOTHING_OUTPUTS_A)
        drift = detect_drift(db, "fake-bin", catalog_v1, catalog_v2)
        assert len(drift) == 1
        assert drift[0].workflow_slug == slug
        assert drift[0].node_id == "bin_1"
        assert drift[0].change == "output_ports_lost"
        assert "extra" in drift[0].detail

        # Still not silent at run time either: the operation still exists, it
        # simply no longer declares 'extra' — so it is no longer offered, not
        # quietly dropped.
        (io / "response.json").write_text(json.dumps(ok({"thing_id": "t-1"})))
        (io / "exit_code").write_text("0")
        result2 = binary_op_factory(saved)({})
        assert result2 == {"thing_id": "t-1"}

        # ── (iii) overwrite so X is gone entirely — /validate/ FAILS the
        #          node. Edge creation still permits it (decision B); the
        #          validate report is the guard that must bite ──────────────
        _write_catalog(catalogs, operations=[
            _op(id="things.other", outputs=[{"name": "z", "type": "string", "description": ""}]),
        ])

        assert _post_node(auth_client, slug, "sink", component_type="switch",
                           rules=[]).status_code == 201
        assert _post_edge(auth_client, slug, "bin_1", "sink").status_code == 201

        resp = auth_client.post(f"/api/v1/workflows/{slug}/validate/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert any(
            "bin_1" in e and "does not offer" in e and "things.doThing" in e
            for e in body["errors"]
        )


# ─────────────────────────────────────────────────────────────────────────────
# Deliverable 3 — the restart-trap demonstration. The headline claim of this
# stage: a plugin registered into an ALREADY RUNNING process is fully usable
# with zero restarts, zero reimports.
# ─────────────────────────────────────────────────────────────────────────────


class TestRestartTrap:
    def test_a_plugin_registered_mid_process_needs_no_restart(
            self, tmp_path, monkeypatch, db, api_key, workflow):
        # 1. "Start the app" with an EMPTY catalog dir — simulate normal boot.
        catalogs = tmp_path / "catalogs"
        plugin_root = tmp_path / "plugins"
        registrations = tmp_path / "registrations"
        for d in (catalogs, plugin_root, registrations):
            d.mkdir()
        monkeypatch.setattr(binary_catalogs, "CATALOG_DIR", catalogs)
        monkeypatch.setattr(plugins_module, "PLUGIN_DIR", plugin_root)
        monkeypatch.setattr(plugins_module, "REGISTRATION_DIR", registrations)

        from database import get_db
        from main import app as _app

        def _override_get_db():
            try:
                yield db
            finally:
                pass

        _app.dependency_overrides[get_db] = _override_get_db
        try:
            client = TestClient(_app)
            client.headers["Authorization"] = f"Bearer {api_key.key}"
            slug = workflow.slug

            # Normal boot behaviour: the palette loads node types. binary_op
            # is STATIC — registered regardless of what the (currently empty)
            # catalog dir holds. Under the OLD dynamic-derivation design,
            # 'binary_op' would not exist as a type AT ALL until a catalog
            # was present at IMPORT time — this call proves it needs none.
            types = client.get("/api/v1/workflows/node-types/").json()
            assert "binary_op" in types

            # Nothing registered yet.
            assert client.get("/api/v1/plugins/catalog/").json()["items"] == []

            # 2. WITHOUT reimporting anything — no importlib.reload, no new
            # interpreter, no fixture that re-executes a module import — plant
            # a fake plugin dir + registration record + catalog file directly
            # on disk. This is exactly what `scripts/register_plugin.py`
            # would have written; the subprocess call to a real binary is
            # skipped because it is not needed to prove this property.
            plugin_dir = plugin_root / "demo-bin"
            plugin_dir.mkdir()
            (plugin_dir / "bin.py").write_text(FAKE_BIN)
            (plugin_dir / "plugin.json").write_text(json.dumps({"exec": ["python3", "bin.py"]}))
            (plugin_root / "io").mkdir()

            catalog_doc = _catalog(binary="demo-bin", operations=[_op(outputs=DOTHING_OUTPUTS_AB)])
            (catalogs / "demo-bin.json").write_text(json.dumps(catalog_doc))

            p = resolve("demo-bin", plugin_root)
            write_registration(Registration(
                binary="demo-bin", plugin="demo-bin", argv=p.argv,
                checksum=tree_checksum(plugin_dir), fingerprint=tree_fingerprint(plugin_dir),
                catalog_hash=catalog_doc["catalog_hash"],
                registered_at="2026-08-18T00:00:00+00:00",
            ))

            # 3. Same process, no reimport: the catalog endpoint lists it
            # immediately (mtime-cache miss on first read, nothing cached from
            # before since the file did not exist).
            resp = client.get("/api/v1/plugins/catalog/")
            assert resp.status_code == 200
            items = {i["binary"]: i for i in resp.json()["items"]}
            assert "demo-bin" in items
            assert items["demo-bin"]["schema"]["x-operations"]["things.doThing"]["domain"] == "things"

            # 4. POST a binary_op node naming it — passes the allowlist (201).
            # Under the OLD dynamic-derivation design this node TYPE could not
            # even be constructed without a restart: the mapped class was
            # built from catalogs present at import.
            resp = client.post(f"/api/v1/workflows/{slug}/nodes/", json={
                "node_id": "bin_1", "component_type": "binary_op",
                "config": {"extra_config": {
                    "binary": "demo-bin", "operation": "things.doThing", "session": "s1"}},
            })
            assert resp.status_code == 201, resp.json()

            # 5. The saved node's component_config row LOADS BACK through
            # SQLAlchemy. This is the direct proof: "No such
            # polymorphic_identity" is impossible by construction now,
            # because 'binary_op' is a STATIC identity that was already
            # mapped when this test process started — nothing new to import,
            # nothing that could be missing.
            from models.node import BaseComponentConfig, WorkflowNode

            saved = db.query(WorkflowNode).filter_by(
                workflow_id=workflow.id, node_id="bin_1").one()
            cfg = db.get(BaseComponentConfig, saved.component_config_id)
            assert cfg.component_type == "binary_op"
            assert type(cfg).__name__ == "_BinaryOpConfig"
            assert cfg.extra_config["binary"] == "demo-bin"

            # 6. /validate/ resolves its ports — no unresolved-ports report
            # for this node.
            resp = client.post(f"/api/v1/workflows/{slug}/validate/")
            assert resp.status_code == 200
            errors = resp.json()["errors"]
            assert not any("bin_1" in e for e in errors)

            # 7. Executing the node through the component returns the
            # envelope's data on the operation's ports.
            io = plugin_root / "io"
            (io / "response.json").write_text(json.dumps(ok({"thing_id": "t-live"})))
            (io / "exit_code").write_text("0")
            result = binary_op_factory(saved)({})
            assert result == {"thing_id": "t-live", "extra": None}
        finally:
            _app.dependency_overrides.clear()
