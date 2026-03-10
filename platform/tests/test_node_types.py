"""Tests for node type registry definitions."""

import pytest

from schemas.node_type_defs import *  # noqa: F401, F403 — trigger registration side effects
from schemas.node_types import NODE_TYPE_REGISTRY


class TestTriggerFilesSchema:
    """Test trigger files port schema."""

    @pytest.mark.parametrize("node_type", ["trigger_telegram", "trigger_chat"])
    def test_trigger_files_port_has_correct_schema(self, node_type):
        """Trigger files port should have url field (not file_id)."""
        spec = NODE_TYPE_REGISTRY[node_type]
        files_port = next((p for p in spec.outputs if p.name == "files"), None)
        assert files_port is not None, f"{node_type} should have a 'files' output port"
        assert files_port.port_schema is not None, "files port should have a schema"

        # Check schema structure
        assert "items" in files_port.port_schema, "files schema should have 'items'"
        items = files_port.port_schema["items"]
        assert "properties" in items, "items should have 'properties'"
        props = items["properties"]

        # Check required fields
        assert "filename" in props, "files schema should have 'filename' field"
        assert "mime_type" in props, "files schema should have 'mime_type' field"
        assert "size_bytes" in props, "files schema should have 'size_bytes' field"
        assert "url" in props, "files schema should have 'url' field (not file_id)"

        # Ensure old fields are not present
        assert "file_id" not in props, "files schema should not have 'file_id' field"
        assert "file_name" not in props, "files schema should not have 'file_name' field"
        assert "file_size" not in props, "files schema should not have 'file_size' field"
