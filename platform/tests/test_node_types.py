"""Tests for node type registry and definitions."""

import pytest

# Force node_type_defs to load so NODE_TYPE_REGISTRY is populated
import schemas.node_type_defs  # noqa: F401
from schemas.node_types import NODE_TYPE_REGISTRY


class TestTriggerDescriptions:
    """Test trigger node type descriptions reference gateway."""

    def test_trigger_telegram_description_contains_gateway(self):
        """trigger_telegram description should mention msg-gateway."""
        spec = NODE_TYPE_REGISTRY["trigger_telegram"]
        assert "gateway" in spec.description.lower(), (
            f"Expected 'gateway' in trigger_telegram description, got: {spec.description}"
        )

    def test_trigger_chat_description_contains_gateway(self):
        """trigger_chat description should mention msg-gateway."""
        spec = NODE_TYPE_REGISTRY["trigger_chat"]
        assert "gateway" in spec.description.lower(), (
            f"Expected 'gateway' in trigger_chat description, got: {spec.description}"
        )


class TestTriggerFilesSchema:
    """Test trigger files port schema."""

    def test_trigger_telegram_files_port_has_correct_schema(self):
        """trigger_telegram files port should have url field (not file_id)."""
        spec = NODE_TYPE_REGISTRY["trigger_telegram"]
        files_port = next((p for p in spec.outputs if p.name == "files"), None)
        assert files_port is not None, "trigger_telegram should have a 'files' output port"
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

    def test_trigger_chat_files_port_has_correct_schema(self):
        """trigger_chat files port should have url field (not file_id)."""
        spec = NODE_TYPE_REGISTRY["trigger_chat"]
        files_port = next((p for p in spec.outputs if p.name == "files"), None)
        assert files_port is not None, "trigger_chat should have a 'files' output port"
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
