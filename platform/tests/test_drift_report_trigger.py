"""The "SURFACE CHANGED" report at the registration boundary triggers on the
COMPUTED DIFF of operation ids — never on catalog_hash inequality alone.

A binary's catalog_hash can legitimately cover things that are not the
operation surface (its own build stamp, e.g.), so a binary hashed that way
changes catalog_hash on every rebuild even when its operations are
byte-for-byte identical. Gating the header on hash inequality would then fire
it on every registration with empty added/removed lists — a warning that
cries wolf on every rebuild is worse than no warning, because it trains
people to ignore the one time it matters. This suite plants exactly the
violations that must and must not trip the header.

Fixtures are deliberately invented — `demo-bin` / `things` / `doThing` — never
a real operator-supplied catalog, in line with the rest of this test suite.
"""

from __future__ import annotations

import json
import sys

import pytest

import schemas.binary_catalogs as binary_catalogs
import scripts.register_plugin as register_plugin
from services import plugins as plugins_module
from services.plugins import Registration, resolve, tree_checksum, tree_fingerprint, write_registration
from tests.test_binary_catalogs import _catalog, _op
from tests.test_binary_plugins import FAKE_BIN


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """An installed + registered fake plugin, and a catalog directory this
    test overwrites across steps — the shape one real re-registration takes."""
    root = tmp_path / "plugins"
    directory = root / "demo-bin"
    directory.mkdir(parents=True)
    (directory / "bin.py").write_text(FAKE_BIN)
    (directory / "plugin.json").write_text(json.dumps({"exec": ["python3", "bin.py"]}))
    (directory / "catalog.json").write_text(json.dumps(_catalog(binary="demo-bin")))
    (root / "io").mkdir()

    registrations = tmp_path / "registrations"
    registrations.mkdir()
    monkeypatch.setattr(plugins_module, "PLUGIN_DIR", root)
    monkeypatch.setattr(plugins_module, "REGISTRATION_DIR", registrations)

    p = resolve("demo-bin", root)
    write_registration(Registration(
        binary="demo-bin", plugin="demo-bin", argv=p.argv,
        checksum=tree_checksum(directory), fingerprint=tree_fingerprint(directory),
        catalog_hash="sha256:" + "1" * 64, registered_at="2026-08-18T00:00:00+00:00",
    ))

    catalogs = tmp_path / "catalogs"
    catalogs.mkdir()
    monkeypatch.setattr(binary_catalogs, "CATALOG_DIR", catalogs)
    return directory, catalogs


def _register(directory, catalogs, monkeypatch, **catalog_overrides):
    """Write a catalog with the given overrides to the plugin dir and register it."""
    (directory / "catalog.json").write_text(json.dumps(_catalog(binary="demo-bin", **catalog_overrides)))
    monkeypatch.setattr(register_plugin, "CATALOG_DIR", catalogs)
    monkeypatch.setattr(sys, "argv", ["register_plugin.py", "demo-bin"])
    # Point register_plugin's own db session (used for the saved-node drift
    # check) at the same in-memory engine the `db` fixture uses, rather than
    # the real configured database file.
    import database
    from conftest import TestSession
    monkeypatch.setattr(database, "SessionLocal", TestSession)
    rc = register_plugin.main()
    return rc


class TestDriftReportTrigger:
    def test_identical_operations_but_a_different_hash_does_not_cry_wolf(
            self, plugin_env, monkeypatch, capsys, db,
    ):
        directory, catalogs = plugin_env

        # First registration: baseline.
        assert _register(directory, catalogs, monkeypatch,
                          operations=[_op(id="things.doThing")]) == 0
        capsys.readouterr()  # discard first-registration output

        # Second registration: SAME operations, but a hash that differs (as a
        # binary computing its hash over something like a build stamp would
        # produce on every rebuild).
        assert _register(directory, catalogs, monkeypatch,
                          catalog_hash="sha256:" + "2" * 64,
                          operations=[_op(id="things.doThing")]) == 0
        out = capsys.readouterr().out

        assert "SURFACE CHANGED" not in out
        assert "removed" not in out
        assert "added" not in out
        # The quiet note takes its place.
        assert "operation surface unchanged" in out

    def test_an_unchanged_hash_does_not_hide_a_changed_surface(
            self, plugin_env, monkeypatch, capsys, db,
    ):
        """The mirror of the cry-wolf case, and the reason the report is not
        gated on the hash at all.

        A binary whose catalog_hash fails to move when its operations move
        would, under a hash-gated report, silence the warning at exactly the
        moment it is needed. The report must not depend on another binary's
        hashing discipline in EITHER direction: a hash that changes too often
        makes it noise, and a hash that changes too rarely makes it absent.
        """
        directory, catalogs = plugin_env

        assert _register(directory, catalogs, monkeypatch,
                          catalog_hash="sha256:" + "9" * 64,
                          operations=[_op(id="things.doThing")]) == 0
        capsys.readouterr()

        # Same hash as before — deliberately stale — but the surface changed.
        assert _register(directory, catalogs, monkeypatch,
                          catalog_hash="sha256:" + "9" * 64,
                          operations=[_op(id="things.doOther")]) == 0
        out = capsys.readouterr().out

        assert "SURFACE CHANGED" in out
        assert "things.doThing" in out
        assert "things.doOther" in out

    def test_a_removed_operation_fires_the_report_and_names_it(
            self, plugin_env, monkeypatch, capsys, db,
    ):
        directory, catalogs = plugin_env

        assert _register(directory, catalogs, monkeypatch,
                          operations=[_op(id="things.doThing"), _op(id="things.other", domain="things")]) == 0
        capsys.readouterr()

        assert _register(directory, catalogs, monkeypatch,
                          catalog_hash="sha256:" + "2" * 64,
                          operations=[_op(id="things.doThing")]) == 0
        out = capsys.readouterr().out

        assert "SURFACE CHANGED" in out
        assert "removed  things.other" in out
        assert "added" not in out.split("removed  things.other")[1].split("\n")[0]

    def test_an_added_operation_fires_the_report_and_names_it(
            self, plugin_env, monkeypatch, capsys, db,
    ):
        directory, catalogs = plugin_env

        assert _register(directory, catalogs, monkeypatch,
                          operations=[_op(id="things.doThing")]) == 0
        capsys.readouterr()

        assert _register(directory, catalogs, monkeypatch,
                          catalog_hash="sha256:" + "2" * 64,
                          operations=[_op(id="things.doThing"), _op(id="things.newOne", domain="things")]) == 0
        out = capsys.readouterr().out

        assert "SURFACE CHANGED" in out
        assert "added    things.newOne" in out
