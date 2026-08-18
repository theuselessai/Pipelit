"""Node types derived from binary catalogs.

Fixtures here are deliberately invented — `demo-bin`, `things`, `doThing`. The
real catalogs describe one organisation's operations and are gitignored for that
reason; a test file that hardcoded them would put back exactly what the gitignore
is keeping out.
"""

import json

import pytest

from schemas.binary_catalogs import component_type_for, load_specs
from schemas.binary_verbs import VERB_MARKER
from schemas.node_types import NODE_TYPE_REGISTRY, DataType


def operation_specs(directory):
    """The node types derived from a catalog's OPERATIONS.

    Every plugin also gets an identity node type, which comes from the protocol's
    verb surface rather than from the catalog — see TestIdentityType.
    """
    return [s for s in load_specs(directory) if not s.config_schema.get(VERB_MARKER)]


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


@pytest.fixture
def catalog_dir(tmp_path):
    """A catalog directory, with the registry restored afterwards.

    The registry is process-global, so a test that registers types would leak
    them into every later test in the session.
    """
    before = dict(NODE_TYPE_REGISTRY)
    yield tmp_path
    NODE_TYPE_REGISTRY.clear()
    NODE_TYPE_REGISTRY.update(before)


def write(directory, doc, name=None):
    path = directory / (name or f"{doc.get('binary', 'x')}.json")
    path.write_text(json.dumps(doc))
    return path


class TestDerivation:
    def test_one_node_type_per_domain(self, catalog_dir):
        write(catalog_dir, _catalog(operations=[
            _op(id="things.a", domain="things"),
            _op(id="things.b", domain="things"),
            _op(id="others.c", domain="others"),
        ]))
        specs = operation_specs(catalog_dir)
        assert sorted(s.component_type for s in specs) == [
            "demo_bin_others", "demo_bin_things"
        ]

    def test_ports_are_the_union_of_the_domains_operations(self, catalog_dir):
        write(catalog_dir, _catalog(operations=[
            _op(id="things.a", outputs=[{"name": "one", "type": "string", "description": "d"}]),
            _op(id="things.b", outputs=[{"name": "two", "type": "array", "description": "d"}]),
        ]))
        spec = operation_specs(catalog_dir)[0]
        assert {p.name: p.data_type for p in spec.outputs} == {
            "one": DataType.STRING,
            "two": DataType.ARRAY,
        }

    def test_a_port_declared_with_two_types_widens_to_any(self, catalog_dir):
        """Rather than silently taking whichever operation was read first."""
        write(catalog_dir, _catalog(operations=[
            _op(id="things.a", outputs=[{"name": "x", "type": "string", "description": "d"}]),
            _op(id="things.b", outputs=[{"name": "x", "type": "number", "description": "d"}]),
        ]))
        spec = operation_specs(catalog_dir)[0]
        port = next(p for p in spec.outputs if p.name == "x")
        assert port.data_type is DataType.ANY
        assert "varies by operation" in port.description

    def test_config_schema_carries_each_operations_params(self, catalog_dir):
        params = {"type": "object", "properties": {"n": {"type": "string"}}}
        write(catalog_dir, _catalog(operations=[_op(params=params)]))
        spec = operation_specs(catalog_dir)[0]
        assert spec.config_schema["properties"]["operation"]["enum"] == ["things.doThing"]
        assert spec.config_schema["x-operations"]["things.doThing"]["params"] == params
        assert spec.config_schema["x-binary"] == "demo-bin"


class TestRefusal:
    def test_an_unknown_protocol_refuses_the_whole_catalog(self, catalog_dir):
        """Not just the operations we happen to recognise — the whole document."""
        write(catalog_dir, _catalog(protocol=2, operations=[_op(), _op(id="things.b")]))
        assert load_specs(catalog_dir) == []

    def test_unreadable_catalog_does_not_stop_the_others(self, catalog_dir):
        (catalog_dir / "broken.json").write_text("{not json")
        write(catalog_dir, _catalog(binary="good-bin"))
        assert [s.component_type for s in operation_specs(catalog_dir)] == ["good_bin_things"]

    def test_an_overlong_component_type_is_skipped_not_truncated(self, catalog_dir):
        """component_type is String(30) and the polymorphic discriminator.

        Truncating would collide with a neighbouring domain and load the wrong
        config class, which is worse than the node type being absent.
        """
        long_domain = "d" * 40
        write(catalog_dir, _catalog(operations=[
            _op(id=f"{long_domain}.a", domain=long_domain),
            _op(id="fine.b", domain="fine"),
        ]))
        assert [s.component_type for s in operation_specs(catalog_dir)] == ["demo_bin_fine"]

    def test_missing_directory_is_not_an_error(self, tmp_path):
        assert load_specs(tmp_path / "absent") == []


class TestEnvelopeUnwrapping:
    def test_a_catalog_still_inside_its_envelope_is_accepted(self, catalog_dir):
        """The binary writes an envelope to stdout; both forms reach this loader."""
        write(catalog_dir, {"ok": True, "data": _catalog(), "proof": None,
                            "slot_patch": None, "error": None}, name="wrapped.json")
        assert [s.component_type for s in operation_specs(catalog_dir)] == ["demo_bin_things"]


class TestNaming:
    def test_the_binary_prefixes_the_domain(self):
        """Two binaries with a `funding` domain must not collide."""
        assert component_type_for("a-bin", "funding") != component_type_for("b-bin", "funding")

    def test_hyphens_become_underscores(self):
        assert component_type_for("demo-bin", "things") == "demo_bin_things"


class TestIdentityType:
    def test_every_catalog_also_yields_an_identity_node_type(self, catalog_dir):
        """Identity management is protocol-defined, so a plugin gets it whatever
        its catalog contains — including a catalog with no operations at all in
        the domains a host cares about."""
        write(catalog_dir, _catalog())
        verbs = [s for s in load_specs(catalog_dir) if s.config_schema.get(VERB_MARKER)]
        assert [s.component_type for s in verbs] == ["demo_bin_auth"]

    def test_a_refused_catalog_yields_no_identity_type_either(self, catalog_dir):
        """The plugin is unusable, so offering to log into it would be a lie."""
        write(catalog_dir, _catalog(protocol=2))
        assert load_specs(catalog_dir) == []
