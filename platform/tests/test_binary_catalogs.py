"""The catalog access layer behind the static binary node types.

Fixtures here are deliberately invented — `demo-bin`, `things`, `doThing`. The
real catalogs describe one organisation's operations and are gitignored for that
reason; a test file that hardcoded them would put back exactly what the gitignore
is keeping out.

Nothing here registers node types: `binary_op` and `binary_auth` are static, and
this module answers per-call questions about a binary's pinned catalog. The
freshness tests below are the point of that design — a catalog registered into
an already-running process is visible on the very next call, no reimport.
"""

import json
import os

import pytest

from schemas.binary_catalogs import (
    catalog_for,
    config_schema_for,
    operation_output_ports,
    operations_for,
)
from schemas.node_types import DataType


def _catalog(binary="demo-bin", operations=None, **overrides):
    doc = {
        "protocol": 1,
        "binary": binary,
        "version": "1.0.0",
        "generated_from": {"tree": "example/demo", "commit": "abc1234", "dirty": False},
        "catalog_hash": "sha256:" + "0" * 64,
        "env_schema": {"type": "object"},
        "operations": operations if operations is not None else [_op()],
    }
    doc.update(overrides)
    return doc


def _op(id="things.doThing", domain="things", outputs=None, **overrides):
    op = {
        "id": id,
        "domain": domain,
        "summary": "Do the thing.",
        "session": {"required": True},
        "params": {"type": "object", "properties": {}, "additionalProperties": False},
        "outputs": outputs if outputs is not None else [
            {"name": "thing_id", "type": "string", "description": "The thing."}
        ],
        "timeout_default_s": 30,
    }
    op.update(overrides)
    return op


def write(directory, doc, name=None):
    path = directory / (name or f"{doc.get('binary', 'x')}.json")
    path.write_text(json.dumps(doc))
    return path


