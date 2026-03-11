"""Tests for _agent_shared — _resolve_credential_field and _build_backend."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from types import SimpleNamespace

from components._agent_shared import _resolve_credential_field
from models.credential import (
    BaseCredential,
    GitCredential,
    GatewayCredential,
    LLMProviderCredential,
)
from models.workspace import Workspace


def _make_deep_agent_node(system_prompt="", extra_config=None):
    """Build a minimal node-like object for deep_agent_factory."""
    extra = extra_config or {}
    concrete = SimpleNamespace(
        system_prompt=system_prompt,
        extra_config=extra,
        max_tokens=None,
    )
    config = SimpleNamespace(
        component_type="deep_agent",
        extra_config=extra,
        system_prompt=system_prompt,
        concrete=concrete,
    )
    workflow = SimpleNamespace(slug="test-workflow")
    return SimpleNamespace(
        node_id="test_deep_1",
        workflow_id=1,
        workflow=workflow,
        component_type="deep_agent",
        component_config=config,
    )


# ---------------------------------------------------------------------------
# _resolve_credential_field
# ---------------------------------------------------------------------------


class TestResolveCredentialField:
    def test_llm_api_key(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id, api_key="sk-test-123"
        )
        db.add(llm)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "api_key") == "sk-test-123"

    def test_llm_base_url(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id,
            api_key="sk-x",
            base_url="https://api.example.com",
        )
        db.add(llm)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "base_url") == "https://api.example.com"

    def test_llm_organization_id(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id,
            api_key="sk-x",
            organization_id="org-abc",
        )
        db.add(llm)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "organization_id") == "org-abc"

    def test_gateway_credential_id(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="gw", credential_type="gateway"
        )
        db.add(cred)
        db.flush()
        gw = GatewayCredential(
            base_credentials_id=cred.id,
            gateway_credential_id="tg_mybot",
            adapter_type="telegram",
        )
        db.add(gw)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "gateway_credential_id") == "tg_mybot"

    def test_git_access_token(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="git", credential_type="git"
        )
        db.add(cred)
        db.flush()
        git = GitCredential(
            base_credentials_id=cred.id,
            provider="github",
            credential_type="token",
            access_token="ghp_abc123",
        )
        db.add(git)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "access_token") == "ghp_abc123"

    def test_git_ssh_private_key(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="git", credential_type="git"
        )
        db.add(cred)
        db.flush()
        git = GitCredential(
            base_credentials_id=cred.id,
            provider="github",
            credential_type="ssh_key",
            ssh_private_key="-----BEGIN OPENSSH PRIVATE KEY-----\nfake",
        )
        db.add(git)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "ssh_private_key") == "-----BEGIN OPENSSH PRIVATE KEY-----\nfake"

    def test_git_webhook_secret(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="git", credential_type="git"
        )
        db.add(cred)
        db.flush()
        git = GitCredential(
            base_credentials_id=cred.id,
            provider="github",
            credential_type="token",
            webhook_secret="whsec_123",
        )
        db.add(git)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "webhook_secret") == "whsec_123"

    def test_unknown_field_returns_none(self, db, user_profile):
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id, api_key="sk-x"
        )
        db.add(llm)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "nonexistent_field") is None

    def test_missing_child_returns_none(self, db, user_profile):
        """Credential without matching child record returns None."""
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="bare", credential_type="llm"
        )
        db.add(cred)
        db.commit()
        db.refresh(cred)

        assert _resolve_credential_field(cred, "api_key") is None
        assert _resolve_credential_field(cred, "gateway_credential_id") is None
        assert _resolve_credential_field(cred, "access_token") is None


# ---------------------------------------------------------------------------
# _build_backend
# ---------------------------------------------------------------------------


class TestBuildBackend:
    def test_with_workspace_id(self, db, user_profile, tmp_path):
        """workspace_id in extra_config loads workspace from DB."""
        ws_path = str(tmp_path / "workspace")
        ws = Workspace(
            name="test-ws",
            path=ws_path,
            user_profile_id=user_profile.id,
            allow_network=True,
            env_vars=[{"key": "FOO", "value": "bar", "source": "raw"}],
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)

        with patch("database.SessionLocal", return_value=db), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="bwrap", can_execute=True, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": ws.id})

        assert str(backend.cwd) == ws_path
        assert backend._allow_network is True
        assert backend._custom_env == {"FOO": "bar"}

    def test_with_workspace_credential_env(self, db, user_profile, tmp_path):
        """workspace with credential-sourced env vars resolves the credential field."""
        ws_path = str(tmp_path / "workspace")
        cred = BaseCredential(
            user_profile_id=user_profile.id, name="llm-cred", credential_type="llm"
        )
        db.add(cred)
        db.flush()
        llm = LLMProviderCredential(
            base_credentials_id=cred.id, api_key="sk-secret-key"
        )
        db.add(llm)
        db.flush()

        ws = Workspace(
            name="cred-ws",
            path=ws_path,
            user_profile_id=user_profile.id,
            env_vars=[
                {
                    "key": "OPENAI_API_KEY",
                    "source": "credential",
                    "credential_id": cred.id,
                    "credential_field": "api_key",
                },
                {"key": "RAW_VAR", "value": "raw_value", "source": "raw"},
            ],
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)
        db.refresh(cred)

        with patch("database.SessionLocal", return_value=db), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="bwrap", can_execute=True, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": ws.id})

        assert backend._custom_env["OPENAI_API_KEY"] == "sk-secret-key"
        assert backend._custom_env["RAW_VAR"] == "raw_value"

    def test_without_workspace_id(self, tmp_path):
        """No workspace_id falls back to filesystem_root_dir."""
        root = str(tmp_path / "fallback")

        with patch("components.sandboxed_backend.resolve_sandbox_mode",
                    return_value=MagicMock(mode="bwrap", can_execute=True, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"filesystem_root_dir": root})

        assert str(backend.cwd) == root
        assert backend._custom_env == {}

    def test_without_workspace_id_default(self, tmp_path):
        """No workspace_id and no filesystem_root_dir falls back to _get_workspace_dir()."""
        default_dir = str(tmp_path / "default-ws")

        with patch("components._agent_shared._get_workspace_dir", return_value=default_dir), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="bwrap", can_execute=True, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({})

        assert str(backend.cwd) == default_dir

    def test_workspace_not_found_falls_back(self, db, user_profile, tmp_path):
        """Invalid workspace_id falls back to default path."""
        fallback_dir = str(tmp_path / "fallback")

        with patch("database.SessionLocal", return_value=db), \
             patch("components._agent_shared._get_workspace_dir", return_value=fallback_dir), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="bwrap", can_execute=True, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": 99999})

        assert str(backend.cwd) == fallback_dir

    def test_workspace_env_var_empty_key_skipped(self, db, user_profile, tmp_path):
        """Env vars with empty key are skipped."""
        ws_path = str(tmp_path / "workspace")
        ws = Workspace(
            name="skip-ws",
            path=ws_path,
            user_profile_id=user_profile.id,
            env_vars=[
                {"key": "", "value": "should-skip", "source": "raw"},
                {"key": "VALID", "value": "ok", "source": "raw"},
            ],
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)

        with patch("database.SessionLocal", return_value=db), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="bwrap", can_execute=True, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": ws.id})

        assert "" not in backend._custom_env
        assert backend._custom_env == {"VALID": "ok"}

    def test_workspace_credential_env_not_found(self, db, user_profile, tmp_path):
        """Credential-sourced env var with non-existent credential_id is skipped."""
        ws_path = str(tmp_path / "workspace")
        ws = Workspace(
            name="nocred-ws",
            path=ws_path,
            user_profile_id=user_profile.id,
            env_vars=[
                {
                    "key": "MISSING_KEY",
                    "source": "credential",
                    "credential_id": 99999,
                    "credential_field": "api_key",
                },
            ],
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)

        with patch("database.SessionLocal", return_value=db), \
             patch("components.sandboxed_backend.resolve_sandbox_mode",
                   return_value=MagicMock(mode="bwrap", can_execute=True, container_type=None, reason=None)):
            from components._agent_shared import _build_backend
            backend = _build_backend({"workspace_id": ws.id})

        assert "MISSING_KEY" not in backend._custom_env


# ---------------------------------------------------------------------------
# deep_agent_factory — capability injection
# ---------------------------------------------------------------------------


class TestDeepAgentCapabilityInjection:
    def test_capability_injection_failure(self):
        """When detect_capabilities raises, system_prompt is unchanged."""
        node = _make_deep_agent_node(system_prompt="You are helpful.")

        with patch("services.capabilities.detect_capabilities", side_effect=RuntimeError("boom")), \
             patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="test-model"), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent._resolve_skills", return_value=[]), \
             patch("components.deep_agent._get_checkpointer", return_value=None), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch("components.deep_agent._build_backend", return_value=MagicMock()), \
             patch("components.deep_agent.create_deep_agent") as mock_create:
            from components.deep_agent import deep_agent_factory
            deep_agent_factory(node)

        # system_prompt should be passed unchanged (no capability prefix)
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs.get("system_prompt") == "You are helpful."


# ---------------------------------------------------------------------------
# extract_text_content
# ---------------------------------------------------------------------------


class TestExtractTextContent:
    def test_string_input_returned_as_string(self):
        from components._agent_shared import extract_text_content
        assert extract_text_content("hello world") == "hello world"

    def test_list_with_single_text_block(self):
        from components._agent_shared import extract_text_content
        content = [{"type": "text", "text": "The answer"}]
        assert extract_text_content(content) == "The answer"

    def test_list_with_multiple_text_blocks_joined(self):
        from components._agent_shared import extract_text_content
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        result = extract_text_content(content)
        assert result == "Hello\nWorld"

    def test_list_with_thinking_block_filtered_out(self):
        from components._agent_shared import extract_text_content
        content = [
            {"type": "thinking", "thinking": "reasoning...", "signature": "sig123"},
            {"type": "text", "text": "The real answer"},
        ]
        result = extract_text_content(content)
        assert result == "The real answer"

    def test_empty_list_returns_empty_string(self):
        from components._agent_shared import extract_text_content
        assert extract_text_content([]) == ""

    def test_list_with_non_text_types_excluded(self):
        from components._agent_shared import extract_text_content
        content = [{"type": "tool_use", "name": "search", "input": {}}]
        assert extract_text_content(content) == ""

    def test_non_string_non_list_coerced_to_string(self):
        from components._agent_shared import extract_text_content
        assert extract_text_content(42) == "42"


# ---------------------------------------------------------------------------
# strip_thinking_blocks
# ---------------------------------------------------------------------------


class TestStripThinkingBlocks:
    def test_strips_thinking_block_from_ai_message(self):
        from components._agent_shared import strip_thinking_blocks

        msg = MagicMock()
        msg.type = "ai"
        msg.content = [
            {"type": "thinking", "thinking": "internal reasoning", "signature": "sig"},
            {"type": "text", "text": "The response"},
        ]

        result = strip_thinking_blocks([msg])
        assert len(result) == 1
        assert msg.content == [{"type": "text", "text": "The response"}]

    def test_non_ai_messages_left_unchanged(self):
        from components._agent_shared import strip_thinking_blocks

        msg = MagicMock()
        msg.type = "human"
        original_content = [{"type": "text", "text": "User input"}]
        msg.content = original_content

        strip_thinking_blocks([msg])
        assert msg.content is original_content

    def test_ai_message_with_string_content_left_unchanged(self):
        from components._agent_shared import strip_thinking_blocks

        msg = MagicMock()
        msg.type = "ai"
        msg.content = "plain string response"

        strip_thinking_blocks([msg])
        assert msg.content == "plain string response"

    def test_empty_messages_list_returns_empty(self):
        from components._agent_shared import strip_thinking_blocks
        assert strip_thinking_blocks([]) == []

    def test_all_thinking_blocks_removed_leaving_empty_list(self):
        from components._agent_shared import strip_thinking_blocks

        msg = MagicMock()
        msg.type = "ai"
        msg.content = [
            {"type": "thinking", "thinking": "step 1"},
            {"type": "thinking", "thinking": "step 2"},
        ]

        strip_thinking_blocks([msg])
        assert msg.content == []

    def test_message_without_type_attr_skipped(self):
        from components._agent_shared import strip_thinking_blocks

        msg = MagicMock(spec=[])  # no attributes
        result = strip_thinking_blocks([msg])
        assert result == [msg]


# ---------------------------------------------------------------------------
# deep_agent_node — strip_thinking_blocks and extract_text_content calls
# ---------------------------------------------------------------------------


class TestDeepAgentNodeFunction:
    """Test the deep_agent_node closure returned by deep_agent_factory."""

    def _make_node_fn(self, system_prompt=""):
        """Build deep_agent_factory and return the inner node function with a mock agent."""
        node = _make_deep_agent_node(system_prompt=system_prompt)
        mock_agent = MagicMock()

        with patch("components.deep_agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.deep_agent.get_model_name_for_node", return_value="test-model"), \
             patch("components.deep_agent._resolve_tools", return_value=([], {})), \
             patch("components.deep_agent._resolve_skills", return_value=[]), \
             patch("components.deep_agent._get_redis_checkpointer", return_value=None), \
             patch("components.deep_agent._build_backend", return_value=MagicMock()), \
             patch("services.capabilities.detect_capabilities", side_effect=ImportError()), \
             patch("components.deep_agent.create_deep_agent", return_value=mock_agent):
            from components.deep_agent import deep_agent_factory
            node_fn = deep_agent_factory(node)

        return node_fn, mock_agent

    def _invoke_node(self, node_fn, mock_agent, ai_msg_content):
        """Helper: set up mock agent result and invoke node_fn."""
        ai_msg = MagicMock()
        ai_msg.type = "ai"
        ai_msg.content = ai_msg_content
        ai_msg.additional_kwargs = {}

        mock_agent.invoke.return_value = {"messages": [ai_msg]}

        state = {"messages": [], "execution_id": "exec-test-123"}

        with patch("services.context.trim_messages_for_model", side_effect=lambda msgs, *a, **kw: msgs), \
             patch("services.token_usage.extract_usage_from_messages",
                   return_value={"llm_calls": 1, "input_tokens": 10, "output_tokens": 5, "total_tokens": 15}), \
             patch("services.token_usage.calculate_cost", return_value=0.001):
            result = node_fn(state)

        return result, ai_msg

    def test_strip_thinking_blocks_called_on_output(self):
        """Line 223: strip_thinking_blocks(out_messages) removes thinking blocks."""
        node_fn, mock_agent = self._make_node_fn()

        ai_content = [
            {"type": "thinking", "thinking": "internal reasoning", "signature": "sig"},
            {"type": "text", "text": "Final answer"},
        ]
        result, ai_msg = self._invoke_node(node_fn, mock_agent, ai_content)

        # thinking block should be stripped from the message content
        assert ai_msg.content == [{"type": "text", "text": "Final answer"}]

    def test_extract_text_content_called_for_final_output(self):
        """Line 235: extract_text_content(msg.content) extracts text from AI message list."""
        node_fn, mock_agent = self._make_node_fn()

        ai_content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        result, ai_msg = self._invoke_node(node_fn, mock_agent, ai_content)

        # extract_text_content joins text blocks with newline
        assert result["output"] == "Hello\nWorld"

    def test_output_extracted_from_last_ai_message(self):
        """The node function returns the text content from the last AI message."""
        node_fn, mock_agent = self._make_node_fn()

        ai_content = [{"type": "text", "text": "The deep agent response"}]
        result, _ = self._invoke_node(node_fn, mock_agent, ai_content)

        assert result["output"] == "The deep agent response"
