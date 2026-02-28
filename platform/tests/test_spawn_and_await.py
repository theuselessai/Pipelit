"""Tests for spawn_and_await tool, checkpointer selection, interrupt/resume flow, and cost sync."""

from __future__ import annotations

import json
import unittest.mock
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from models.epic import Epic, Task
from models.execution import WorkflowExecution


def _make_node(component_type, workflow_id, node_id="tool_node_1"):
    config = SimpleNamespace(
        component_type=component_type,
        extra_config={},
        system_prompt="",
        concrete=SimpleNamespace(
            system_prompt="",
            extra_config={},
        ),
    )
    # Make config.concrete return config itself for attribute access
    config.concrete = config
    return SimpleNamespace(
        node_id=node_id,
        workflow_id=workflow_id,
        component_type=component_type,
        component_config=config,
        workflow=SimpleNamespace(slug="test-wf"),
    )


@pytest.fixture
def mock_session(db):
    """Patch SessionLocal to return the test db session with close() as no-op."""
    original_close = db.close
    db.close = lambda: None
    with patch("database.SessionLocal", return_value=db):
        yield db
    db.close = original_close


# ---------------------------------------------------------------------------
# PipelitAgentMiddleware.wrap_model_call (replaces AgentMessageCallback)
# ---------------------------------------------------------------------------


class TestPipelitAgentMiddlewareModelCall:
    """Test the PipelitAgentMiddleware.wrap_model_call that publishes chat_message WS events."""

    def _make_middleware(self, agent_node_id="agent_1", workflow_slug="test-wf"):
        from components.agent import PipelitAgentMiddleware

        return PipelitAgentMiddleware(
            tool_metadata={},
            agent_node_id=agent_node_id,
            workflow_slug=workflow_slug,
        )

    def _make_model_response(self, content):
        """Build a mock ModelResponse with the given AI message content."""
        msg = MagicMock()
        msg.content = content
        response = MagicMock()
        response.result = [msg]
        return response

    def test_publishes_chat_message_after_llm_response(self):
        middleware = self._make_middleware()
        response = self._make_model_response("Hello, world!")
        mock_request = MagicMock()
        mock_request.state = {"execution_id": "exec-1"}
        mock_handler = MagicMock(return_value=response)

        with patch("services.orchestrator._publish_event") as mock_pub:
            result = middleware.wrap_model_call(mock_request, mock_handler)

        assert result is response
        mock_pub.assert_called_once()
        call_args = mock_pub.call_args
        assert call_args[0][0] == "exec-1"
        assert call_args[0][1] == "chat_message"
        assert call_args[0][2]["text"] == "Hello, world!"
        assert call_args[0][2]["node_id"] == "agent_1"
        assert call_args[1]["workflow_slug"] == "test-wf"

    def test_handles_anthropic_list_format(self):
        middleware = self._make_middleware()
        content = [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]
        response = self._make_model_response(content)
        mock_request = MagicMock()
        mock_request.state = {"execution_id": "exec-1"}
        mock_handler = MagicMock(return_value=response)

        with patch("services.orchestrator._publish_event") as mock_pub:
            middleware.wrap_model_call(mock_request, mock_handler)

        mock_pub.assert_called_once()
        assert mock_pub.call_args[0][2]["text"] == "hello\nworld"

    def test_skips_empty_content(self):
        middleware = self._make_middleware()
        response = self._make_model_response("")
        mock_request = MagicMock()
        mock_request.state = {"execution_id": "exec-1"}
        mock_handler = MagicMock(return_value=response)

        with patch("services.orchestrator._publish_event") as mock_pub:
            middleware.wrap_model_call(mock_request, mock_handler)

        mock_pub.assert_not_called()

    def test_skips_none_content(self):
        middleware = self._make_middleware()
        response = self._make_model_response(None)
        mock_request = MagicMock()
        mock_request.state = {"execution_id": "exec-1"}
        mock_handler = MagicMock(return_value=response)

        with patch("services.orchestrator._publish_event") as mock_pub:
            middleware.wrap_model_call(mock_request, mock_handler)

        mock_pub.assert_not_called()

    def test_swallows_exceptions(self):
        middleware = self._make_middleware()
        response = self._make_model_response("test")
        mock_request = MagicMock()
        mock_request.state = {"execution_id": "exec-1"}
        mock_handler = MagicMock(return_value=response)

        with patch("services.orchestrator._publish_event", side_effect=RuntimeError("publish failed")):
            result = middleware.wrap_model_call(mock_request, mock_handler)

        # Should not raise, and should still return the response
        assert result is response

    def test_skips_without_exec_id(self):
        middleware = self._make_middleware()
        response = self._make_model_response("test")
        mock_request = MagicMock()
        mock_request.state = {}
        mock_handler = MagicMock(return_value=response)

        with patch("services.orchestrator._publish_event") as mock_pub:
            middleware.wrap_model_call(mock_request, mock_handler)

        mock_pub.assert_not_called()


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


class TestSpawnAndAwaitFactory:
    def test_returns_list_with_one_tool(self):
        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tools = spawn_and_await_factory(node)

        assert isinstance(tools, list)
        assert len(tools) == 1
        assert tools[0].name == "spawn_and_await"

    def test_tool_has_tasks_list_parameter(self):
        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tools = spawn_and_await_factory(node)
        tool = tools[0]

        # Check that tool has 'tasks' parameter in its schema
        schema = tool.args_schema.model_json_schema() if hasattr(tool, "args_schema") else {}
        props = schema.get("properties", {})
        assert "tasks" in props
        # Should NOT have old single-task params
        assert "workflow_slug" not in props
        assert "input_text" not in props


# ---------------------------------------------------------------------------
# Checkpointer selection
# ---------------------------------------------------------------------------


class TestCheckpointerSelection:
    """Test dual checkpointer selection logic in agent_factory."""

    def _build_agent(self, conversation_memory=False, has_spawn_tool=False):
        """Call real agent_factory and capture the checkpointer it selected."""
        from components.agent import agent_factory

        mock_tools = []
        if has_spawn_tool:
            mock_spawn = MagicMock()
            mock_spawn.name = "spawn_and_await"
            mock_tools.append(mock_spawn)

        mock_sqlite = MagicMock(name="sqlite_checkpointer")
        mock_redis = MagicMock(name="redis_checkpointer")

        node = _make_node("agent", workflow_id=1)
        node.component_config.extra_config = {"conversation_memory": conversation_memory}
        node.component_config.concrete.extra_config = {"conversation_memory": conversation_memory}

        captured = {}

        def capture_create_agent(**kwargs):
            captured["checkpointer"] = kwargs.get("checkpointer")
            return MagicMock()

        with patch("components.agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.agent._resolve_tools", return_value=(mock_tools, {})), \
             patch("components.agent.create_agent", side_effect=capture_create_agent), \
             patch("components.agent._get_checkpointer", return_value=mock_sqlite), \
             patch("components.agent._get_redis_checkpointer", return_value=mock_redis):
            agent_factory(node)

        return captured.get("checkpointer"), mock_sqlite, mock_redis

    def test_no_memory_no_spawn_returns_none(self):
        checkpointer, _, _ = self._build_agent(conversation_memory=False, has_spawn_tool=False)
        assert checkpointer is None

    def test_conversation_memory_returns_sqlite(self):
        checkpointer, mock_sqlite, _ = self._build_agent(conversation_memory=True, has_spawn_tool=False)
        assert checkpointer is mock_sqlite

    def test_spawn_tool_returns_redis(self):
        checkpointer, _, mock_redis = self._build_agent(conversation_memory=False, has_spawn_tool=True)
        assert checkpointer is mock_redis

    def test_both_prefers_sqlite(self):
        checkpointer, mock_sqlite, _ = self._build_agent(conversation_memory=True, has_spawn_tool=True)
        assert checkpointer is mock_sqlite


