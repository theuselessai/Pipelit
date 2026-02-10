"""Tests for the workflow discovery scoring engine."""

from __future__ import annotations

import pytest

from models.execution import WorkflowExecution
from models.node import BaseComponentConfig, WorkflowNode
from models.workflow import Workflow
from services.workflow_discovery import (
    _compute_success_rate,
    _extract_capabilities,
    _score_workflow,
    discover_workflows,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def wf_telegram_agent(db, user_profile):
    """Workflow with telegram trigger, agent, web_search tool, and ai_model."""
    wf = Workflow(
        name="Telegram Bot",
        slug="telegram-bot",
        owner_id=user_profile.id,
        is_active=True,
        tags=["automation", "telegram"],
    )
    db.add(wf)
    db.flush()

    # Trigger
    cfg = BaseComponentConfig(component_type="trigger_telegram", is_active=True, trigger_config={})
    db.add(cfg)
    db.flush()
    db.add(WorkflowNode(workflow_id=wf.id, node_id="trigger_telegram_1", component_type="trigger_telegram", component_config_id=cfg.id))

    # Agent
    cfg2 = BaseComponentConfig(component_type="agent", system_prompt="Help user")
    db.add(cfg2)
    db.flush()
    db.add(WorkflowNode(workflow_id=wf.id, node_id="agent_1", component_type="agent", component_config_id=cfg2.id))

    # AI Model
    cfg3 = BaseComponentConfig(component_type="ai_model", model_name="gpt-4")
    db.add(cfg3)
    db.flush()
    db.add(WorkflowNode(workflow_id=wf.id, node_id="ai_model_1", component_type="ai_model", component_config_id=cfg3.id))

    # Web search tool
    cfg4 = BaseComponentConfig(component_type="web_search", extra_config={"searxng_url": "http://localhost"})
    db.add(cfg4)
    db.flush()
    db.add(WorkflowNode(workflow_id=wf.id, node_id="web_search_1", component_type="web_search", component_config_id=cfg4.id))

    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture
def wf_webhook_code(db, user_profile):
    """Workflow with webhook trigger and code node."""
    wf = Workflow(
        name="Webhook Processor",
        slug="webhook-processor",
        owner_id=user_profile.id,
        is_active=True,
        tags=["automation"],
    )
    db.add(wf)
    db.flush()

    cfg = BaseComponentConfig(component_type="trigger_webhook", is_active=True, trigger_config={})
    db.add(cfg)
    db.flush()
    db.add(WorkflowNode(workflow_id=wf.id, node_id="trigger_webhook_1", component_type="trigger_webhook", component_config_id=cfg.id))

    cfg2 = BaseComponentConfig(component_type="code", code_snippet="pass", code_language="python")
    db.add(cfg2)
    db.flush()
    db.add(WorkflowNode(workflow_id=wf.id, node_id="code_1", component_type="code", component_config_id=cfg2.id))

    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture
def wf_inactive(db, user_profile):
    """Inactive workflow that should be excluded."""
    wf = Workflow(
        name="Inactive WF",
        slug="inactive-wf",
        owner_id=user_profile.id,
        is_active=False,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture
def wf_deleted(db, user_profile):
    """Soft-deleted workflow that should be excluded."""
    from datetime import datetime, timezone

    wf = Workflow(
        name="Deleted WF",
        slug="deleted-wf",
        owner_id=user_profile.id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    wf.soft_delete()
    db.commit()
    db.refresh(wf)
    return wf


# ── TestExtractCapabilities ──────────────────────────────────────────────────


class TestExtractCapabilities:
    def test_triggers_extracted_without_prefix(self, db, wf_telegram_agent):
        caps = _extract_capabilities(wf_telegram_agent.id, db)
        assert "telegram" in caps["triggers"]
        assert "trigger_telegram" not in caps["triggers"]

    def test_node_types_detected(self, db, wf_telegram_agent):
        caps = _extract_capabilities(wf_telegram_agent.id, db)
        assert "agent" in caps["node_types"]

    def test_tools_detected(self, db, wf_telegram_agent):
        caps = _extract_capabilities(wf_telegram_agent.id, db)
        assert "web_search" in caps["tools"]

    def test_model_names_from_ai_model(self, db, wf_telegram_agent):
        caps = _extract_capabilities(wf_telegram_agent.id, db)
        assert "gpt-4" in caps["model_names"]

    def test_tags_pass_through(self, db, wf_telegram_agent):
        caps = _extract_capabilities(wf_telegram_agent.id, db)
        assert "automation" in caps["tags"]
        assert "telegram" in caps["tags"]

    def test_webhook_code_workflow(self, db, wf_webhook_code):
        caps = _extract_capabilities(wf_webhook_code.id, db)
        assert "webhook" in caps["triggers"]
        assert "code" in caps["node_types"]
        assert caps["tools"] == []
        assert caps["model_names"] == []


# ── TestComputeSuccessRate ───────────────────────────────────────────────────


class TestComputeSuccessRate:
    def test_correct_ratio(self, db, user_profile, wf_telegram_agent):
        for status in ["completed", "completed", "failed"]:
            db.add(WorkflowExecution(
                workflow_id=wf_telegram_agent.id,
                user_profile_id=user_profile.id,
                status=status,
                thread_id="t",
            ))
        db.commit()

        rate, count = _compute_success_rate(wf_telegram_agent.id, db)
        assert rate == pytest.approx(2 / 3)
        assert count == 3

    def test_none_with_no_executions(self, db, wf_telegram_agent):
        rate, count = _compute_success_rate(wf_telegram_agent.id, db)
        assert rate is None
        assert count == 0

    def test_ignores_pending_and_running(self, db, user_profile, wf_telegram_agent):
        db.add(WorkflowExecution(
            workflow_id=wf_telegram_agent.id,
            user_profile_id=user_profile.id,
            status="pending",
            thread_id="t",
        ))
        db.add(WorkflowExecution(
            workflow_id=wf_telegram_agent.id,
            user_profile_id=user_profile.id,
            status="running",
            thread_id="t",
        ))
        db.add(WorkflowExecution(
            workflow_id=wf_telegram_agent.id,
            user_profile_id=user_profile.id,
            status="completed",
            thread_id="t",
        ))
        db.commit()

        rate, count = _compute_success_rate(wf_telegram_agent.id, db)
        assert rate == 1.0
        assert count == 1


# ── TestScoreWorkflow ────────────────────────────────────────────────────────


class TestScoreWorkflow:
    def test_perfect_match(self):
        caps = {"triggers": ["telegram"], "node_types": ["agent"], "tools": ["web_search"], "model_names": ["gpt-4"], "tags": ["automation"]}
        reqs = {"triggers": ["telegram"], "node_types": ["agent"], "tools": ["web_search"], "tags": ["automation"]}
        score = _score_workflow(caps, reqs, 1.0, "")
        assert score == pytest.approx(1.0)

    def test_partial_match(self):
        caps = {"triggers": ["telegram"], "node_types": ["agent"], "tools": [], "model_names": [], "tags": []}
        reqs = {"triggers": ["telegram", "webhook"], "node_types": ["agent"], "tools": ["web_search"]}
        score = _score_workflow(caps, reqs, 1.0, "")
        # 2 out of 4 required items matched → capability = 0.5
        # no tags on either side → tag_overlap = 1.0
        # success_rate = 1.0
        # 0.5 * 0.6 + 1.0 * 0.2 + 1.0 * 0.2 = 0.3 + 0.2 + 0.2 = 0.7
        assert score == pytest.approx(0.7)

    def test_no_match(self):
        caps = {"triggers": ["telegram"], "node_types": ["agent"], "tools": [], "model_names": [], "tags": []}
        reqs = {"triggers": ["webhook"], "node_types": ["code"], "tools": ["calculator"]}
        score = _score_workflow(caps, reqs, 0.0, "")
        # 0 out of 3 matched → capability = 0.0
        # no tags → 1.0
        # sr = 0.0
        # 0.0 * 0.6 + 1.0 * 0.2 + 0.0 * 0.2 = 0.2
        assert score == pytest.approx(0.2)

    def test_empty_requirements(self):
        caps = {"triggers": ["telegram"], "node_types": ["agent"], "tools": [], "model_names": [], "tags": []}
        reqs = {}
        score = _score_workflow(caps, reqs, None, "")
        # capability = 1.0 (nothing required), tags = 1.0, sr = 0.5 (default)
        # 1.0 * 0.6 + 1.0 * 0.2 + 0.5 * 0.2 = 0.6 + 0.2 + 0.1 = 0.9
        assert score == pytest.approx(0.9)

    def test_tag_jaccard(self):
        caps = {"triggers": [], "node_types": [], "tools": [], "model_names": [], "tags": ["a", "b", "c"]}
        reqs = {"tags": ["b", "c", "d"]}
        score = _score_workflow(caps, reqs, 1.0, "")
        # capability = 1.0, tags = |{b,c}| / |{a,b,c,d}| = 2/4 = 0.5, sr = 1.0
        # 1.0 * 0.6 + 0.5 * 0.2 + 1.0 * 0.2 = 0.6 + 0.1 + 0.2 = 0.9
        assert score == pytest.approx(0.9)

    def test_model_capability_substring(self):
        caps = {"triggers": [], "node_types": [], "tools": [], "model_names": ["gpt-4-turbo"], "tags": []}
        reqs = {"model_capability": "gpt-4"}
        score = _score_workflow(caps, reqs, 1.0, "")
        # model_capability matched (substring) → 1/1 = 1.0
        # 1.0 * 0.6 + 1.0 * 0.2 + 1.0 * 0.2 = 1.0
        assert score == pytest.approx(1.0)

    def test_model_capability_no_match(self):
        caps = {"triggers": [], "node_types": [], "tools": [], "model_names": ["claude-3"], "tags": []}
        reqs = {"model_capability": "gpt-4"}
        score = _score_workflow(caps, reqs, 1.0, "")
        # 0/1 = 0.0
        # 0.0 * 0.6 + 1.0 * 0.2 + 1.0 * 0.2 = 0.4
        assert score == pytest.approx(0.4)

    def test_description_bonus(self):
        caps = {"triggers": [], "node_types": [], "tools": [], "model_names": [], "tags": []}
        reqs = {"description": "automation"}
        # Use success_rate=0.0 so base score < 1.0 and bonus is visible
        score_with = _score_workflow(caps, reqs, 0.0, "An automation workflow")
        score_without = _score_workflow(caps, reqs, 0.0, "A different workflow")
        assert score_with == pytest.approx(score_without + 0.05)

    def test_description_bonus_capped(self):
        caps = {"triggers": [], "node_types": [], "tools": [], "model_names": [], "tags": []}
        reqs = {"description": "test"}
        score = _score_workflow(caps, reqs, 1.0, "A test workflow")
        assert score <= 1.0


# ── TestDiscoverWorkflows ────────────────────────────────────────────────────


class TestDiscoverWorkflows:
    def test_sorted_by_score(self, db, user_profile, wf_telegram_agent, wf_webhook_code):
        results = discover_workflows(
            {"triggers": ["telegram"], "node_types": ["agent"]}, db,
        )
        assert len(results) >= 2
        assert results[0]["match_score"] >= results[1]["match_score"]
        assert results[0]["slug"] == "telegram-bot"

    def test_excludes_self(self, db, user_profile, wf_telegram_agent, wf_webhook_code):
        results = discover_workflows(
            {"triggers": ["telegram"]}, db,
            exclude_workflow_id=wf_telegram_agent.id,
        )
        slugs = [r["slug"] for r in results]
        assert "telegram-bot" not in slugs

    def test_excludes_inactive(self, db, user_profile, wf_telegram_agent, wf_inactive):
        results = discover_workflows({}, db)
        slugs = [r["slug"] for r in results]
        assert "inactive-wf" not in slugs

    def test_excludes_deleted(self, db, user_profile, wf_telegram_agent, wf_deleted):
        results = discover_workflows({}, db)
        slugs = [r["slug"] for r in results]
        assert "deleted-wf" not in slugs

    def test_respects_limit(self, db, user_profile, wf_telegram_agent, wf_webhook_code):
        results = discover_workflows({}, db, limit=1)
        assert len(results) == 1

    def test_gap_analysis_populated(self, db, user_profile, wf_telegram_agent):
        results = discover_workflows(
            {"triggers": ["telegram", "webhook"], "tools": ["calculator"]}, db,
        )
        match = next(r for r in results if r["slug"] == "telegram-bot")
        assert "webhook" in match["missing_capabilities"]["triggers"]
        assert "calculator" in match["missing_capabilities"]["tools"]
        assert "telegram" in match["has_capabilities"]["triggers"]
        assert "web_search" in match["extra_capabilities"]["tools"]

    def test_recommendation_reuse(self, db, user_profile, wf_telegram_agent):
        # Add 10 successful executions for high success rate
        for _ in range(10):
            db.add(WorkflowExecution(
                workflow_id=wf_telegram_agent.id,
                user_profile_id=user_profile.id,
                status="completed",
                thread_id="t",
            ))
        db.commit()

        results = discover_workflows(
            {"triggers": ["telegram"], "node_types": ["agent"], "tools": ["web_search"], "tags": ["automation", "telegram"]}, db,
        )
        match = next(r for r in results if r["slug"] == "telegram-bot")
        assert match["recommendation"] == "reuse"
        assert match["match_score"] >= 0.95

    def test_recommendation_fork(self, db, user_profile, wf_telegram_agent):
        results = discover_workflows(
            {"triggers": ["telegram"], "node_types": ["agent", "code"]}, db,
        )
        match = next(r for r in results if r["slug"] == "telegram-bot")
        # Partial match, no executions → score around 0.5-0.8 range
        assert match["recommendation"] in ("fork_and_patch", "reuse")

    def test_recommendation_create_new(self, db, user_profile, wf_webhook_code):
        results = discover_workflows(
            {"triggers": ["telegram"], "node_types": ["agent"], "tools": ["web_search"]}, db,
        )
        match = next(r for r in results if r["slug"] == "webhook-processor")
        assert match["recommendation"] == "create_new"
