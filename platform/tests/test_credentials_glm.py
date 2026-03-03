"""Tests for credentials API — GLM provider coverage."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class TestGLMCredential:
    """Test GLM provider in credentials API."""

    @patch("api.credentials.httpx.get")
    def test_glm_test_credential_success(self, mock_get):
        """Test GLM credential test with valid API key returns success."""
        from api.credentials import test_credential
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "glm-4"}]}
        mock_get.return_value = mock_response
        
        cred = SimpleNamespace(
            provider_type="glm",
            api_key="test-key",
            base_url="",
        )
        
        result = test_credential(cred)
        assert result == {"ok": True}

    @patch("api.credentials.httpx.get")
    def test_glm_test_credential_with_custom_url(self, mock_get):
        """Test GLM credential test with custom base URL."""
        from api.credentials import test_credential
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        cred = SimpleNamespace(
            provider_type="glm",
            api_key="test-key",
            base_url="https://custom.glm.api/v4",
        )
        
        result = test_credential(cred)
        # Verify custom URL was used
        call_url = mock_get.call_args[0][0]
        assert "custom.glm.api" in call_url

    @patch("api.credentials.httpx.get")
    def test_glm_list_models(self, mock_get):
        """Test listing GLM models."""
        from api.credentials import list_credential_models
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "glm-4", "object": "model"},
                {"id": "glm-4-plus", "object": "model"},
            ]
        }
        mock_get.return_value = mock_response
        
        cred = SimpleNamespace(
            provider_type="glm",
            api_key="test-key",
            base_url="",
        )
        
        result = list_credential_models(cred)
        
        assert result == [
            {"id": "glm-4", "name": "GLM-4"},
            {"id": "glm-4-plus", "name": "GLM-4-PLUS"},
        ]