class TestAgentFactoryInputValidation:
    """Test that agent_factory handles invalid extra_config values gracefully."""

    def _build_with_config(self, extra_config):
        """Call agent_factory with given extra_config, all external deps mocked."""
        from components.agent import agent_factory

        node = _make_node("agent", workflow_id=1)
        node.component_config.extra_config = extra_config
        node.component_config.concrete.extra_config = extra_config

        captured = {}

        def capture_create_agent(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch("components.agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.agent._resolve_tools", return_value=([], {})), \
             patch("components.agent.create_agent", side_effect=capture_create_agent), \
             patch("components.agent._get_checkpointer", return_value=MagicMock()), \
             patch("components.agent._get_redis_checkpointer", return_value=MagicMock()):
            fn = agent_factory(node)

        return fn, captured

    def test_invalid_context_window_string_falls_back_to_none(self):
        fn, _ = self._build_with_config({"context_window": "not-a-number"})
        assert callable(fn)

    def test_invalid_compacting_trigger_falls_back_to_default(self):
        import sys

        mock_summarization_cls = MagicMock()
        mock_mw_module = MagicMock()
        mock_mw_module.SummarizationMiddleware = mock_summarization_cls

        extra = {"compacting": "summarize", "compacting_trigger": "bad"}
        node = _make_node("agent", workflow_id=1)
        node.component_config.extra_config = extra
        node.component_config.concrete.extra_config = extra

        with patch("components.agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.agent._resolve_tools", return_value=([], {})), \
             patch("components.agent.create_agent", return_value=MagicMock()), \
             patch("components.agent._get_checkpointer", return_value=MagicMock()), \
             patch("components.agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch.dict(sys.modules, {"langchain.agents.middleware": mock_mw_module}):
            from components.agent import agent_factory
            agent_factory(node)

        mock_summarization_cls.assert_called_once()
        call_kwargs = mock_summarization_cls.call_args[1]
        assert call_kwargs["trigger"] == ("fraction", 0.7)

    def test_invalid_compacting_keep_falls_back_to_default(self):
        import sys

        mock_summarization_cls = MagicMock()
        mock_mw_module = MagicMock()
        mock_mw_module.SummarizationMiddleware = mock_summarization_cls

        extra = {"compacting": "summarize", "compacting_keep": "bad"}
        node = _make_node("agent", workflow_id=1)
        node.component_config.extra_config = extra
        node.component_config.concrete.extra_config = extra

        with patch("components.agent.resolve_llm_for_node", return_value=MagicMock()), \
             patch("components.agent._resolve_tools", return_value=([], {})), \
             patch("components.agent.create_agent", return_value=MagicMock()), \
             patch("components.agent._get_checkpointer", return_value=MagicMock()), \
             patch("components.agent._get_redis_checkpointer", return_value=MagicMock()), \
             patch.dict(sys.modules, {"langchain.agents.middleware": mock_mw_module}):
            from components.agent import agent_factory
            agent_factory(node)

        mock_summarization_cls.assert_called_once()
        call_kwargs = mock_summarization_cls.call_args[1]
        assert call_kwargs["keep"] == ("messages", 20)


# ---------------------------------------------------------------------------
# Interrupt flow — parallel spawn
# ---------------------------------------------------------------------------


class TestInterruptFlow:
    """Test that GraphInterrupt from spawn_and_await is caught and creates child executions."""

    def test_creates_multiple_children(self, mock_session, workflow, user_profile):
        from components.agent import _create_child_from_interrupt

        # Create target workflows
        from models.workflow import Workflow
        target_wf = Workflow(
            name="Child Workflow",
            slug="child-workflow",
            owner_id=user_profile.id,
            is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()
        mock_session.refresh(target_wf)

        # Create parent execution
        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={"text": "test"},
            thread_id="test-thread",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
            "_spawn_depth": 0,
        }

        child_ids = []
        for i in range(2):
            task_data = {
                "workflow_slug": "child-workflow",
                "input_text": f"Task {i}",
            }
            with patch("redis.from_url", return_value=MagicMock()), \
                 patch("rq.Queue", return_value=MagicMock()):
                child_id = _create_child_from_interrupt(task_data, state, "agent_1")
                child_ids.append(child_id)

        assert len(child_ids) == 2

        # Verify both child executions were created
        for child_id in child_ids:
            child_exec = (
                mock_session.query(WorkflowExecution)
                .filter(WorkflowExecution.execution_id == child_id)
                .first()
            )
            assert child_exec is not None
            assert child_exec.parent_execution_id == str(parent_exec.execution_id)
            assert child_exec.parent_node_id == "agent_1"
            assert child_exec.workflow_id == target_wf.id
            # Verify spawn_depth is incremented in trigger payload
            assert child_exec.trigger_payload.get("_spawn_depth") == 1

    def test_self_slug_resolves_to_parent_workflow(self, mock_session, workflow, user_profile):
        from components.agent import _create_child_from_interrupt

        # Create parent execution with trigger_node_id
        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={"text": "test"},
            thread_id="test-thread",
            trigger_node_id=42,
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
            "_spawn_depth": 0,
        }
        task_data = {
            "workflow_slug": "self",
            "input_text": "Do something",
        }

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            child_id = _create_child_from_interrupt(task_data, state, "agent_1")

        child_exec = (
            mock_session.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == child_id)
            .first()
        )
        assert child_exec is not None
        assert child_exec.workflow_id == workflow.id
        # Child should inherit trigger_node_id from parent
        assert child_exec.trigger_node_id == 42

    def test_non_self_spawn_finds_trigger_workflow_node(self, mock_session, workflow, user_profile):
        """Non-self spawn should look up the target workflow's trigger_workflow node."""
        from components.agent import _create_child_from_interrupt
        from models.node import BaseComponentConfig, WorkflowNode

        # Create target workflow with a trigger_workflow node
        from models.workflow import Workflow
        target_wf = Workflow(
            name="Target WF",
            slug="target-wf-trigger",
            owner_id=user_profile.id,
            is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()
        mock_session.refresh(target_wf)

        # Create a trigger_workflow node on the target workflow
        config = BaseComponentConfig(component_type="trigger_workflow")
        mock_session.add(config)
        mock_session.flush()

        tw_node = WorkflowNode(
            workflow_id=target_wf.id,
            node_id="trigger_workflow_abc",
            component_type="trigger_workflow",
            component_config_id=config.id,
        )
        mock_session.add(tw_node)
        mock_session.commit()
        mock_session.refresh(tw_node)

        # Create parent execution (no trigger_node_id — non-self spawn)
        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={"text": "test"},
            thread_id="test-thread",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
            "_spawn_depth": 0,
        }
        task_data = {
            "workflow_slug": "target-wf-trigger",
            "input_text": "Do something",
        }

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            child_id = _create_child_from_interrupt(task_data, state, "agent_1")

        child_exec = (
            mock_session.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == child_id)
            .first()
        )
        assert child_exec is not None
        assert child_exec.workflow_id == target_wf.id
        # Should have resolved trigger_node_id from the target's trigger_workflow node
        assert child_exec.trigger_node_id == tw_node.id

    def test_non_self_spawn_no_trigger_workflow_node(self, mock_session, workflow, user_profile):
        """Non-self spawn with no trigger_workflow node leaves trigger_node_id as None."""
        from components.agent import _create_child_from_interrupt

        # Create target workflow WITHOUT a trigger_workflow node
        from models.workflow import Workflow
        target_wf = Workflow(
            name="No Trigger WF",
            slug="no-trigger-wf",
            owner_id=user_profile.id,
            is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()
        mock_session.refresh(target_wf)

        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={"text": "test"},
            thread_id="test-thread",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
            "_spawn_depth": 0,
        }
        task_data = {
            "workflow_slug": "no-trigger-wf",
            "input_text": "Do something",
        }

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            child_id = _create_child_from_interrupt(task_data, state, "agent_1")

        child_exec = (
            mock_session.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == child_id)
            .first()
        )
        assert child_exec is not None
        assert child_exec.workflow_id == target_wf.id
        # No trigger_workflow node → trigger_node_id stays None
        assert child_exec.trigger_node_id is None

    def test_interrupt_raises_on_missing_workflow(self, mock_session, workflow, user_profile):
        from components.agent import _create_child_from_interrupt

        state = {
            "execution_id": "test-exec-id",
            "user_context": {"user_profile_id": user_profile.id},
        }
        task_data = {
            "workflow_slug": "nonexistent-workflow",
        }

        with pytest.raises(ValueError, match="target workflow not found"):
            _create_child_from_interrupt(task_data, state, "agent_1")

    def test_try_create_children_exception_returns_error(self):
        """When _create_child_from_interrupt raises, _try_create_children returns error output."""
        from components.agent import _try_create_children

        interrupt_data = {
            "tasks": [{"workflow_slug": "wf1", "input_text": "test"}],
        }
        state = {
            "execution_id": "exec-1",
            "user_context": {"user_profile_id": 1},
            "_spawn_depth": 0,
        }

        with patch(
            "components.agent._create_child_from_interrupt",
            side_effect=RuntimeError("DB connection failed"),
        ):
            result = _try_create_children(interrupt_data, state, "agent_1")

        assert "output" in result
        assert "spawn_and_await failed" in result["output"]


