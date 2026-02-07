"""Tests for services/cache.py, services/executor.py, tasks/__init__.py."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── GraphCache ────────────────────────────────────────────────────────────────

class TestGraphCache:
    @patch("services.cache.WorkflowBuilder")
    def test_build_on_miss(self, mock_builder_cls):
        from services.cache import GraphCache

        mock_builder = MagicMock()
        mock_builder.build.return_value = "compiled_graph"
        mock_builder_cls.return_value = mock_builder

        cache = GraphCache(ttl=60)

        workflow = SimpleNamespace(id=1, updated_at="2024-01-01")
        mock_db = MagicMock()
        mock_node = MagicMock()
        mock_node.node_id = "n1"
        mock_node.updated_at = "2024-01-01"
        mock_node.component_config.updated_at = "2024-01-01"
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_node]

        result = cache.get_or_build(workflow, mock_db)
        assert result == "compiled_graph"
        mock_builder.build.assert_called_once()

    @patch("services.cache.WorkflowBuilder")
    def test_cache_hit(self, mock_builder_cls):
        from services.cache import GraphCache

        mock_builder = MagicMock()
        mock_builder.build.return_value = "compiled_graph"
        mock_builder_cls.return_value = mock_builder

        cache = GraphCache(ttl=60)

        workflow = SimpleNamespace(id=1, updated_at="2024-01-01")
        mock_db = MagicMock()
        mock_node = MagicMock()
        mock_node.node_id = "n1"
        mock_node.updated_at = "2024-01-01"
        mock_node.component_config.updated_at = "2024-01-01"
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_node]

        cache.get_or_build(workflow, mock_db)
        cache.get_or_build(workflow, mock_db)
        assert mock_builder.build.call_count == 1

    @patch("services.cache.WorkflowBuilder")
    def test_cache_expiry(self, mock_builder_cls):
        from services.cache import GraphCache

        mock_builder = MagicMock()
        mock_builder.build.return_value = "graph"
        mock_builder_cls.return_value = mock_builder

        cache = GraphCache(ttl=0)

        workflow = SimpleNamespace(id=1, updated_at="2024-01-01")
        mock_db = MagicMock()
        mock_node = MagicMock()
        mock_node.node_id = "n1"
        mock_node.updated_at = "2024-01-01"
        mock_node.component_config.updated_at = "2024-01-01"
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_node]

        cache.get_or_build(workflow, mock_db)
        time.sleep(0.01)
        cache.get_or_build(workflow, mock_db)
        assert mock_builder.build.call_count == 2

    @patch("services.cache.WorkflowBuilder")
    def test_invalidate(self, mock_builder_cls):
        from services.cache import GraphCache

        mock_builder = MagicMock()
        mock_builder.build.return_value = "graph"
        mock_builder_cls.return_value = mock_builder

        cache = GraphCache(ttl=3600)

        workflow = SimpleNamespace(id=1, updated_at="2024-01-01")
        mock_db = MagicMock()
        mock_node = MagicMock()
        mock_node.node_id = "n1"
        mock_node.updated_at = "2024-01-01"
        mock_node.component_config.updated_at = "2024-01-01"
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_node]

        cache.get_or_build(workflow, mock_db)
        cache.invalidate(1)
        cache.get_or_build(workflow, mock_db)
        assert mock_builder.build.call_count == 2

    @patch("services.cache.WorkflowBuilder")
    def test_clear(self, mock_builder_cls):
        from services.cache import GraphCache

        mock_builder = MagicMock()
        mock_builder.build.return_value = "graph"
        mock_builder_cls.return_value = mock_builder

        cache = GraphCache(ttl=3600)

        workflow = SimpleNamespace(id=1, updated_at="2024-01-01")
        mock_db = MagicMock()
        mock_node = MagicMock()
        mock_node.node_id = "n1"
        mock_node.updated_at = "2024-01-01"
        mock_node.component_config.updated_at = "2024-01-01"
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_node]

        cache.get_or_build(workflow, mock_db)
        cache.clear()
        cache.get_or_build(workflow, mock_db)
        assert mock_builder.build.call_count == 2

    @patch("services.cache.WorkflowBuilder")
    def test_trigger_node_id_varies_key(self, mock_builder_cls):
        from services.cache import GraphCache

        mock_builder = MagicMock()
        mock_builder.build.return_value = "graph"
        mock_builder_cls.return_value = mock_builder

        cache = GraphCache(ttl=3600)

        workflow = SimpleNamespace(id=1, updated_at="2024-01-01")
        mock_db = MagicMock()
        mock_node = MagicMock()
        mock_node.node_id = "n1"
        mock_node.updated_at = "2024-01-01"
        mock_node.component_config.updated_at = "2024-01-01"
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_node]

        cache.get_or_build(workflow, mock_db, trigger_node_id=1)
        cache.get_or_build(workflow, mock_db, trigger_node_id=2)
        assert mock_builder.build.call_count == 2


# ── WorkflowExecutor ──────────────────────────────────────────────────────────

class TestWorkflowExecutor:
    def test_execute(self):
        from services.executor import WorkflowExecutor
        with patch("services.orchestrator.start_execution") as mock_start:
            executor = WorkflowExecutor()
            executor.execute("exec-123")
            mock_start.assert_called_once_with("exec-123", None)

    def test_execute_with_db(self):
        from services.executor import WorkflowExecutor
        mock_db = MagicMock()
        with patch("services.orchestrator.start_execution") as mock_start:
            executor = WorkflowExecutor()
            executor.execute("exec-123", db=mock_db)
            mock_start.assert_called_once_with("exec-123", mock_db)

    def test_resume(self):
        from services.executor import WorkflowExecutor
        with patch("services.orchestrator.resume_node_job") as mock_resume:
            executor = WorkflowExecutor()
            executor.resume("exec-123", "yes")
            mock_resume.assert_called_once_with("exec-123", "yes")


class TestExecutorJobFunctions:
    def test_execute_workflow_job(self):
        from services.executor import execute_workflow_job
        with patch("services.orchestrator.start_execution_job") as mock_fn:
            execute_workflow_job("exec-1")
            mock_fn.assert_called_once_with("exec-1")

    def test_resume_workflow_job(self):
        from services.executor import resume_workflow_job
        with patch("services.orchestrator.resume_node_job") as mock_fn:
            resume_workflow_job("exec-1", "confirm")
            mock_fn.assert_called_once_with("exec-1", "confirm")


# ── tasks/__init__.py ─────────────────────────────────────────────────────────

class TestTaskWrappers:
    def test_execute_workflow_job(self):
        from tasks import execute_workflow_job
        with patch("services.orchestrator.start_execution_job") as mock_fn:
            execute_workflow_job("exec-1")
            mock_fn.assert_called_once_with("exec-1")

    def test_resume_workflow_job(self):
        from tasks import resume_workflow_job
        with patch("services.orchestrator.resume_node_job") as mock_fn:
            resume_workflow_job("exec-1", "yes")
            mock_fn.assert_called_once_with("exec-1", "yes")

    def test_execute_node_job(self):
        from tasks import execute_node_job
        with patch("services.orchestrator.execute_node_job") as mock_fn:
            execute_node_job("exec-1", "node-1", 0)
            mock_fn.assert_called_once_with("exec-1", "node-1", 0)

    def test_start_execution_job(self):
        from tasks import start_execution_job
        with patch("services.orchestrator.start_execution") as mock_fn:
            start_execution_job("exec-1")
            mock_fn.assert_called_once_with("exec-1")

    def test_module_name(self):
        """RQ needs the module name to be 'tasks' for job lookup."""
        import tasks
        assert tasks.execute_workflow_job.__module__ == "tasks"
        assert tasks.resume_workflow_job.__module__ == "tasks"
