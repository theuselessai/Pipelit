"""Tests for activity indicator — schema, orchestrator metadata, and agent tool enrichment."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── ActivitySummary schema ────────────────────────────────────────────────────


class TestActivitySummary:
    def test_defaults(self):
        from schemas.activity import ActivitySummary

        s = ActivitySummary()
        assert s.total_steps == 0
        assert s.total_duration_ms == 0
        assert s.total_tokens == 0
        assert s.total_cost_usd == 0.0
        assert s.llm_calls == 0
        assert s.tool_invocations == 0

    def test_with_values(self):
        from schemas.activity import ActivitySummary

        s = ActivitySummary(
            total_steps=3,
            total_duration_ms=4500,
            total_tokens=1200,
            total_cost_usd=0.0024,
            llm_calls=2,
            tool_invocations=1,
        )
        assert s.total_steps == 3
        assert s.total_cost_usd == 0.0024

    def test_json_serialization(self):
        from schemas.activity import ActivitySummary

        s = ActivitySummary(total_steps=5, total_tokens=100)
        data = s.model_dump()
        assert data["total_steps"] == 5
        assert data["total_tokens"] == 100


# ── _get_node_meta helper ────────────────────────────────────────────────────


class TestGetNodeMeta:
    def test_known_component_type(self):
        from services.orchestrator import _get_node_meta

        # agent is always registered in node_type_defs
        import schemas.node_type_defs  # noqa: F401 — force registration

        node_info = {"node_id": "agent_abc", "component_type": "agent"}
        meta = _get_node_meta(node_info)
        assert meta["component_type"] == "agent"
        assert meta["display_name"] == "Agent"
        assert meta["node_label"] == "agent_abc"

    def test_unknown_component_type(self):
        from services.orchestrator import _get_node_meta

        node_info = {"node_id": "custom_xyz", "component_type": "unknown_widget"}
        meta = _get_node_meta(node_info)
        assert meta["component_type"] == "unknown_widget"
        assert meta["display_name"] == "unknown_widget"  # fallback to raw type
        assert meta["node_label"] == "custom_xyz"

    def test_empty_node_info(self):
        from services.orchestrator import _get_node_meta

        meta = _get_node_meta({})
        assert meta["component_type"] == ""
        assert meta["node_label"] == ""


# ── Agent tool event enrichment ──────────────────────────────────────────────


class TestPublishToolStatus:
    @patch("schemas.node_types.get_node_type")
    @patch("services.orchestrator._publish_event")
    def test_uses_publish_event_when_execution_id_available(self, mock_publish, mock_get_type):
        from components.agent import _publish_tool_status

        mock_spec = MagicMock()
        mock_spec.display_name = "Web Search"
        mock_get_type.return_value = mock_spec

        _publish_tool_status(
            tool_node_id="ws_123",
            status="running",
            workflow_slug="my-wf",
            agent_node_id="agent_abc",
            tool_name="web_search",
            tool_component_type="web_search",
            execution_id="exec-42",
        )
        mock_publish.assert_called_once()
        args = mock_publish.call_args
        assert args[0][0] == "exec-42"
        assert args[0][1] == "node_status"
        data = args[0][2]
        assert data["node_id"] == "ws_123"
        assert data["status"] == "running"
        assert data["tool_name"] == "web_search"
        assert data["parent_node_id"] == "agent_abc"
        assert data["is_tool_call"] is True
        assert data["component_type"] == "web_search"
        assert data["display_name"] == "Web Search"

    @patch("schemas.node_types.get_node_type")
    @patch("ws.broadcast.broadcast")
    def test_falls_back_to_broadcast_without_execution_id(self, mock_broadcast, mock_get_type):
        from components.agent import _publish_tool_status

        mock_spec = MagicMock()
        mock_spec.display_name = "Calculator"
        mock_get_type.return_value = mock_spec

        _publish_tool_status(
            tool_node_id="calc_1",
            status="success",
            workflow_slug="my-wf",
            agent_node_id="agent_abc",
            tool_name="calculator",
            tool_component_type="calculator",
            execution_id=None,
        )
        mock_broadcast.assert_called_once()
        args = mock_broadcast.call_args
        assert args[0][0] == "workflow:my-wf"
        assert args[0][1] == "node_status"
        data = args[0][2]
        assert data["is_tool_call"] is True
        assert data["tool_name"] == "calculator"

    @patch("schemas.node_types.get_node_type", return_value=None)
    def test_no_slug_logs_warning(self, mock_get_type):
        from components.agent import _publish_tool_status

        with patch("components._agent_shared.logger") as mock_logger:
            _publish_tool_status(
                tool_node_id="tool_1",
                status="running",
                workflow_slug="",
                agent_node_id="agent_abc",
                tool_name="",
                tool_component_type="",
                execution_id=None,
            )
            mock_logger.warning.assert_called()


class TestPipelitAgentMiddlewareToolCall:
    def _make_middleware(self, tool_metadata=None, agent_node_id="agent_1", workflow_slug="wf"):
        from components.agent import PipelitAgentMiddleware

        return PipelitAgentMiddleware(
            tool_metadata=tool_metadata or {},
            agent_node_id=agent_node_id,
            workflow_slug=workflow_slug,
        )

    def test_publishes_running_and_success(self):
        middleware = self._make_middleware(
            tool_metadata={"test_tool": {"tool_node_id": "tool_1", "component_type": "run_command"}},
        )
        mock_request = MagicMock()
        mock_request.tool_call = {"name": "test_tool"}
        mock_request.state = {"execution_id": "exec-99"}

        mock_handler = MagicMock(return_value="result")

        with patch("components._agent_shared._publish_tool_status") as mock_publish:
            result = middleware.wrap_tool_call(mock_request, mock_handler)

        assert result == "result"
        assert mock_publish.call_count == 2  # running + success
        assert mock_publish.call_args_list[0].kwargs["status"] == "running"
        assert mock_publish.call_args_list[0].kwargs["execution_id"] == "exec-99"
        assert mock_publish.call_args_list[1].kwargs["status"] == "success"

    def test_publishes_running_and_failed_on_error(self):
        middleware = self._make_middleware(
            tool_metadata={"bad_tool": {"tool_node_id": "tool_1", "component_type": ""}},
        )
        mock_request = MagicMock()
        mock_request.tool_call = {"name": "bad_tool"}
        mock_request.state = {"execution_id": "exec-99"}

        mock_handler = MagicMock(side_effect=ValueError("boom"))

        with patch("components._agent_shared._publish_tool_status") as mock_publish:
            with pytest.raises(ValueError, match="boom"):
                middleware.wrap_tool_call(mock_request, mock_handler)

        assert mock_publish.call_count == 2  # running + failed
        assert mock_publish.call_args_list[1].kwargs["status"] == "failed"

    def test_publishes_running_and_waiting_on_graph_interrupt(self):
        from langgraph.errors import GraphInterrupt

        middleware = self._make_middleware(
            tool_metadata={"spawn_tool": {"tool_node_id": "tool_1", "component_type": "spawn_and_await"}},
        )
        mock_request = MagicMock()
        mock_request.tool_call = {"name": "spawn_tool"}
        mock_request.state = {"execution_id": "exec-99"}

        mock_handler = MagicMock(side_effect=GraphInterrupt([]))

        with patch("components._agent_shared._publish_tool_status") as mock_publish:
            with pytest.raises(GraphInterrupt):
                middleware.wrap_tool_call(mock_request, mock_handler)

        assert mock_publish.call_count == 2  # running + waiting
        assert mock_publish.call_args_list[1].kwargs["status"] == "waiting"

    def test_unknown_tool_degrades_gracefully(self):
        middleware = self._make_middleware(tool_metadata={})
        mock_request = MagicMock()
        mock_request.tool_call = {"name": "unknown_tool"}
        mock_request.state = {"execution_id": "exec-99"}

        mock_handler = MagicMock(return_value="ok")

        with patch("components._agent_shared._publish_tool_status") as mock_publish:
            result = middleware.wrap_tool_call(mock_request, mock_handler)

        assert result == "ok"
        assert mock_publish.call_count == 2
        # Unknown tools get a synthetic _builtin_ prefix node ID
        assert mock_publish.call_args_list[0].kwargs["tool_node_id"] == "_builtin_unknown_tool"
        assert mock_publish.call_args_list[0].kwargs["tool_component_type"] == ""