# ---------------------------------------------------------------------------
# Spawn depth limit
# ---------------------------------------------------------------------------


class TestSpawnDepthLimit:
    """Test depth limit prevents infinite spawn chains."""

    def test_depth_limit_blocks_spawning(self):
        from components.agent import MAX_SPAWN_DEPTH, _try_create_children

        interrupt_data = {
            "tasks": [{"workflow_slug": "child-wf", "input_text": "test"}],
        }
        state = {
            "execution_id": "exec-1",
            "user_context": {"user_profile_id": 1},
            "_spawn_depth": MAX_SPAWN_DEPTH,
        }

        result = _try_create_children(interrupt_data, state, "agent_1")

        # Should return error output, not create children
        assert "output" in result
        assert "depth limit" in result["output"].lower()

    def test_depth_increments_per_level(self, mock_session, workflow, user_profile):
        from components.agent import _create_child_from_interrupt
        from models.workflow import Workflow

        target_wf = Workflow(
            name="Child", slug="child-wf", owner_id=user_profile.id, is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()

        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
            "_spawn_depth": 2,
        }
        task_data = {"workflow_slug": "child-wf", "input_text": "test"}

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            child_id = _create_child_from_interrupt(task_data, state, "agent_1")

        child_exec = (
            mock_session.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == child_id)
            .first()
        )
        assert child_exec.trigger_payload["_spawn_depth"] == 3

    def test_no_tasks_returns_error(self):
        from components.agent import _try_create_children

        result = _try_create_children({"tasks": []}, {"_spawn_depth": 0}, "agent_1")
        assert "output" in result
        assert "no tasks" in result["output"]


# ---------------------------------------------------------------------------
# Checkpoint isolation for child executions
# ---------------------------------------------------------------------------


class TestCheckpointIsolation:
    """Test that child executions use execution-scoped thread_id."""

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_agent")
    @patch("components.agent._get_checkpointer")
    def test_child_execution_uses_exec_scoped_thread(
        self, mock_get_sqlite, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        from components.agent import agent_factory

        mock_resolve_llm.return_value = MagicMock()
        mock_spawn = MagicMock()
        mock_spawn.name = "spawn_and_await"
        mock_resolve_tools.return_value = ([mock_spawn], {"spawn_and_await": {"tool_node_id": "spawn_1", "component_type": "spawn_and_await"}})
        mock_checkpointer = MagicMock()
        mock_get_sqlite.return_value = mock_checkpointer

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="done", additional_kwargs={})],
        }
        mock_create_agent.return_value = mock_agent

        node = _make_node("agent", workflow_id=1, node_id="agent_1")
        node.component_config.extra_config = {"conversation_memory": True}
        node.component_config.concrete.extra_config = {"conversation_memory": True}
        agent_node = agent_factory(node)

        # Simulate child execution state
        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "child-exec-123",
            "_is_child_execution": True,
            "user_context": {"user_profile_id": 1, "telegram_chat_id": "chat-456"},
        }

        agent_node(state)

        # Verify thread_id is execution-scoped, NOT conversation-scoped
        config_arg = mock_agent.invoke.call_args
        config = config_arg[1].get("config") or config_arg[0][1]
        assert config["configurable"]["thread_id"] == "exec:child-exec-123:agent_1"

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_agent")
    @patch("components.agent._get_checkpointer")
    def test_parent_execution_uses_conversation_thread(
        self, mock_get_sqlite, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        from components.agent import agent_factory

        mock_resolve_llm.return_value = MagicMock()
        mock_resolve_tools.return_value = ([], {})
        mock_checkpointer = MagicMock()
        mock_get_sqlite.return_value = mock_checkpointer

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="done", additional_kwargs={})],
        }
        mock_create_agent.return_value = mock_agent

        node = _make_node("agent", workflow_id=1, node_id="agent_1")
        node.component_config.extra_config = {"conversation_memory": True}
        node.component_config.concrete.extra_config = {"conversation_memory": True}
        agent_node = agent_factory(node)

        # Simulate parent execution state (NOT a child)
        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "parent-exec-123",
            "_is_child_execution": False,
            "user_context": {"user_profile_id": 1, "telegram_chat_id": "chat-456"},
        }

        agent_node(state)

        config_arg = mock_agent.invoke.call_args
        config = config_arg[1].get("config") or config_arg[0][1]
        # Should use conversation-scoped thread_id
        assert config["configurable"]["thread_id"] == "1:chat-456:1"


# ---------------------------------------------------------------------------
# Parallel wait tracking (orchestrator)
# ---------------------------------------------------------------------------


class TestParallelWaitTracking:
    """Test parallel child wait key format and accumulation."""

    def test_parallel_wait_key_format(self):
        """Verify wait key stores parallel metadata."""
        from services.orchestrator import _child_wait_key

        key = _child_wait_key("exec-123", "agent_1")
        assert key == "execution:exec-123:child_wait:agent_1"

    def test_partial_completion_does_not_resume(self):
        """When only some children complete, parent should NOT be resumed."""
        from services.orchestrator import _resume_from_child

        mock_redis = MagicMock()
        wait_data = json.dumps({
            "parallel": True,
            "total": 3,
            "child_ids": ["c1", "c2", "c3"],
            "results": {},
            "deadline": 9999999999,
        })
        mock_redis.get.return_value = wait_data

        # Mock Redis lock
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_redis.lock.return_value = mock_lock

        mock_parent = MagicMock()
        mock_parent.status = "running"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_parent

        with patch("services.orchestrator._redis", return_value=mock_redis), \
             patch("services.orchestrator.load_state", return_value={}) as mock_load, \
             patch("services.orchestrator.save_state") as mock_save, \
             patch("services.orchestrator._queue", return_value=MagicMock()) as mock_q, \
             patch("database.SessionLocal", return_value=mock_db):
            _resume_from_child("parent-exec", "agent_1", {"result": "ok"}, child_execution_id="c1")

        # Parent should NOT be re-enqueued (only 1/3 done)
        mock_q.return_value.enqueue.assert_not_called()
        mock_save.assert_not_called()

        # Wait key should be updated, not deleted
        mock_redis.delete.assert_not_called()
        mock_redis.set.assert_called()

    def test_full_completion_resumes_parent(self):
        """When all children complete, parent should be resumed with ordered results."""
        from services.orchestrator import _resume_from_child

        mock_redis = MagicMock()

        # Simulate: c1 already done, c2 now completing
        wait_data_initial = json.dumps({
            "parallel": True,
            "total": 2,
            "child_ids": ["c1", "c2"],
            "results": {"c1": {"output": "result1"}},
            "deadline": 9999999999,
        })
        mock_redis.get.return_value = wait_data_initial

        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_redis.lock.return_value = mock_lock

        mock_parent = MagicMock()
        mock_parent.status = "running"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_parent

        saved_state = {}

        def capture_save(eid, state):
            saved_state.update(state)

        with patch("services.orchestrator._redis", return_value=mock_redis), \
             patch("services.orchestrator.load_state", return_value={}), \
             patch("services.orchestrator.save_state", side_effect=capture_save), \
             patch("services.orchestrator._queue", return_value=MagicMock()) as mock_q, \
             patch("database.SessionLocal", return_value=mock_db):
            _resume_from_child("parent-exec", "agent_1", {"output": "result2"}, child_execution_id="c2")

        # Parent should be re-enqueued
        mock_q.return_value.enqueue.assert_called_once()

        # Wait key should be deleted
        mock_redis.delete.assert_called()

        # Results should be ordered by child_ids
        results = saved_state.get("_subworkflow_results", {}).get("agent_1")
        assert results == [{"output": "result1"}, {"output": "result2"}]


# ---------------------------------------------------------------------------
# Task linkage in child creation
# ---------------------------------------------------------------------------


