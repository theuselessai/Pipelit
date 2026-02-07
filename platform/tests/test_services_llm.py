"""Tests for services/llm.py — LLM factory and resolution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.llm import create_llm_from_db, resolve_llm_for_node


# ── create_llm_from_db ────────────────────────────────────────────────────────

class TestCreateLlmFromDb:
    @patch("services.llm.ChatOpenAI", create=True)
    def test_openai_provider(self, mock_cls):
        # Patch the import
        with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=mock_cls)}):
            cred = SimpleNamespace(provider_type="openai", api_key="sk-test")
            create_llm_from_db(cred, "gpt-4")
            mock_cls.assert_called_once_with(api_key="sk-test", model="gpt-4")

    @patch("services.llm.ChatOpenAI", create=True)
    def test_openai_with_all_params(self, mock_cls):
        with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=mock_cls)}):
            cred = SimpleNamespace(provider_type="openai", api_key="sk-test")
            create_llm_from_db(
                cred, "gpt-4",
                temperature=0.7,
                max_tokens=100,
                frequency_penalty=0.5,
                presence_penalty=0.3,
                top_p=0.9,
                timeout=30,
                max_retries=2,
                response_format={"type": "json_object"},
            )
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["temperature"] == 0.7
            assert call_kwargs["max_tokens"] == 100
            assert call_kwargs["frequency_penalty"] == 0.5
            assert call_kwargs["presence_penalty"] == 0.3
            assert call_kwargs["top_p"] == 0.9
            assert call_kwargs["timeout"] == 30
            assert call_kwargs["max_retries"] == 2
            assert call_kwargs["model_kwargs"] == {"response_format": {"type": "json_object"}}

    @patch("services.llm.ChatAnthropic", create=True)
    def test_anthropic_provider(self, mock_cls):
        with patch.dict("sys.modules", {"langchain_anthropic": MagicMock(ChatAnthropic=mock_cls)}):
            cred = SimpleNamespace(provider_type="anthropic", api_key="sk-ant-test")
            create_llm_from_db(cred, "claude-3-opus-20240229")
            mock_cls.assert_called_once_with(api_key="sk-ant-test", model="claude-3-opus-20240229")

    @patch("services.llm.ChatOpenAI", create=True)
    def test_openai_compatible_provider(self, mock_cls):
        with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=mock_cls)}):
            cred = SimpleNamespace(
                provider_type="openai_compatible",
                api_key="custom-key",
                base_url="http://localhost:11434/v1",
            )
            create_llm_from_db(cred, "llama2")
            mock_cls.assert_called_once_with(
                api_key="custom-key",
                base_url="http://localhost:11434/v1",
                model="llama2",
            )

    @patch("services.llm.ChatOpenAI", create=True)
    def test_openai_compatible_with_params(self, mock_cls):
        with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=mock_cls)}):
            cred = SimpleNamespace(
                provider_type="openai_compatible",
                api_key="key",
                base_url="http://test/v1",
            )
            create_llm_from_db(
                cred, "model",
                frequency_penalty=0.1,
                presence_penalty=0.2,
                response_format={"type": "json"},
            )
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["frequency_penalty"] == 0.1
            assert call_kwargs["presence_penalty"] == 0.2
            assert call_kwargs["model_kwargs"] == {"response_format": {"type": "json"}}

    def test_unsupported_provider(self):
        cred = SimpleNamespace(provider_type="unknown_provider", api_key="key")
        with pytest.raises(ValueError, match="Unsupported provider"):
            create_llm_from_db(cred, "model")


# ── resolve_llm_for_node ──────────────────────────────────────────────────────

class TestResolveLlmForNode:
    @patch("services.llm.create_llm_from_db")
    def test_ai_model_node(self, mock_create):
        mock_create.return_value = MagicMock()

        cc = SimpleNamespace(
            component_type="ai_model",
            model_name="gpt-4",
            llm_credential_id=10,
            temperature=0.5,
            max_tokens=200,
            frequency_penalty=None,
            presence_penalty=None,
            top_p=None,
            timeout=None,
            max_retries=None,
            response_format=None,
            llm_model_config_id=None,
        )
        node = SimpleNamespace(node_id="model_1", component_config=cc)

        mock_db = MagicMock()
        mock_base_cred = MagicMock()
        mock_base_cred.llm_credential = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_base_cred

        result = resolve_llm_for_node(node, db=mock_db)
        mock_create.assert_called_once()
        assert mock_create.call_args[0][1] == "gpt-4"

    def test_ai_model_missing_config(self):
        cc = SimpleNamespace(
            component_type="ai_model",
            model_name="",
            llm_credential_id=None,
        )
        node = SimpleNamespace(node_id="model_1", component_config=cc)
        mock_db = MagicMock()

        with pytest.raises(ValueError, match="requires both"):
            resolve_llm_for_node(node, db=mock_db)

    @patch("services.llm.create_llm_from_db")
    def test_resolve_via_llm_model_config_id(self, mock_create):
        mock_create.return_value = MagicMock()

        # Agent node with llm_model_config_id pointing to ai_model config
        cc = SimpleNamespace(
            component_type="agent",
            model_name=None,
            llm_credential_id=None,
            llm_model_config_id=42,
        )
        node = SimpleNamespace(node_id="agent_1", component_config=cc)

        ai_model_config = SimpleNamespace(
            component_type="ai_model",
            model_name="claude-3-sonnet",
            llm_credential_id=5,
            temperature=0.3,
            max_tokens=500,
            frequency_penalty=None,
            presence_penalty=None,
            top_p=None,
            timeout=None,
            max_retries=None,
            response_format=None,
        )

        mock_db = MagicMock()
        mock_db.get.return_value = ai_model_config
        mock_base_cred = MagicMock()
        mock_base_cred.llm_credential = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_base_cred

        resolve_llm_for_node(node, db=mock_db)
        mock_create.assert_called_once()
        assert mock_create.call_args[0][1] == "claude-3-sonnet"

    def test_no_model_config_raises(self):
        cc = SimpleNamespace(
            component_type="agent",
            model_name=None,
            llm_credential_id=None,
            llm_model_config_id=None,
        )
        node = SimpleNamespace(node_id="agent_1", component_config=cc)
        mock_db = MagicMock()

        with pytest.raises(ValueError, match="no connected ai_model"):
            resolve_llm_for_node(node, db=mock_db)

    @patch("services.llm.create_llm_from_db")
    def test_creates_own_session_when_none(self, mock_create):
        mock_create.return_value = MagicMock()
        mock_db = MagicMock()

        cc = SimpleNamespace(
            component_type="ai_model",
            model_name="gpt-4",
            llm_credential_id=10,
            temperature=None, max_tokens=None, frequency_penalty=None,
            presence_penalty=None, top_p=None, timeout=None,
            max_retries=None, response_format=None, llm_model_config_id=None,
        )
        node = SimpleNamespace(node_id="model_1", component_config=cc)
        mock_base_cred = MagicMock()
        mock_base_cred.llm_credential = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_base_cred

        # Patch the SessionLocal that gets lazily imported inside resolve_llm_for_node
        with patch("database.SessionLocal", return_value=mock_db):
            resolve_llm_for_node(node, db=None)
        mock_create.assert_called_once()

    def test_llm_model_config_not_ai_model(self):
        """When llm_model_config_id points to a non-ai_model config, should raise."""
        cc = SimpleNamespace(
            component_type="agent",
            model_name=None,
            llm_credential_id=None,
            llm_model_config_id=42,
        )
        node = SimpleNamespace(node_id="agent_1", component_config=cc)

        non_ai_config = SimpleNamespace(
            component_type="agent",  # Not ai_model
            model_name=None,
            llm_credential_id=None,
        )

        mock_db = MagicMock()
        mock_db.get.return_value = non_ai_config

        with pytest.raises(ValueError, match="no connected ai_model"):
            resolve_llm_for_node(node, db=mock_db)