def bump_mtime(path):
    """Force a visibly different mtime — two quick writes may otherwise share one."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


class TestAccess:
    def test_the_catalog_is_read_by_binary_name(self, tmp_path):
        write(tmp_path, _catalog())
        assert catalog_for("demo-bin", tmp_path)["binary"] == "demo-bin"

    def test_operations_are_keyed_by_id_and_carry_their_domain(self, tmp_path):
        write(tmp_path, _catalog(operations=[
            _op(id="things.a", domain="things"),
            _op(id="others.b", domain="others"),
        ]))
        ops = operations_for("demo-bin", tmp_path)
        assert sorted(ops) == ["others.b", "things.a"]
        assert ops["things.a"]["domain"] == "things"
        assert ops["others.b"]["domain"] == "others"

    def test_an_entry_keeps_the_legacy_sidecar_shape(self, tmp_path):
        params = {"type": "object", "properties": {"n": {"type": "string"}}}
        write(tmp_path, _catalog(operations=[_op(params=params)]))
        entry = operations_for("demo-bin", tmp_path)["things.doThing"]
        assert entry["summary"] == "Do the thing."
        assert entry["params"] == params
        assert entry["session_required"] is True
        assert entry["timeout_default_s"] == 30
        assert entry["outputs"] == ["thing_id"]

    def test_output_ports_are_typed_from_the_operation(self, tmp_path):
        write(tmp_path, _catalog(operations=[
            _op(outputs=[
                {"name": "one", "type": "string", "description": "d"},
                {"name": "two", "type": "array", "description": "d"},
            ]),
        ]))
        ports = operation_output_ports("demo-bin", "things.doThing", tmp_path)
        assert {p.name: p.data_type for p in ports} == {
            "one": DataType.STRING,
            "two": DataType.ARRAY,
        }

    def test_an_operation_with_no_outputs_is_an_empty_list_not_none(self, tmp_path):
        """[] means "knows there are none"; None means "cannot know"."""
        write(tmp_path, _catalog(operations=[_op(outputs=[])]))
        assert operation_output_ports("demo-bin", "things.doThing", tmp_path) == []

    def test_an_unknown_operation_is_none_not_empty(self, tmp_path):
        write(tmp_path, _catalog())
        assert operation_output_ports("demo-bin", "things.nope", tmp_path) is None

    def test_an_unknown_binary_is_none_everywhere(self, tmp_path):
        assert catalog_for("no-such-bin", tmp_path) is None
        assert operations_for("no-such-bin", tmp_path) is None
        assert operation_output_ports("no-such-bin", "x", tmp_path) is None
        assert config_schema_for("no-such-bin", tmp_path) is None

    def test_a_binary_name_cannot_escape_the_catalog_directory(self, tmp_path):
        """The name arrives from node configuration, so it is caller-controlled."""
        for name in ("../etc", "a/b", "..", "", "."):
            assert catalog_for(name, tmp_path) is None


class TestRefusal:
    def test_an_unknown_protocol_refuses_the_whole_catalog(self, tmp_path):
        """Not just the operations we happen to recognise — the whole document."""
        write(tmp_path, _catalog(protocol=2, operations=[_op(), _op(id="things.b")]))
        assert catalog_for("demo-bin", tmp_path) is None
        assert operations_for("demo-bin", tmp_path) is None

    def test_an_unreadable_catalog_disables_only_its_own_binary(self, tmp_path):
        (tmp_path / "broken-bin.json").write_text("{not json")
        write(tmp_path, _catalog(binary="good-bin"))
        assert catalog_for("broken-bin", tmp_path) is None
        assert sorted(operations_for("good-bin", tmp_path)) == ["things.doThing"]

    def test_a_missing_directory_is_not_an_error(self, tmp_path):
        assert catalog_for("demo-bin", tmp_path / "absent") is None

    def test_an_operation_missing_id_or_domain_skips_itself_only(self, tmp_path):
        broken = _op(id="things.b")
        del broken["domain"]
        write(tmp_path, _catalog(operations=[_op(), broken]))
        assert sorted(operations_for("demo-bin", tmp_path)) == ["things.doThing"]


class TestEnvelopeUnwrapping:
    def test_a_catalog_still_inside_its_envelope_is_accepted(self, tmp_path):
        """The binary writes an envelope to stdout; both forms reach this reader."""
        write(tmp_path, {"ok": True, "data": _catalog(), "proof": None,
                         "slot_patch": None, "error": None}, name="demo-bin.json")
        assert catalog_for("demo-bin", tmp_path)["binary"] == "demo-bin"


class TestFreshness:
    """A catalog registered into a RUNNING process is visible on the next call.

    This is the property the static-type design exists to provide: nothing is
    read at import, so there is nothing a restart would refresh.
    """

    def test_a_catalog_written_after_a_miss_is_found_on_the_next_call(self, tmp_path):
        assert catalog_for("late-bin", tmp_path) is None
        write(tmp_path, _catalog(binary="late-bin"))
        assert catalog_for("late-bin", tmp_path)["binary"] == "late-bin"

    def test_a_rewritten_catalog_is_visible_without_any_reimport(self, tmp_path):
        path = write(tmp_path, _catalog(operations=[
            _op(outputs=[{"name": "a", "type": "string", "description": "d"}]),
        ]))
        before = operation_output_ports("demo-bin", "things.doThing", tmp_path)
        assert [p.name for p in before] == ["a"]

        path.write_text(json.dumps(_catalog(operations=[
            _op(outputs=[
                {"name": "a", "type": "string", "description": "d"},
                {"name": "b", "type": "number", "description": "d"},
            ]),
        ])))
        bump_mtime(path)
        after = operation_output_ports("demo-bin", "things.doThing", tmp_path)
        assert [p.name for p in after] == ["a", "b"]

    def test_a_deleted_catalog_stops_resolving(self, tmp_path):
        path = write(tmp_path, _catalog())
        assert catalog_for("demo-bin", tmp_path) is not None
        path.unlink()
        assert catalog_for("demo-bin", tmp_path) is None

    def test_an_unchanged_file_is_served_from_the_cache(self, tmp_path):
        write(tmp_path, _catalog())
        first = catalog_for("demo-bin", tmp_path)
        assert catalog_for("demo-bin", tmp_path) is first


class TestConfigSchema:
    def test_the_legacy_shape_survives(self, tmp_path):
        """`SchemaConfigForm` consumes this shape unchanged, keyed by binary."""
        write(tmp_path, _catalog(operations=[
            _op(id="things.b", domain="things"),
            _op(id="things.a", domain="things"),
        ]))
        schema = config_schema_for("demo-bin", tmp_path)
        assert schema["properties"]["operation"]["enum"] == ["things.a", "things.b"]
        assert schema["required"] == ["operation"]
        assert schema["x-binary"] == "demo-bin"
        assert "session" in schema["properties"]
        assert "env" in schema["properties"]
        assert schema["x-operations"]["things.a"]["domain"] == "things"


class TestReservedKeys:
    def test_a_parameter_colliding_with_a_platform_key_is_skipped(self, tmp_path):
        """`binary`, `domain`, `operation`, `session`, `env` are the platform's
        own extra_config keys; a catalog parameter of that name would be
        indistinguishable from them."""
        write(tmp_path, _catalog(operations=[_op(params={
            "type": "object",
            "required": ["session", "n"],
            "properties": {
                "session": {"type": "string"},
                "binary": {"type": "string"},
                "n": {"type": "string"},
            },
        })]))
        params = operations_for("demo-bin", tmp_path)["things.doThing"]["params"]
        assert sorted(params["properties"]) == ["n"]
        assert params["required"] == ["n"]