class TestTaskLinkage:
    def test_task_linked_when_task_id_provided(self, mock_session, workflow, user_profile):
        from components.agent import _create_child_from_interrupt
        from models.workflow import Workflow

        # Create target workflow
        target_wf = Workflow(
            name="Child WF",
            slug="child-wf",
            owner_id=user_profile.id,
            is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()

        # Create epic and task
        epic = Epic(
            title="Test Epic",
            user_profile_id=user_profile.id,
        )
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(
            epic_id=epic.id,
            title="Test Task",
            status="pending",
        )
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        # Create parent execution
        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="test",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
        }
        task_data = {
            "workflow_slug": "child-wf",
            "input_text": "run task",
            "task_id": task.id,
            "input_data": {},
        }

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            child_id = _create_child_from_interrupt(task_data, state, "agent_1")

        # Verify task was linked
        mock_session.refresh(task)
        assert task.execution_id == child_id
        assert task.status == "running"


# ---------------------------------------------------------------------------
# Cost sync
# ---------------------------------------------------------------------------


class TestCostSync:
    def test_sync_completed_execution(self, mock_session, workflow, user_profile):
        from services.orchestrator import _sync_task_costs

        # Create epic + task
        epic = Epic(title="E", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(epic_id=epic.id, title="T", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        # Create execution linked to task
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
            final_output={"message": "done"},
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        task.execution_id = str(execution.execution_id)
        mock_session.commit()

        _sync_task_costs(str(execution.execution_id), mock_session)

        mock_session.refresh(task)
        assert task.status == "completed"
        assert task.duration_ms == 5000
        assert task.result_summary is not None
        assert task.completed_at is not None

    def test_sync_failed_execution(self, mock_session, workflow, user_profile):
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="E", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(epic_id=epic.id, title="T", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="failed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
            error_message="Node agent_1: something went wrong",
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        task.execution_id = str(execution.execution_id)
        mock_session.commit()

        _sync_task_costs(str(execution.execution_id), mock_session)

        mock_session.refresh(task)
        assert task.status == "failed"
        assert task.duration_ms == 3000
        assert task.error_message is not None

    def test_no_op_when_no_linked_task(self, mock_session, workflow, user_profile):
        from services.orchestrator import _sync_task_costs

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        # Should not raise — just a no-op
        _sync_task_costs(str(execution.execution_id), mock_session)

    def test_epic_progress_synced(self, mock_session, workflow, user_profile):
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="E", user_profile_id=user_profile.id, total_tasks=0, completed_tasks=0)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        # Add two tasks — one completed, one to be synced
        done_task = Task(epic_id=epic.id, title="Done", status="completed")
        mock_session.add(done_task)
        pending_task = Task(epic_id=epic.id, title="Pending", status="running")
        mock_session.add(pending_task)
        mock_session.commit()
        mock_session.refresh(pending_task)

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        pending_task.execution_id = str(execution.execution_id)
        mock_session.commit()

        _sync_task_costs(str(execution.execution_id), mock_session)

        mock_session.refresh(epic)
        assert epic.total_tasks == 2
        assert epic.completed_tasks == 2  # both should be completed now


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_spawn_and_await_in_node_type_registry(self):
        import schemas.node_type_defs  # noqa: F401 — triggers registration
        from schemas.node_types import NODE_TYPE_REGISTRY

        assert "spawn_and_await" in NODE_TYPE_REGISTRY
        spec = NODE_TYPE_REGISTRY["spawn_and_await"]
        assert spec.display_name == "Spawn & Await"
        assert spec.category == "agent"

    def test_spawn_and_await_in_builder_sub_component_types(self):
        from services.builder import SUB_COMPONENT_TYPES

        assert "spawn_and_await" in SUB_COMPONENT_TYPES

    def test_spawn_and_await_in_topology_sub_component_types(self):
        from services.topology import SUB_COMPONENT_TYPES

        assert "spawn_and_await" in SUB_COMPONENT_TYPES

    def test_spawn_and_await_in_component_registry(self):
        from components import COMPONENT_REGISTRY

        assert "spawn_and_await" in COMPONENT_REGISTRY

    def test_spawn_and_await_polymorphic_identity(self):
        from models.node import COMPONENT_TYPE_TO_CONFIG

        assert "spawn_and_await" in COMPONENT_TYPE_TO_CONFIG


# ---------------------------------------------------------------------------
# Tool invocation (spawn_and_await.py)
# ---------------------------------------------------------------------------


class TestToolInvocation:
    """Test spawn_and_await tool body: interrupt call and result serialization."""

    def test_tool_returns_json_when_interrupt_returns_list(self):
        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tool = spawn_and_await_factory(node)[0]

        child_results = [{"result": "done1"}, {"result": "done2"}]

        with patch("langgraph.types.interrupt", return_value=child_results):
            result = tool.invoke({
                "tasks": [
                    {"workflow_slug": "wf1", "input_text": "task1"},
                    {"workflow_slug": "wf2", "input_text": "task2"},
                ],
            })

        assert result == json.dumps(child_results, default=str)

    def test_tool_returns_string_passthrough_when_interrupt_returns_string(self):
        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tool = spawn_and_await_factory(node)[0]

        with patch("langgraph.types.interrupt", return_value="child completed"):
            result = tool.invoke({
                "tasks": [{"workflow_slug": "wf1", "input_text": "hello"}],
            })

        assert result == "child completed"

    def test_tool_raises_tool_exception_on_error(self):
        from langchain_core.tools import ToolException

        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tool = spawn_and_await_factory(node)[0]

        error_result = {"_error": "Spawn depth limit reached"}

        with patch("langgraph.types.interrupt", return_value=error_result):
            with pytest.raises(ToolException, match="Spawn failed"):
                tool.invoke({
                    "tasks": [{"workflow_slug": "wf1", "input_text": "hello"}],
                })

    def test_tool_returns_dict_without_error_normally(self):
        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tool = spawn_and_await_factory(node)[0]

        # Dict without _error should be returned as JSON, not raise
        child_output = {"output": "success", "_other_key": "fine"}

        with patch("langgraph.types.interrupt", return_value=child_output):
            result = tool.invoke({
                "tasks": [{"workflow_slug": "wf1", "input_text": "hello"}],
            })

        assert result == json.dumps(child_output, default=str)

    def test_tool_validates_non_dict_task(self):
        """Non-dict tasks should raise ToolException during validation."""
        from langchain_core.tools import ToolException

        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tool = spawn_and_await_factory(node)[0]

        # Pydantic validates list[dict] at the schema level, so we need to
        # call the underlying function directly to test the tool body validation
        with pytest.raises(ToolException, match="must be a dict"):
            tool.func(tasks=["not_a_dict"])

    def test_tool_validates_missing_workflow_slug(self):
        from langchain_core.tools import ToolException

        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tool = spawn_and_await_factory(node)[0]

        with pytest.raises(ToolException, match="missing required field 'workflow_slug'"):
            tool.invoke({"tasks": [{"input_text": "hi"}]})

    def test_tool_validates_empty_tasks_list(self):
        from langchain_core.tools import ToolException

        from components.spawn_and_await import spawn_and_await_factory

        node = _make_node("spawn_and_await", workflow_id=1)
        tool = spawn_and_await_factory(node)[0]

        with pytest.raises(ToolException, match="cannot be empty"):
            tool.invoke({"tasks": []})


# ---------------------------------------------------------------------------
# _create_child_from_interrupt edge cases (agent.py)
# ---------------------------------------------------------------------------


class TestCreateChildEdgeCases:
    """Cover uncovered branches in _create_child_from_interrupt."""

    def test_user_profile_id_fallback_from_parent_execution(
        self, mock_session, workflow, user_profile
    ):
        """When user_context has no user_profile_id, fall back to the parent execution's user_profile_id."""
        from components.agent import _create_child_from_interrupt
        from models.workflow import Workflow

        target_wf = Workflow(
            name="Target", slug="target-wf", owner_id=user_profile.id, is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()

        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        # user_context has NO user_profile_id — should fall back to parent exec
        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {},
        }
        task_data = {
            "workflow_slug": "target-wf",
            "input_text": "test fallback",
            "task_id": None,
            "input_data": {},
        }

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            child_id = _create_child_from_interrupt(task_data, state, "agent_1")

        child_exec = (
            mock_session.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == child_id)
            .first()
        )
        assert child_exec is not None
        assert child_exec.user_profile_id == user_profile.id

    def test_raises_when_no_user_profile_id(self, mock_session, workflow, user_profile):
        """Raises ValueError when user_profile_id cannot be determined at all."""
        from components.agent import _create_child_from_interrupt
        from models.workflow import Workflow

        target_wf = Workflow(
            name="Target", slug="target-wf2", owner_id=user_profile.id, is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()

        # No user_profile_id in context, no parent execution to fall back to
        state = {
            "execution_id": "nonexistent-exec-id",
            "user_context": {},
        }
        task_data = {
            "workflow_slug": "target-wf2",
            "input_text": "test",
            "task_id": None,
            "input_data": {},
        }

        with pytest.raises(ValueError, match="cannot determine user_profile_id"):
            _create_child_from_interrupt(task_data, state, "agent_1")

    def test_task_linkage_exception_swallowed(
        self, mock_session, workflow, user_profile
    ):
        """When task linkage fails, the exception is logged but not raised."""
        from components.agent import _create_child_from_interrupt
        from models.workflow import Workflow

        target_wf = Workflow(
            name="Target", slug="target-wf3", owner_id=user_profile.id, is_active=True,
        )
        mock_session.add(target_wf)
        mock_session.commit()

        parent_exec = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
        )
        mock_session.add(parent_exec)
        mock_session.commit()
        mock_session.refresh(parent_exec)

        state = {
            "execution_id": str(parent_exec.execution_id),
            "user_context": {"user_profile_id": user_profile.id},
        }
        task_data = {
            "workflow_slug": "target-wf3",
            "input_text": "test",
            "task_id": "tk-fake123",
            "input_data": {},
        }

        # Patch Task query inside the linkage try/except to raise
        original_query = mock_session.query
        call_count = {"task_queries": 0}

        def patched_query(model):
            from models.epic import Task as TaskModel
            if model is TaskModel:
                call_count["task_queries"] += 1
                raise RuntimeError("DB error during task linkage")
            return original_query(model)

        with patch("redis.from_url", return_value=MagicMock()), \
             patch("rq.Queue", return_value=MagicMock()):
            # Temporarily replace mock_session.query so that the Task query
            # inside the linkage block raises, while other queries still work.
            # We swap it in only after the child execution is committed.
            original_commit = mock_session.commit
            commit_calls = {"count": 0}

            def commit_then_patch():
                commit_calls["count"] += 1
                original_commit()
                # After the child execution is committed (2nd commit inside the function),
                # swap in the patched query for the task linkage block
                if commit_calls["count"] == 1:
                    mock_session.query = patched_query

            mock_session.commit = commit_then_patch
            try:
                child_id = _create_child_from_interrupt(task_data, state, "agent_1")
            finally:
                mock_session.commit = original_commit
                mock_session.query = original_query

        # Should succeed despite task linkage exception — child was still created
        assert child_id is not None
        assert call_count["task_queries"] == 1


# ---------------------------------------------------------------------------
# _sync_task_costs edge cases (orchestrator.py)
# ---------------------------------------------------------------------------


class TestSyncTaskCostsEdgeCases:
    """Cover uncovered branches in _sync_task_costs."""

    def test_no_op_when_execution_not_found(self, mock_session, workflow, user_profile):
        """Early return when execution_id has a linked task but no matching execution."""
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="E", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(
            epic_id=epic.id,
            title="T",
            status="running",
            execution_id="orphan-exec-id",
        )
        mock_session.add(task)
        mock_session.commit()

        # Call with the task's execution_id, but no WorkflowExecution row exists
        _sync_task_costs("orphan-exec-id", mock_session)

        mock_session.refresh(task)
        assert task.status == "running"  # unchanged

    def test_task_committed_when_epic_sync_raises(
        self, mock_session, workflow, user_profile
    ):
        """Task status is persisted even if sync_epic_progress raises."""
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="E", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        task = Task(epic_id=epic.id, title="T", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        task.execution_id = str(execution.execution_id)
        mock_session.commit()

        with patch(
            "api.epic_helpers.sync_epic_progress",
            side_effect=RuntimeError("boom"),
        ):
            _sync_task_costs(str(execution.execution_id), mock_session)

        mock_session.refresh(task)
        # Task status should still be committed despite epic sync failure
        assert task.status == "completed"
        assert task.duration_ms == 2000

    def test_no_epic_sync_when_task_has_no_epic(
        self, mock_session, workflow, user_profile
    ):
        """When task.epic is falsy, sync_epic_progress is not called."""
        from services.orchestrator import _sync_task_costs

        epic = Epic(title="Placeholder", user_profile_id=user_profile.id)
        mock_session.add(epic)
        mock_session.commit()
        mock_session.refresh(epic)

        # task.epic will be patched to None later
        task = Task(epic_id=epic.id, title="Orphan Task", status="running")
        mock_session.add(task)
        mock_session.commit()
        mock_session.refresh(task)

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            trigger_payload={},
            thread_id="t",
            status="completed",
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 4, tzinfo=timezone.utc),
        )
        mock_session.add(execution)
        mock_session.commit()
        mock_session.refresh(execution)

        task.execution_id = str(execution.execution_id)
        mock_session.commit()

        with patch(
            "api.epic_helpers.sync_epic_progress",
        ) as mock_sync:
            # Override the epic relationship at class level so task.epic is None
            with patch.object(Task, "epic", None):
                _sync_task_costs(str(execution.execution_id), mock_session)

        mock_sync.assert_not_called()

        mock_session.refresh(task)
        assert task.status == "completed"
        assert task.duration_ms == 4000


# ---------------------------------------------------------------------------
# Redis checkpointer singleton (agent.py lines 23-24, 46-57)
# ---------------------------------------------------------------------------


class TestRedisCheckpointer:
    """Test _get_redis_checkpointer() creates and caches a RedisSaver singleton."""

    def test_creates_and_caches_redis_saver(self):
        import sys
        import components._agent_shared as shared_mod
        from components._agent_shared import _get_redis_checkpointer

        original = shared_mod._redis_checkpointer
        shared_mod._redis_checkpointer = None
        try:
            mock_saver_instance = MagicMock()
            mock_saver_cls = MagicMock(return_value=mock_saver_instance)
            mock_redis_module = MagicMock(RedisSaver=mock_saver_cls)

            with patch.dict(sys.modules, {"langgraph.checkpoint.redis": mock_redis_module}), \
                 patch("config.settings") as mock_settings:
                mock_settings.REDIS_URL = "redis://test:6379/0"

                first = _get_redis_checkpointer()
                second = _get_redis_checkpointer()

                assert first is second
                mock_saver_cls.assert_called_once_with(redis_url="redis://test:6379/0")
                mock_saver_instance.setup.assert_called_once()
        finally:
            shared_mod._redis_checkpointer = original


class TestSqliteCheckpointer:
    """Test _get_checkpointer() creates and caches a SqliteSaver singleton."""

    def test_creates_and_caches_sqlite_saver(self):
        import sys
        import components._agent_shared as shared_mod
        from components._agent_shared import _get_checkpointer

        original = shared_mod._checkpointer
        shared_mod._checkpointer = None
        try:
            mock_conn = MagicMock()
            mock_sqlite3 = MagicMock()
            mock_sqlite3.connect.return_value = mock_conn

            mock_saver_instance = MagicMock()
            mock_saver_cls = MagicMock(return_value=mock_saver_instance)
            mock_sqlite_module = MagicMock(SqliteSaver=mock_saver_cls)

            with patch.dict(sys.modules, {
                "sqlite3": mock_sqlite3,
                "langgraph.checkpoint.sqlite": mock_sqlite_module,
            }):
                first = _get_checkpointer()
                second = _get_checkpointer()

                assert first is second
                assert first is mock_saver_instance
                mock_sqlite3.connect.assert_called_once()
                # Verify check_same_thread=False was passed
                connect_kwargs = mock_sqlite3.connect.call_args
                assert connect_kwargs[1].get("check_same_thread") is False
                mock_saver_cls.assert_called_once_with(mock_conn)
                mock_saver_instance.setup.assert_called_once()
        finally:
            shared_mod._checkpointer = original


# ---------------------------------------------------------------------------
# Agent node: spawn resume / interrupt flow (agent.py)
# ---------------------------------------------------------------------------


class TestAgentNodeSpawnResume:
    """Test resume-from-child-result path through agent_node()."""

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_resume_from_child_result(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        from components.agent import agent_factory

        # Mock LLM
        mock_resolve_llm.return_value = MagicMock()

        # Mock tools list with a spawn_and_await tool
        mock_spawn_tool = MagicMock()
        mock_spawn_tool.name = "spawn_and_await"
        mock_resolve_tools.return_value = ([mock_spawn_tool], {"spawn_and_await": {"tool_node_id": "spawn_1", "component_type": "spawn_and_await"}})

        # Mock redis checkpointer
        mock_checkpointer = MagicMock()
        mock_get_redis.return_value = mock_checkpointer

        # Mock agent
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="resumed output", additional_kwargs={})],
        }
        mock_create_agent.return_value = mock_agent

        # Build the agent_node closure
        node = _make_node("agent", workflow_id=1, node_id="test_node_1")
        agent_node = agent_factory(node)

        # Verify create_agent was called with checkpointer and middleware
        create_kwargs = mock_create_agent.call_args
        assert create_kwargs.kwargs.get("checkpointer") is mock_checkpointer
        assert "middleware" in create_kwargs.kwargs

        # Invoke with _subworkflow_results present (resume path)
        state = {
            "messages": [],
            "execution_id": "exec-123",
            "_subworkflow_results": {
                "test_node_1": [{"result": "child output 1"}, {"result": "child output 2"}],
            },
        }
        result = agent_node(state)

        # Verify agent.invoke was called with Command(resume=...) and ephemeral thread config
        invoke_args = mock_agent.invoke.call_args
        command_arg = invoke_args[0][0]
        # Check it's a Command with resume data (list of results for parallel)
        from langgraph.types import Command
        assert isinstance(command_arg, Command)
        assert command_arg.resume == [{"result": "child output 1"}, {"result": "child output 2"}]

        # Check ephemeral thread config (no callbacks — middleware handles events now)
        config_arg = invoke_args[1].get("config") or invoke_args[0][1]
        assert config_arg["configurable"] == {"thread_id": "exec:exec-123:test_node_1"}
        assert "callbacks" not in config_arg

        # Verify output
        assert "output" in result


class TestAgentNodeGraphInterrupt:
    """Test GraphInterrupt handling in agent_node()."""

    def _setup_agent(self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm):
        """Shared setup for interrupt tests — returns (agent_node, mock_agent)."""
        from components.agent import agent_factory

        mock_resolve_llm.return_value = MagicMock()

        mock_spawn_tool = MagicMock()
        mock_spawn_tool.name = "spawn_and_await"
        mock_resolve_tools.return_value = ([mock_spawn_tool], {"spawn_and_await": {"tool_node_id": "spawn_1", "component_type": "spawn_and_await"}})

        mock_checkpointer = MagicMock()
        mock_get_redis.return_value = mock_checkpointer

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent

        node = _make_node("agent", workflow_id=1, node_id="test_node_1")
        agent_node = agent_factory(node)
        return agent_node, mock_agent

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_graph_interrupt_creates_children(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        from langgraph.errors import GraphInterrupt

        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        # New parallel interrupt format
        interrupt_value = {
            "action": "spawn_and_await",
            "tasks": [
                {"workflow_slug": "wf1", "input_text": "task 1"},
                {"workflow_slug": "wf2", "input_text": "task 2"},
            ],
        }
        interrupt_obj = MagicMock()
        interrupt_obj.value = interrupt_value

        exc = GraphInterrupt([interrupt_obj])
        exc.interrupts = [interrupt_obj]
        mock_agent.invoke.side_effect = exc

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-789",
            "_spawn_depth": 0,
        }

        with patch("components.agent._try_create_children", return_value={
            "_subworkflow": {"child_execution_ids": ["c1", "c2"], "parallel": True, "count": 2}
        }) as mock_create:
            result = agent_node(state)

        assert result == {
            "_subworkflow": {"child_execution_ids": ["c1", "c2"], "parallel": True, "count": 2}
        }
        mock_create.assert_called_once_with(interrupt_value, state, "test_node_1")

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_interrupt_in_return_value_creates_children(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        """When checkpointer is present, invoke() returns __interrupt__ instead of raising."""
        from langgraph.types import Interrupt

        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        interrupt_value = {
            "action": "spawn_and_await",
            "tasks": [{"workflow_slug": "wf1", "input_text": "do something"}],
        }
        interrupt_obj = Interrupt(value=interrupt_value)

        # invoke() returns dict with __interrupt__ key (checkpointer present)
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="partial", additional_kwargs={})],
            "__interrupt__": (interrupt_obj,),
        }

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-789",
            "_spawn_depth": 0,
        }

        with patch("components.agent._try_create_children", return_value={
            "_subworkflow": {"child_execution_ids": ["c1"], "parallel": True, "count": 1}
        }) as mock_create:
            result = agent_node(state)

        assert "_subworkflow" in result
        mock_create.assert_called_once_with(interrupt_value, state, "test_node_1")

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_interrupt_in_return_value_ignored_without_spawn_action(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        """__interrupt__ with non-spawn action (e.g. human_confirmation) is not intercepted."""
        from langgraph.types import Interrupt

        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        interrupt_obj = Interrupt(value={"action": "human_confirmation", "message": "approve?"})

        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="waiting", additional_kwargs={})],
            "__interrupt__": (interrupt_obj,),
        }

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-100",
        }

        result = agent_node(state)

        # Should NOT create children — falls through to normal output extraction
        assert "output" in result
        assert result["output"] == "waiting"

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_non_interrupt_exception_reraises(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        mock_agent.invoke.side_effect = RuntimeError("LLM error")

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-999",
        }

        with pytest.raises(RuntimeError, match="LLM error"):
            agent_node(state)

    @patch("components.agent.resolve_llm_for_node")
    @patch("components.agent._resolve_tools")
    @patch("components.agent.create_agent")
    @patch("components.agent._get_redis_checkpointer")
    def test_interrupt_child_creation_error_returns_output(
        self, mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
    ):
        """When _try_create_children fails, return error output instead of raising."""
        from langgraph.types import Interrupt

        agent_node, mock_agent = self._setup_agent(
            mock_get_redis, mock_create_agent, mock_resolve_tools, mock_resolve_llm,
        )

        interrupt_value = {
            "action": "spawn_and_await",
            "tasks": [{"workflow_slug": "nonexistent", "input_text": "test"}],
        }
        interrupt_obj = Interrupt(value=interrupt_value)

        mock_agent.invoke.return_value = {
            "messages": [MagicMock(type="ai", content="partial", additional_kwargs={})],
            "__interrupt__": (interrupt_obj,),
        }

        state = {
            "messages": [MagicMock(type="human", content="hello")],
            "execution_id": "exec-err",
            "_spawn_depth": 0,
        }

        with patch(
            "components.agent._create_child_from_interrupt",
            side_effect=ValueError("target workflow not found"),
        ):
            result = agent_node(state)

        # Should return error output, NOT raise (generic message, no raw exception)
        assert "output" in result
        assert "spawn_and_await failed" in result["output"]
        assert "unable to create child execution" in result["output"]


# ---------------------------------------------------------------------------
# Child wait timeout & cleanup (orchestrator + tasks/cleanup.py)
# ---------------------------------------------------------------------------


class TestChildWaitTimeout:
    """Test child_wait Redis key lifecycle and cleanup job."""

    def test_child_wait_key_helper(self):
        from services.orchestrator import _child_wait_key

        key = _child_wait_key("exec-123", "agent_1")
        assert key == "execution:exec-123:child_wait:agent_1"

    def test_resume_from_child_deletes_wait_key(self):
        """_resume_from_child (legacy single-child) should delete the child_wait key."""
        from services.orchestrator import _child_wait_key, _resume_from_child

        mock_redis = MagicMock()
        # Legacy non-parallel wait key
        mock_redis.get.return_value = json.dumps({
            "deadline": 9999999999,
            "child_execution_id": "child-1",
        })
        mock_parent = MagicMock()
        mock_parent.status = "running"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_parent

        with patch("services.orchestrator._redis", return_value=mock_redis), \
             patch("services.orchestrator.load_state", return_value={}), \
             patch("services.orchestrator.save_state"), \
             patch("services.orchestrator._queue", return_value=MagicMock()), \
             patch("database.SessionLocal", return_value=mock_db):
            _resume_from_child("parent-exec", "agent_1", {"result": "ok"})

        mock_redis.delete.assert_called_once_with(
            _child_wait_key("parent-exec", "agent_1")
        )

    def test_cleanup_expires_stuck_parallel_waits(self):
        """cleanup_stuck_child_waits handles parallel wait keys with timeout errors."""
        import time as _time

        from services.cleanup import cleanup_stuck_child_waits

        expired_data = json.dumps({
            "deadline": _time.time() - 100,
            "parallel": True,
            "total": 3,
            "child_ids": ["c1", "c2", "c3"],
            "results": {"c1": {"output": "done"}},
        })

        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, ["execution:parent-exec:child_wait:agent_1"])
        mock_redis.get.return_value = expired_data

        with patch("services.cleanup.redis_lib.from_url", return_value=mock_redis), \
             patch("services.cleanup.settings"), \
             patch("services.orchestrator._resume_from_child") as mock_resume:
            count = cleanup_stuck_child_waits()

        assert count == 1
        # Should resume with ordered list: c1 has result, c2 and c3 timed out
        mock_resume.assert_called_once_with(
            parent_execution_id="parent-exec",
            parent_node_id="agent_1",
            child_output=[
                {"output": "done"},
                {"_error": "Child execution timed out"},
                {"_error": "Child execution timed out"},
            ],
        )

    def test_cleanup_expires_stuck_single_waits(self):
        """cleanup_stuck_child_waits handles legacy single-child wait keys."""
        import time as _time

        from services.cleanup import cleanup_stuck_child_waits

        expired_data = json.dumps({
            "deadline": _time.time() - 100,
            "child_execution_id": "child-456",
        })

        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, ["execution:parent-exec:child_wait:agent_1"])
        mock_redis.get.return_value = expired_data

        with patch("services.cleanup.redis_lib.from_url", return_value=mock_redis), \
             patch("services.cleanup.settings"), \
             patch("services.orchestrator._resume_from_child") as mock_resume:
            count = cleanup_stuck_child_waits()

        assert count == 1
        mock_resume.assert_called_once_with(
            parent_execution_id="parent-exec",
            parent_node_id="agent_1",
            child_output={"_error": "Child execution timed out"},
        )

    def test_cleanup_skips_non_expired_waits(self):
        """cleanup_stuck_child_waits should skip keys whose deadline hasn't passed."""
        import time as _time

        from services.cleanup import cleanup_stuck_child_waits

        future_data = json.dumps({
            "deadline": _time.time() + 1000,  # still in the future
            "child_execution_id": "child-789",
        })

        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, ["execution:parent-exec:child_wait:agent_1"])
        mock_redis.get.return_value = future_data

        with patch("services.cleanup.redis_lib.from_url", return_value=mock_redis), \
             patch("services.cleanup.settings"), \
             patch("services.orchestrator._resume_from_child") as mock_resume:
            count = cleanup_stuck_child_waits()

        assert count == 0
        mock_resume.assert_not_called()

    def test_cleanup_retains_key_on_resume_failure(self):
        """When _resume_from_child raises, the key is kept for retry on next run."""
        import time as _time

        from services.cleanup import cleanup_stuck_child_waits

        expired_data = json.dumps({
            "deadline": _time.time() - 100,
            "child_execution_id": "child-456",
        })

        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, ["execution:parent-exec:child_wait:agent_1"])
        mock_redis.get.return_value = expired_data

        with patch("services.cleanup.redis_lib.from_url", return_value=mock_redis), \
             patch("services.cleanup.settings"), \
             patch("services.orchestrator._resume_from_child", side_effect=RuntimeError("transient")):
            count = cleanup_stuck_child_waits()

        assert count == 0
        # Key should NOT have been deleted since resume failed
        mock_redis.delete.assert_not_called()

    def test_cleanup_skips_empty_keys(self):
        """cleanup_stuck_child_waits skips keys whose value is empty/gone."""
        from services.cleanup import cleanup_stuck_child_waits

        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, ["execution:ex1:child_wait:n1"])
        mock_redis.get.return_value = None  # key disappeared

        with patch("services.cleanup.redis_lib.from_url", return_value=mock_redis), \
             patch("services.cleanup.settings"):
            count = cleanup_stuck_child_waits()

        assert count == 0

    def test_cleanup_deletes_malformed_json_keys(self):
        """cleanup_stuck_child_waits deletes keys with unparseable JSON."""
        from services.cleanup import cleanup_stuck_child_waits

        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, ["execution:ex1:child_wait:n1"])
        mock_redis.get.return_value = "not-json{{"

        with patch("services.cleanup.redis_lib.from_url", return_value=mock_redis), \
             patch("services.cleanup.settings"):
            count = cleanup_stuck_child_waits()

        assert count == 0
        mock_redis.delete.assert_called_once_with("execution:ex1:child_wait:n1")

    def test_cleanup_deletes_malformed_key_pattern(self):
        """cleanup_stuck_child_waits deletes keys that don't match expected pattern."""
        import time as _time

        from services.cleanup import cleanup_stuck_child_waits

        expired_data = json.dumps({"deadline": _time.time() - 100})

        mock_redis = MagicMock()
        # Key without "child_wait" sentinel
        mock_redis.scan.return_value = (0, ["execution:ex1:bogus:n1"])
        mock_redis.get.return_value = expired_data

        with patch("services.cleanup.redis_lib.from_url", return_value=mock_redis), \
             patch("services.cleanup.settings"):
            count = cleanup_stuck_child_waits()

        assert count == 0
        mock_redis.delete.assert_called_once_with("execution:ex1:bogus:n1")

    def test_cleanup_job_wrapper(self):
        """services.cleanup_stuck_child_waits_job delegates to the real function."""
        from tasks import cleanup_stuck_child_waits_job

        with patch("services.cleanup.cleanup_stuck_child_waits", return_value=3) as mock_fn:
            result = cleanup_stuck_child_waits_job()

        assert result == 3
        mock_fn.assert_called_once()


# ---------------------------------------------------------------------------
# _propagate_failure_to_parent helper (orchestrator.py)
# ---------------------------------------------------------------------------


class TestPropagateFailureToParent:
    """Test the _propagate_failure_to_parent helper."""

    def test_no_op_when_no_parent(self):
        """Does nothing when execution has no parent_execution_id."""
        from services.orchestrator import _propagate_failure_to_parent

        execution = MagicMock()
        execution.parent_execution_id = None
        execution.parent_node_id = None

        with patch("services.orchestrator._resume_from_child") as mock_resume:
            _propagate_failure_to_parent(execution, RuntimeError("fail"))

        mock_resume.assert_not_called()

    def test_calls_resume_from_child_with_execution_id(self):
        """Calls _resume_from_child with error payload and child_execution_id."""
        from services.orchestrator import _propagate_failure_to_parent

        execution = MagicMock()
        execution.parent_execution_id = "parent-exec-1"
        execution.parent_node_id = "agent_1"
        execution.execution_id = "child-exec-1"

        with patch("services.orchestrator._resume_from_child") as mock_resume:
            _propagate_failure_to_parent(execution, RuntimeError("something broke"))

        mock_resume.assert_called_once_with(
            parent_execution_id="parent-exec-1",
            parent_node_id="agent_1",
            child_output={"_error": "Child execution failed: something broke"},
            child_execution_id="child-exec-1",
        )

    def test_swallows_resume_exception(self):
        """Does not raise when _resume_from_child fails."""
        from services.orchestrator import _propagate_failure_to_parent

        execution = MagicMock()
        execution.parent_execution_id = "parent-exec-1"
        execution.parent_node_id = "agent_1"
        execution.execution_id = "child-exec-1"

        with patch("services.orchestrator._resume_from_child", side_effect=RuntimeError("redis down")):
            # Should not raise
            _propagate_failure_to_parent(execution, RuntimeError("original error"))


# ---------------------------------------------------------------------------
# execute_node_job integration paths (orchestrator.py changed lines)
# ---------------------------------------------------------------------------


class TestExecuteNodeJobSpawnPaths:
    """Cover the changed lines inside execute_node_job for subworkflow/propagation."""

    def _make_topo_data(self, node_id="agent_1", component_type="agent"):
        return {
            "workflow_slug": "test-wf",
            "nodes": {
                node_id: {
                    "node_id": node_id,
                    "component_type": component_type,
                    "db_id": 1,
                    "component_config_id": 1,
                    "interrupt_before": False,
                    "interrupt_after": False,
                },
            },
            "edges_by_source": {},
            "incoming_count": {},
            "entry_node_ids": [node_id],
            "loop_bodies": {},
            "loop_return_nodes": {},
            "loop_body_all_nodes": {},
        }

    @patch("services.orchestrator._cleanup_redis")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._publish_event")
    @patch("services.orchestrator._clear_stale_checkpoints")
    @patch("services.orchestrator._sync_task_costs")
    @patch("services.orchestrator._propagate_failure_to_parent")
    def test_inner_failure_calls_propagate(
        self, mock_propagate, mock_sync, mock_clear, mock_publish, mock_episode, mock_cleanup,
    ):
        """When a node fails permanently (max retries), _propagate_failure_to_parent is called."""
        from services.orchestrator import execute_node_job

        mock_exec = MagicMock()
        mock_exec.status = "running"
        mock_exec.execution_id = "exec-1"
        mock_exec.trigger_payload = {}

        mock_db_node = MagicMock()
        mock_db_node.component_config.system_prompt = None
        mock_db_node.component_config.extra_config = {}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_exec
        mock_db.get.return_value = mock_db_node

        topo = self._make_topo_data()

        def fake_factory(node):
            def fn(state):
                raise RuntimeError("component exploded")
            return fn

        with patch("database.SessionLocal", return_value=mock_db), \
             patch("services.orchestrator._load_topology", return_value=topo), \
             patch("services.orchestrator.load_state", return_value={"node_outputs": {}, "messages": []}), \
             patch("services.orchestrator.save_state"), \
             patch("services.orchestrator._redis", return_value=MagicMock()), \
             patch("services.orchestrator._queue", return_value=MagicMock()), \
             patch("services.orchestrator._write_log"), \
             patch("components.get_component_factory", return_value=fake_factory), \
             patch("services.expressions.resolve_expressions", side_effect=lambda s, *a: s), \
             patch("services.expressions.resolve_config_expressions", side_effect=lambda c, *a: c):
            execute_node_job("exec-1", "agent_1", retry_count=3)

        mock_propagate.assert_called_once_with(mock_exec, unittest.mock.ANY)

    @patch("services.orchestrator._advance")
    @patch("services.orchestrator._publish_event")
    def test_subworkflow_stores_parallel_wait(self, mock_publish, mock_advance):
        """When component returns _subworkflow with parallel children, a parallel wait key is stored."""
        from services.orchestrator import _child_wait_key, execute_node_job

        mock_exec = MagicMock()
        mock_exec.status = "running"
        mock_exec.execution_id = "exec-2"
        mock_exec.trigger_payload = {}

        mock_db_node = MagicMock()
        mock_db_node.component_config.system_prompt = None
        mock_db_node.component_config.extra_config = {}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_exec
        mock_db.get.return_value = mock_db_node

        topo = self._make_topo_data()
        mock_redis = MagicMock()

        def fake_factory(node):
            def fn(state):
                return {
                    "_subworkflow": {
                        "child_execution_ids": ["c1", "c2"],
                        "parallel": True,
                        "count": 2,
                    },
                    "output": "spawning",
                }
            return fn

        with patch("database.SessionLocal", return_value=mock_db), \
             patch("services.orchestrator._load_topology", return_value=topo), \
             patch("services.orchestrator.load_state", return_value={"node_outputs": {}, "messages": []}), \
             patch("services.orchestrator.save_state"), \
             patch("services.orchestrator._redis", return_value=mock_redis), \
             patch("services.orchestrator._write_log"), \
             patch("components.get_component_factory", return_value=fake_factory), \
             patch("services.expressions.resolve_expressions", side_effect=lambda s, *a: s), \
             patch("services.expressions.resolve_config_expressions", side_effect=lambda c, *a: c):
            execute_node_job("exec-2", "agent_1")

        # Verify parallel wait data was stored in Redis
        set_calls = [c for c in mock_redis.set.call_args_list
                     if c[0][0] == _child_wait_key("exec-2", "agent_1")]
        assert len(set_calls) == 1
        wait_data = json.loads(set_calls[0][0][1])
        assert wait_data["parallel"] is True
        assert wait_data["total"] == 2
        assert wait_data["child_ids"] == ["c1", "c2"]
        assert wait_data["results"] == {}

        # Verify _advance was NOT called (node stays waiting)
        mock_advance.assert_not_called()

    @patch("services.orchestrator._propagate_failure_to_parent")
    @patch("services.orchestrator._complete_episode")
    @patch("services.orchestrator._publish_event")
    def test_outer_handler_propagates_to_parent(
        self, mock_publish, mock_episode, mock_propagate,
    ):
        """Outer except handler calls _propagate_failure_to_parent."""
        from services.orchestrator import execute_node_job

        mock_exec = MagicMock()
        mock_exec.status = "running"
        mock_exec.execution_id = "exec-3"
        mock_exec.trigger_payload = {}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_exec

        # Make _load_topology raise to trigger the outer except handler
        with patch("database.SessionLocal", return_value=mock_db), \
             patch("services.orchestrator._load_topology", side_effect=RuntimeError("topo missing")), \
             patch("services.orchestrator._clear_stale_checkpoints"), \
             patch("services.orchestrator._sync_task_costs"):
            execute_node_job("exec-3", "agent_1")

        mock_propagate.assert_called_once_with(mock_exec, unittest.mock.ANY)


# ---------------------------------------------------------------------------
# Initial state: _is_child_execution and _spawn_depth
# ---------------------------------------------------------------------------


class TestBuildInitialState:
    """Test _build_initial_state includes child/spawn_depth flags."""

    def test_parent_execution_state(self):
        from services.orchestrator import _build_initial_state

        execution = MagicMock()
        execution.trigger_payload = {"text": "hello"}
        execution.user_profile_id = 1
        execution.execution_id = "exec-1"
        execution.parent_execution_id = None

        state = _build_initial_state(execution)
        assert state["_is_child_execution"] is False
        assert state["_spawn_depth"] == 0

    def test_child_execution_state(self):
        from services.orchestrator import _build_initial_state

        execution = MagicMock()
        execution.trigger_payload = {"text": "do task", "_spawn_depth": 2}
        execution.user_profile_id = 1
        execution.execution_id = "child-exec-1"
        execution.parent_execution_id = "parent-exec-1"

        state = _build_initial_state(execution)
        assert state["_is_child_execution"] is True
        assert state["_spawn_depth"] == 2


# ---------------------------------------------------------------------------
# Resume from child: gone wait key
# ---------------------------------------------------------------------------


class TestResumeFromChildEdgeCases:
    """Test edge cases in _resume_from_child."""

    def test_no_op_when_wait_key_gone(self):
        """When wait key is already consumed, _resume_from_child is a no-op."""
        from services.orchestrator import _resume_from_child

        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # key already gone

        mock_parent = MagicMock()
        mock_parent.status = "running"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_parent

        with patch("services.orchestrator._redis", return_value=mock_redis), \
             patch("services.orchestrator.load_state") as mock_load, \
             patch("services.orchestrator.save_state") as mock_save, \
             patch("services.orchestrator._queue", return_value=MagicMock()) as mock_q, \
             patch("database.SessionLocal", return_value=mock_db):
            _resume_from_child("parent-exec", "agent_1", {"result": "ok"}, child_execution_id="c1")

        # Should not load/save state or enqueue
        mock_load.assert_not_called()
        mock_save.assert_not_called()
        mock_q.return_value.enqueue.assert_not_called()

    def test_no_op_when_parent_not_running(self):
        """When parent is not running, skip resume."""
        from services.orchestrator import _resume_from_child

        mock_parent = MagicMock()
        mock_parent.status = "failed"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_parent

        with patch("services.orchestrator._redis", return_value=MagicMock()), \
             patch("services.orchestrator.load_state") as mock_load, \
             patch("database.SessionLocal", return_value=mock_db):
            _resume_from_child("parent-exec", "agent_1", {"result": "ok"}, child_execution_id="c1")

        mock_load.assert_not_called()
