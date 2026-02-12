"""DSL Compiler — YAML workflow spec to database objects.

Parses a YAML DSL string and creates Workflow + WorkflowNode + WorkflowEdge
rows in a single transaction.  Supports two modes:

* **Create mode** — ``name``, ``trigger``, ``steps`` define a new workflow.
* **Fork & patch mode** — ``based_on`` clones an existing workflow and applies
  ``patches`` (add_step, remove_step, update_prompt, add_tool, remove_tool,
  update_config).

Model resolution strategies:
  ``inherit: true``  — copy from a parent agent node (caller context)
  ``capability: "gpt-4"`` — find first LLMProviderCredential matching substring
  ``credential_id: N``  — direct pass-through
  ``discover: true``  — auto-discover best model from available credentials
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

import yaml
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from models.credential import BaseCredential, LLMProviderCredential
from models.node import (
    BaseComponentConfig,
    WorkflowEdge,
    WorkflowNode,
)
from models.workflow import Workflow

logger = logging.getLogger(__name__)

# ── Step type → component_type mapping ───────────────────────────────────────

STEP_TYPE_MAP: dict[str, str] = {
    "code": "code",
    "agent": "agent",
    "http": "http_request",
    "switch": "switch",
    "loop": "loop",
    "workflow": "workflow",
    "human": "human_confirmation",
    "transform": "code",
}

TRIGGER_TYPE_MAP: dict[str, str] = {
    "webhook": "trigger_webhook",
    "telegram": "trigger_telegram",
    "chat": "trigger_chat",
    "none": "trigger_workflow",
    "manual": "trigger_manual",
}

TOOL_TYPE_MAP: dict[str, str] = {
    "code": "code_execute",
    "http_request": "http_request",
    "web_search": "web_search",
    "calculator": "calculator",
    "datetime": "datetime",
}

# ── Model preference table for discover mode ─────────────────────────────────

# Maps model name substrings to (cost, speed, capability) scores (0-100).
# Higher = more expensive / slower / more capable.
MODEL_PREFERENCE_TABLE: dict[str, tuple[int, int, int]] = {
    # OpenAI
    "gpt-4o-mini": (20, 90, 60),
    "gpt-4o": (50, 70, 85),
    "gpt-4-turbo": (60, 60, 82),
    "gpt-4": (70, 50, 80),
    "gpt-3.5-turbo": (10, 95, 50),
    "o1-mini": (30, 80, 75),
    "o1": (80, 40, 90),
    # Anthropic
    "claude-3-haiku": (15, 95, 55),
    "claude-haiku-3-5": (18, 90, 60),
    "claude-3-5-sonnet": (40, 70, 85),
    "claude-sonnet-4": (45, 65, 88),
    "claude-opus": (90, 30, 95),
    # Open-source
    "llama-3.1-8b": (5, 95, 45),
    "llama-3.1-70b": (25, 60, 70),
    "llama-3.1-405b": (50, 40, 80),
    "mixtral-8x7b": (15, 80, 55),
    "mixtral-8x22b": (30, 60, 65),
    "mistral-large": (35, 55, 70),
    "mistral-small": (10, 90, 45),
    "qwen-2.5-72b": (25, 60, 70),
    "deepseek-v3": (15, 75, 72),
    "deepseek-r1": (20, 50, 78),
    "gemma-2-27b": (15, 70, 58),
}


# ── Public API ───────────────────────────────────────────────────────────────


def compile_dsl(
    yaml_str: str,
    owner_id: int,
    db: Session,
    parent_node: WorkflowNode | None = None,
) -> dict:
    """Compile a YAML DSL string into a persisted workflow.

    Returns ``{"success": True, "workflow_id": ..., "slug": ..., ...}``
    or ``{"success": False, "error": "..."}`` on failure.
    """
    try:
        parsed = _parse_dsl(yaml_str)

        # Fork & patch mode
        if "based_on" in parsed:
            return _compile_fork(parsed, owner_id, db)

        # Create mode
        model_spec = parsed.get("model", {})
        model_info = _resolve_model(model_spec, parent_node, db)

        nodes, edges = _build_graph(parsed, model_info, db, parent_node)

        return _persist_workflow(
            name=parsed["name"],
            description=parsed.get("description", ""),
            tags=parsed.get("tags", []),
            owner_id=owner_id,
            nodes=nodes,
            edges=edges,
            db=db,
        )
    except Exception as exc:
        logger.exception("DSL compilation failed")
        return {"success": False, "error": str(exc)}


def validate_dsl(
    yaml_str: str,
    db: Session,
    parent_node: WorkflowNode | None = None,
) -> dict:
    """Validate a YAML DSL string without persisting.

    Returns ``{"valid": bool, "errors": list[str], "node_count": int, "edge_count": int}``.
    """
    errors: list[str] = []
    node_count = 0
    edge_count = 0

    # Stage 1: Parse
    try:
        parsed = _parse_dsl(yaml_str)
    except Exception as exc:
        errors.append(f"Parse error: {exc}")
        return {"valid": False, "errors": errors, "node_count": 0, "edge_count": 0}

    if "based_on" in parsed:
        # Fork mode — validate source exists
        source_slug = parsed["based_on"]
        source = db.query(Workflow).filter_by(slug=source_slug).first()
        if not source:
            errors.append(f"Source workflow '{source_slug}' not found")
        return {"valid": len(errors) == 0, "errors": errors, "node_count": 0, "edge_count": 0}

    # Stage 2: Model resolution
    model_spec = parsed.get("model", {})
    try:
        model_info = _resolve_model(model_spec, parent_node, db)
    except Exception as exc:
        errors.append(f"Model resolution error: {exc}")
        model_info = (None, None, None)

    # Stage 3: Build graph
    try:
        nodes, edges = _build_graph(parsed, model_info, db, parent_node)
        node_count = len(nodes)
        edge_count = len(edges)
    except Exception as exc:
        errors.append(f"Graph build error: {exc}")

    return {"valid": len(errors) == 0, "errors": errors, "node_count": node_count, "edge_count": edge_count}


# ── Stage 1: Parse ───────────────────────────────────────────────────────────


def _parse_dsl(yaml_str: str) -> dict:
    """Parse and validate top-level YAML structure."""
    try:
        parsed = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("DSL must be a YAML mapping (dict)")

    # Fork mode — needs based_on + patches
    if "based_on" in parsed:
        if not isinstance(parsed["based_on"], str):
            raise ValueError("`based_on` must be a workflow slug string")
        if "patches" not in parsed:
            raise ValueError("Fork mode requires a `patches` list")
        if not isinstance(parsed["patches"], list):
            raise ValueError("`patches` must be a list")
        return parsed

    # Create mode — needs name + steps
    if "name" not in parsed:
        raise ValueError("DSL requires a `name` field")
    if "steps" not in parsed:
        raise ValueError("DSL requires a `steps` list")
    if not isinstance(parsed["steps"], list) or len(parsed["steps"]) == 0:
        raise ValueError("`steps` must be a non-empty list")

    # Normalize and validate trigger — accept both string ("webhook")
    # and dict ({"type": "webhook"}) forms per the DSL spec.
    trigger = parsed.setdefault("trigger", "none")
    if isinstance(trigger, dict):
        trigger = trigger.get("type", "none")
        parsed["trigger"] = trigger
    if isinstance(trigger, str) and trigger not in TRIGGER_TYPE_MAP:
        raise ValueError(
            f"Unknown trigger type '{trigger}'. "
            f"Valid: {', '.join(TRIGGER_TYPE_MAP)}"
        )

    # Validate each step
    seen_ids: set[str] = set()
    for i, step in enumerate(parsed["steps"]):
        if not isinstance(step, dict):
            raise ValueError(f"Step {i} must be a mapping")
        step_type = step.get("type")
        if not step_type:
            raise ValueError(f"Step {i} missing `type` field")
        if step_type not in STEP_TYPE_MAP:
            raise ValueError(
                f"Unknown step type '{step_type}' in step {i}. "
                f"Valid: {', '.join(STEP_TYPE_MAP)}"
            )
        step_id = step.get("id", f"{STEP_TYPE_MAP[step_type]}_{i + 1}")
        if step_id in seen_ids:
            raise ValueError(f"Duplicate step ID '{step_id}' in step {i}")
        seen_ids.add(step_id)

    return parsed


# ── Stage 2: Model resolution ────────────────────────────────────────────────


def _resolve_model(
    model_spec: dict,
    parent_node: WorkflowNode | None,
    db: Session,
) -> tuple[int | None, str | None, float | None]:
    """Resolve model specification to (credential_id, model_name, temperature).

    Strategies:
      inherit   — copy from parent_node's linked ai_model
      capability — substring-match against available LLM credentials
      credential_id — direct pass-through
      discover — auto-discover best model from available credentials
    """
    if not model_spec:
        return (None, None, None)

    # Inherit from parent agent's ai_model
    if model_spec.get("inherit") and parent_node:
        config = parent_node.component_config
        if config:
            # For agent nodes, the model info lives on the linked ai_model config
            # Check if there's a direct ai_model connection via edge
            edges = (
                db.query(WorkflowEdge)
                .filter_by(workflow_id=parent_node.workflow_id, target_node_id=parent_node.node_id, edge_label="llm")
                .all()
            )
            for edge in edges:
                ai_node = (
                    db.query(WorkflowNode)
                    .filter_by(workflow_id=parent_node.workflow_id, node_id=edge.source_node_id)
                    .first()
                )
                if ai_node and ai_node.component_config:
                    ai_cfg = ai_node.component_config
                    return (ai_cfg.llm_credential_id, ai_cfg.model_name, ai_cfg.temperature)
            # Fallback: check the agent config itself
            return (config.llm_credential_id, config.model_name, config.temperature)
        raise ValueError("Cannot inherit model: parent node has no config")

    # Discover mode — auto-select best model from available credentials
    if model_spec.get("discover"):
        preference = model_spec.get("preference", "cheapest")
        temperature = model_spec.get("temperature")
        return _discover_model(preference, temperature, db)

    # Capability-based resolution — the capability string is treated as the
    # desired model name.  We first try to match it against provider_type
    # (e.g. capability: "anthropic"), then fall back to the first available
    # credential, passing capability through as model_name for the provider
    # to resolve.
    if "capability" in model_spec:
        capability = model_spec["capability"]
        creds = (
            db.query(LLMProviderCredential)
            .join(BaseCredential, LLMProviderCredential.base_credentials_id == BaseCredential.id)
            .all()
        )
        if not creds:
            raise ValueError(f"No LLM credential found for capability '{capability}'")
        # Prefer a credential whose provider_type matches (e.g. "anthropic")
        for cred in creds:
            if capability.lower() in (cred.provider_type or "").lower():
                return (cred.base_credentials_id, capability, model_spec.get("temperature"))
        # Otherwise use the first credential — the user-supplied capability
        # string is passed as model_name for the provider API to resolve.
        return (creds[0].base_credentials_id, capability, model_spec.get("temperature"))

    # Direct credential_id
    if "credential_id" in model_spec:
        return (
            model_spec["credential_id"],
            model_spec.get("model_name", ""),
            model_spec.get("temperature"),
        )

    return (None, None, None)


def _discover_model(
    preference: str,
    temperature: float | None,
    db: Session,
) -> tuple[int, str, float | None]:
    """Auto-discover the best model from available LLM credentials.

    Preference can be "cheapest", "fastest", or "most_capable".
    """
    creds = (
        db.query(LLMProviderCredential)
        .join(BaseCredential, LLMProviderCredential.base_credentials_id == BaseCredential.id)
        .all()
    )
    if not creds:
        raise ValueError("No LLM credentials available for model discovery")

    best_score: float = -1
    best_cred_id: int | None = None
    best_model: str | None = None

    for cred in creds:
        model_ids = _fetch_model_ids(cred)
        for model_id in model_ids:
            score = _score_model(model_id, preference)
            if score > best_score:
                best_score = score
                best_cred_id = cred.base_credentials_id
                best_model = model_id

    if best_cred_id is None or best_model is None:
        # No models could be scored — raise rather than guessing
        raise ValueError("No scoreable models found across available credentials")

    return (best_cred_id, best_model, temperature)


def _fetch_model_ids(cred: LLMProviderCredential) -> list[str]:
    """Fetch available model IDs from a credential. Best-effort, silent on failure."""
    if cred.provider_type == "anthropic":
        return [
            "claude-sonnet-4-20250514",
            "claude-opus-4-0-20250514",
            "claude-haiku-3-5-20241022",
            "claude-3-5-sonnet-20241022",
        ]
    # For OpenAI-compatible providers, try the /models endpoint
    try:
        import httpx
        base_url = (cred.base_url or "https://api.openai.com/v1").rstrip("/")
        resp = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {cred.api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [m["id"] for m in data if "id" in m]
    except Exception:
        return []


def _score_model(model_id: str, preference: str) -> float:
    """Score a model ID based on preference using substring matching."""
    model_lower = model_id.lower()
    best_match_score = 0.0

    for substring, (cost, speed, capability) in MODEL_PREFERENCE_TABLE.items():
        if substring.lower() in model_lower:
            if preference == "cheapest":
                score = 100 - cost  # Lower cost = higher score
            elif preference == "fastest":
                score = speed
            elif preference == "most_capable":
                score = capability
            else:
                score = 100 - cost  # Default to cheapest
            if score > best_match_score:
                best_match_score = score
    return best_match_score


# ── Stage 3: Build graph ─────────────────────────────────────────────────────


def _build_step_config(
    step: dict,
    step_type: str,
    model_info: tuple[int | None, str | None, float | None],
    db: Session,
    parent_node: WorkflowNode | None = None,
) -> dict[str, Any]:
    """Build the config dict for a single step based on its type.

    Returns a config dict suitable for node creation.
    """
    cred_id, model_name, temperature = model_info
    config: dict[str, Any] = {}

    if step_type == "code":
        # Accept snippet, code, or config.code (LLMs use all three forms)
        step_config = step.get("config", {}) if isinstance(step.get("config"), dict) else {}
        code_content = (
            step.get("snippet")
            or step.get("code")
            or step_config.get("code", "")
        )
        code_content = _strip_markdown_fences(code_content)
        config["extra_config"] = {
            "code": code_content,
            "language": step.get("language") or step_config.get("language", "python"),
        }

    elif step_type == "agent":
        config["system_prompt"] = step.get("prompt") or step.get("system_prompt", "")
        # Model: step-level override → workflow-level default → inherit from parent
        step_model = step.get("model", {})
        if step_model:
            s_cred, s_model, s_temp = _resolve_model(step_model, parent_node, db)
            config["llm_credential_id"] = s_cred
            config["model_name"] = s_model
            config["temperature"] = s_temp
        elif cred_id is not None:
            config["llm_credential_id"] = cred_id
            config["model_name"] = model_name
            config["temperature"] = temperature
        elif parent_node:
            # Auto-inherit from parent agent when no model specified
            inherit_info = _resolve_model({"inherit": True}, parent_node, db)
            if inherit_info[0] is not None:
                config["llm_credential_id"] = inherit_info[0]
                config["model_name"] = inherit_info[1]
                config["temperature"] = inherit_info[2]
        # Memory
        extra = {}
        if step.get("memory"):
            extra["conversation_memory"] = True
        config["extra_config"] = extra

    elif step_type == "http":
        config["extra_config"] = {
            "url": step.get("url", ""),
            "method": step.get("method", "GET"),
            "headers": step.get("headers", {}),
            "body": step.get("body", ""),
            "timeout": step.get("timeout", 30),
        }

    elif step_type == "switch":
        rules = []
        for rule in step.get("rules", []):
            rules.append({
                "id": rule.get("route", ""),
                "field": rule.get("field", ""),
                "operator": rule.get("operator", "equals"),
                "value": rule.get("value", ""),
            })
        config["extra_config"] = {
            "rules": rules,
            "enable_fallback": bool(step.get("default")),
        }

    elif step_type == "loop":
        over_expr = step.get("over", "")
        source_node, field = _parse_over_expression(over_expr)
        config["extra_config"] = {
            "source_node": source_node,
            "field": field,
            "max_iterations": step.get("max_iterations", 100),
        }

    elif step_type == "workflow":
        config["extra_config"] = {
            "target_workflow": step.get("workflow", ""),
            "trigger_mode": "implicit",
            "input_mapping": step.get("payload", {}),
        }

    elif step_type == "human":
        config["extra_config"] = {
            "prompt": step.get("message", ""),
        }

    elif step_type == "transform":
        template = step.get("template", "")
        config["extra_config"] = {
            "code": f'return f"""{template}"""',
            "language": "python",
        }

    return config


def _parse_over_expression(expr: str) -> tuple[str, str]:
    """Parse a loop ``over`` expression like ``{{ node_id.field }}`` or ``node_id.field``.

    Returns (source_node, field) tuple.
    """
    if not expr:
        return ("", "")
    # Strip Jinja2 delimiters
    cleaned = expr.strip()
    cleaned = re.sub(r"^\{\{\s*", "", cleaned)
    cleaned = re.sub(r"\s*\}\}$", "", cleaned)
    cleaned = cleaned.strip()
    parts = cleaned.split(".", 1)
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (parts[0], "output")


def _resolve_tool_inherit(
    tool_component_type: str,
    config_key: str,
    parent_node: WorkflowNode | None,
    db: Session,
) -> Any:
    """Resolve a tool config value by inheriting from parent node's connected tools.

    Looks up edges with edge_label="tool" targeting the parent node, finds a source
    node whose component_type matches, and returns the specified key from its extra_config.
    """
    if not parent_node:
        raise ValueError("Cannot inherit tool config: no parent node")

    edges = (
        db.query(WorkflowEdge)
        .filter_by(
            workflow_id=parent_node.workflow_id,
            target_node_id=parent_node.node_id,
            edge_label="tool",
        )
        .all()
    )

    for edge in edges:
        tool_node = (
            db.query(WorkflowNode)
            .filter_by(workflow_id=parent_node.workflow_id, node_id=edge.source_node_id)
            .first()
        )
        if tool_node and tool_node.component_type == tool_component_type:
            tool_cfg = tool_node.component_config
            if tool_cfg and tool_cfg.extra_config:
                val = tool_cfg.extra_config.get(config_key)
                if val is not None:
                    return val
                raise ValueError(
                    f"Parent tool '{tool_component_type}' has no key '{config_key}' in extra_config"
                )

    raise ValueError(
        f"No matching tool '{tool_component_type}' found on parent node '{parent_node.node_id}'"
    )


def _build_graph(
    parsed: dict,
    model_info: tuple[int | None, str | None, float | None],
    db: Session,
    parent_node: WorkflowNode | None = None,
) -> tuple[list[dict], list[dict]]:
    """Convert parsed DSL steps into node/edge dicts.

    Returns (nodes_list, edges_list) where each item is a dict of kwargs for
    WorkflowNode / WorkflowEdge / BaseComponentConfig creation.
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    cred_id, model_name, temperature = model_info

    # ── Trigger node ─────────────────────────────────────────────────────
    trigger_type_str = parsed.get("trigger", "manual")
    component_type = TRIGGER_TYPE_MAP[trigger_type_str]
    trigger_node_id = f"{component_type}_1"

    nodes.append({
        "node_id": trigger_node_id,
        "component_type": component_type,
        "is_entry_point": False,
        "position_x": 0,
        "position_y": 200,
        "config": {
            "is_active": True,
            "trigger_config": parsed.get("trigger_config", {}),
        },
    })

    prev_node_id = trigger_node_id
    x_offset = 300

    # ── Pre-scan: collect claimed step IDs (switch route targets) ─────
    claimed_step_ids: set[str] = set()
    for step in parsed["steps"]:
        if step["type"] == "switch":
            for rule in step.get("rules", []):
                route_target = rule.get("route", "")
                if route_target:
                    claimed_step_ids.add(route_target)
            default_target = step.get("default", "")
            if default_target:
                claimed_step_ids.add(default_target)

    # ── Step nodes ───────────────────────────────────────────────────────
    for i, step in enumerate(parsed["steps"]):
        step_type = step["type"]
        step_component = STEP_TYPE_MAP[step_type]
        step_id = step.get("id", f"{step_component}_{i + 1}")
        is_first_exec = i == 0

        config = _build_step_config(step, step_type, model_info, db, parent_node)

        # Resolve tool config inheritance (value == "inherit")
        if isinstance(config.get("extra_config"), dict):
            for key, val in list(config["extra_config"].items()):
                if val == "inherit":
                    config["extra_config"][key] = _resolve_tool_inherit(
                        step_component, key, parent_node, db,
                    )

        node_dict: dict[str, Any] = {
            "node_id": step_id,
            "component_type": step_component,
            "is_entry_point": is_first_exec,
            "position_x": x_offset,
            "position_y": 200,
            "config": config,
        }

        # Human step needs interrupt_before
        if step_type == "human":
            node_dict["interrupt_before"] = True

        # Workflow step needs subworkflow_id resolution
        if step_type == "workflow":
            target_slug = step.get("workflow", "")
            if target_slug:
                target_wf = db.query(Workflow).filter_by(slug=target_slug).first()
                if target_wf:
                    node_dict["subworkflow_id"] = target_wf.id

        nodes.append(node_dict)

        # Linear edge: prev → current (skip for claimed step IDs)
        if prev_node_id is not None and step_id not in claimed_step_ids:
            edges.append({
                "source_node_id": prev_node_id,
                "target_node_id": step_id,
                "edge_type": "direct",
                "edge_label": "",
            })

        # ── Switch step: conditional edges ───────────────────────────
        if step_type == "switch":
            for rule in step.get("rules", []):
                route_target = rule.get("route", "")
                if route_target:
                    edges.append({
                        "source_node_id": step_id,
                        "target_node_id": route_target,
                        "edge_type": "conditional",
                        "edge_label": "",
                        "condition_value": route_target,
                    })
            default_target = step.get("default", "")
            if default_target:
                edges.append({
                    "source_node_id": step_id,
                    "target_node_id": default_target,
                    "edge_type": "conditional",
                    "edge_label": "",
                    "condition_value": "__other__",
                })
            # Break linear chain after switch — routes via conditional edges
            prev_node_id = None
            x_offset += 300
            continue

        # ── Loop step: body nodes and edges ──────────────────────────
        if step_type == "loop":
            body_steps = step.get("body", [])
            if not body_steps:
                raise ValueError(f"Loop step '{step_id}' requires a non-empty `body` list")

            body_prev_id: str | None = None
            for bi, body_step in enumerate(body_steps):
                body_type = body_step.get("type", "code")
                if body_type not in STEP_TYPE_MAP:
                    raise ValueError(f"Unknown step type '{body_type}' in loop body")
                body_component = STEP_TYPE_MAP[body_type]
                body_id = body_step.get("id", f"{step_id}_body_{bi + 1}")
                body_config = _build_step_config(body_step, body_type, model_info, db, parent_node)

                nodes.append({
                    "node_id": body_id,
                    "component_type": body_component,
                    "is_entry_point": False,
                    "position_x": x_offset + (bi * 200),
                    "position_y": 350,
                    "config": body_config,
                })

                if bi == 0:
                    # loop → first body (loop_body edge)
                    edges.append({
                        "source_node_id": step_id,
                        "target_node_id": body_id,
                        "edge_type": "direct",
                        "edge_label": "loop_body",
                    })
                else:
                    # body[n-1] → body[n]
                    edges.append({
                        "source_node_id": body_prev_id,
                        "target_node_id": body_id,
                        "edge_type": "direct",
                        "edge_label": "",
                    })
                body_prev_id = body_id

            # last body → loop (loop_return edge)
            if body_prev_id:
                edges.append({
                    "source_node_id": body_prev_id,
                    "target_node_id": step_id,
                    "edge_type": "direct",
                    "edge_label": "loop_return",
                })

        # ── Agent sub-components ─────────────────────────────────────
        if step_type == "agent":
            # ai_model node (if model is specified)
            if config.get("llm_credential_id"):
                model_node_id = f"ai_model_{step_id}"
                nodes.append({
                    "node_id": model_node_id,
                    "component_type": "ai_model",
                    "is_entry_point": False,
                    "position_x": x_offset - 50,
                    "position_y": 350,
                    "config": {
                        "llm_credential_id": config.get("llm_credential_id"),
                        "model_name": config.get("model_name"),
                        "temperature": config.get("temperature"),
                    },
                })
                edges.append({
                    "source_node_id": model_node_id,
                    "target_node_id": step_id,
                    "edge_type": "direct",
                    "edge_label": "llm",
                })

            # Inline tools
            for j, tool_spec in enumerate(step.get("tools", [])):
                if not isinstance(tool_spec, (str, dict)):
                    raise ValueError(f"Tool {j} in step '{step_id}' must be a string or mapping, got {type(tool_spec).__name__}")
                tool_type = tool_spec if isinstance(tool_spec, str) else tool_spec.get("type", "")
                tool_component = TOOL_TYPE_MAP.get(tool_type)
                if not tool_component:
                    raise ValueError(
                        f"Unknown inline tool type '{tool_type}'. "
                        f"Valid: {', '.join(TOOL_TYPE_MAP)}"
                    )
                tool_node_id = f"{tool_component}_{step_id}_{j + 1}"
                tool_config: dict[str, Any] = {}

                # Tool-specific config from dict-form specs
                if isinstance(tool_spec, dict):
                    tool_extra = {k: v for k, v in tool_spec.items() if k != "type"}
                    if tool_extra:
                        tool_config["extra_config"] = tool_extra

                nodes.append({
                    "node_id": tool_node_id,
                    "component_type": tool_component,
                    "is_entry_point": False,
                    "position_x": x_offset + 50,
                    "position_y": 350 + j * 80,
                    "config": tool_config,
                })
                edges.append({
                    "source_node_id": tool_node_id,
                    "target_node_id": step_id,
                    "edge_type": "direct",
                    "edge_label": "tool",
                })

        prev_node_id = step_id
        x_offset += 300

    return nodes, edges


# ── Stage 4: Persist ─────────────────────────────────────────────────────────


def _persist_workflow(
    name: str,
    description: str,
    tags: list,
    owner_id: int,
    nodes: list[dict],
    edges: list[dict],
    db: Session,
    forked_from_id: int | None = None,
) -> dict:
    """Create Workflow + all nodes/edges in a single transaction."""
    slug = _unique_slug(name, db)

    workflow = Workflow(
        name=name,
        slug=slug,
        description=description,
        owner_id=owner_id,
        tags=tags or [],
        is_active=True,
        is_callable=True,
        forked_from_id=forked_from_id,
    )
    db.add(workflow)
    db.flush()  # get workflow.id

    # Create nodes
    for nd in nodes:
        config_kwargs = dict(nd.get("config", {}))
        comp_type = nd["component_type"]
        # Remove component_type from kwargs — we pass it explicitly below.
        # Use BaseComponentConfig directly (same as API nodes.py) — STI
        # discriminator is set via component_type kwarg.
        config_kwargs.pop("component_type", None)
        config = BaseComponentConfig(component_type=comp_type, **config_kwargs)
        db.add(config)
        db.flush()

        node = WorkflowNode(
            workflow_id=workflow.id,
            node_id=nd["node_id"],
            component_type=comp_type,
            component_config_id=config.id,
            is_entry_point=nd.get("is_entry_point", False),
            interrupt_before=nd.get("interrupt_before", False),
            subworkflow_id=nd.get("subworkflow_id"),
            position_x=nd.get("position_x", 0),
            position_y=nd.get("position_y", 0),
        )
        db.add(node)

    db.flush()

    # Create edges
    for ed in edges:
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id=ed["source_node_id"],
            target_node_id=ed["target_node_id"],
            edge_type=ed.get("edge_type", "direct"),
            edge_label=ed.get("edge_label", ""),
            condition_value=ed.get("condition_value", ""),
        )
        db.add(edge)

    db.commit()
    db.refresh(workflow)

    # Broadcast creation event
    try:
        from ws.broadcast import broadcast
        broadcast(f"workflow:{slug}", "workflow_created", {"slug": slug, "name": name})
    except Exception:
        pass  # WS broadcast is best-effort

    node_count = len(nodes)
    edge_count = len(edges)
    return {
        "success": True,
        "workflow_id": workflow.id,
        "slug": slug,
        "node_count": node_count,
        "edge_count": edge_count,
        "mode": "forked" if forked_from_id else "created",
    }


# ── Fork & patch ─────────────────────────────────────────────────────────────


def _compile_fork(parsed: dict, owner_id: int, db: Session) -> dict:
    """Clone an existing workflow and apply patches."""
    source_slug = parsed["based_on"]
    source = db.query(Workflow).filter_by(slug=source_slug).first()
    if not source:
        raise ValueError(f"Source workflow '{source_slug}' not found")

    # Load source nodes and edges
    source_nodes = db.query(WorkflowNode).filter_by(workflow_id=source.id).all()
    source_edges = db.query(WorkflowEdge).filter_by(workflow_id=source.id).all()

    # Build node dicts from source
    node_dicts: list[dict] = []
    old_config_to_new: dict[int, dict] = {}  # old config id → config kwargs

    _SKIP_CONFIG_COLUMNS = {"id", "updated_at"}

    for sn in source_nodes:
        cfg = sn.component_config
        config_kwargs: dict[str, Any] = {}
        # Copy all column attributes via SQLAlchemy inspect (future-proof)
        for col in sa_inspect(type(cfg)).columns:
            if col.key in _SKIP_CONFIG_COLUMNS:
                continue
            val = getattr(cfg, col.key, None)
            if val is not None:
                config_kwargs[col.key] = copy.deepcopy(val) if isinstance(val, (dict, list)) else val

        nd = {
            "node_id": sn.node_id,
            "component_type": sn.component_type,
            "is_entry_point": sn.is_entry_point,
            "position_x": sn.position_x,
            "position_y": sn.position_y,
            "config": config_kwargs,
        }
        node_dicts.append(nd)

    # Build edge dicts from source
    edge_dicts: list[dict] = []
    for se in source_edges:
        edge_dicts.append({
            "source_node_id": se.source_node_id,
            "target_node_id": se.target_node_id,
            "edge_type": se.edge_type,
            "edge_label": se.edge_label,
            "condition_value": se.condition_value or "",
        })

    # Apply patches
    for patch in parsed.get("patches", []):
        if not isinstance(patch, dict):
            raise ValueError("Each patch must be a mapping")
        action = patch.get("action")
        if not action:
            raise ValueError("Patch missing `action` field")

        if action == "update_prompt":
            _patch_update_prompt(node_dicts, patch)
        elif action == "add_step":
            _patch_add_step(node_dicts, edge_dicts, patch)
        elif action == "remove_step":
            _patch_remove_step(node_dicts, edge_dicts, patch)
        elif action == "add_tool":
            _patch_add_tool(node_dicts, edge_dicts, patch)
        elif action == "remove_tool":
            _patch_remove_tool(node_dicts, edge_dicts, patch)
        elif action == "update_config":
            _patch_update_config(node_dicts, patch)
        else:
            raise ValueError(f"Unknown patch action: '{action}'")

    name = parsed.get("name", f"{source.name} (fork)")
    return _persist_workflow(
        name=name,
        description=parsed.get("description", source.description),
        tags=parsed.get("tags", source.tags or []),
        owner_id=owner_id,
        nodes=node_dicts,
        edges=edge_dicts,
        db=db,
        forked_from_id=source.id,
    )


# ── Patch helpers ────────────────────────────────────────────────────────────


def _find_node(node_dicts: list[dict], step_id: str) -> dict | None:
    for nd in node_dicts:
        if nd["node_id"] == step_id:
            return nd
    return None


def _patch_update_prompt(node_dicts: list[dict], patch: dict) -> None:
    step_id = patch.get("step_id")
    if not step_id:
        raise ValueError("update_prompt patch requires `step_id`")
    nd = _find_node(node_dicts, step_id)
    if not nd:
        raise ValueError(f"Step '{step_id}' not found for update_prompt")
    config = nd.get("config", {})
    if "prompt" in patch:
        config["system_prompt"] = patch["prompt"]
    snippet = patch.get("snippet") or patch.get("code")
    if snippet:
        extra = config.get("extra_config", {})
        if not isinstance(extra, dict):
            extra = {}
        extra["code"] = _strip_markdown_fences(snippet)
        config["extra_config"] = extra
    nd["config"] = config


def _patch_add_step(
    node_dicts: list[dict], edge_dicts: list[dict], patch: dict
) -> None:
    after = patch.get("after")
    step = patch.get("step")
    if not step or not isinstance(step, dict):
        raise ValueError("add_step patch requires a `step` mapping")

    step_type = step.get("type")
    if not step_type or step_type not in STEP_TYPE_MAP:
        raise ValueError(f"Invalid step type in add_step: '{step_type}'")

    comp_type = STEP_TYPE_MAP[step_type]
    step_id = step.get("id", f"{comp_type}_added")

    config: dict[str, Any] = {}
    if step_type == "code":
        config["extra_config"] = {
            "code": _strip_markdown_fences(step.get("snippet") or step.get("code", "")),
            "language": step.get("language", "python"),
        }
    elif step_type == "agent":
        config["system_prompt"] = step.get("prompt") or step.get("system_prompt", "")
    elif step_type == "http":
        config["extra_config"] = {
            "url": step.get("url", ""),
            "method": step.get("method", "GET"),
        }

    new_node = {
        "node_id": step_id,
        "component_type": comp_type,
        "is_entry_point": False,
        "position_x": 400,
        "position_y": 200,
        "config": config,
    }
    node_dicts.append(new_node)

    # Reconnect edges: after → X becomes after → new → X
    if after:
        targets = [
            e for e in edge_dicts
            if e["source_node_id"] == after and e["edge_label"] == ""
        ]
        for e in targets:
            old_target = e["target_node_id"]
            e["target_node_id"] = step_id
            edge_dicts.append({
                "source_node_id": step_id,
                "target_node_id": old_target,
                "edge_type": "direct",
                "edge_label": "",
            })
        if not targets:
            # No outgoing edge found — just add edge from after to new step
            edge_dicts.append({
                "source_node_id": after,
                "target_node_id": step_id,
                "edge_type": "direct",
                "edge_label": "",
            })


def _patch_remove_step(
    node_dicts: list[dict], edge_dicts: list[dict], patch: dict
) -> None:
    step_id = patch.get("step_id")
    if not step_id:
        raise ValueError("remove_step patch requires `step_id`")

    nd = _find_node(node_dicts, step_id)
    if not nd:
        raise ValueError(f"Step '{step_id}' not found for remove_step")

    # Find incoming and outgoing non-subcomponent edges
    incoming = [e for e in edge_dicts if e["target_node_id"] == step_id and e["edge_label"] == ""]
    outgoing = [e for e in edge_dicts if e["source_node_id"] == step_id and e["edge_label"] == ""]

    # Reconnect: each incoming source → each outgoing target
    for inc in incoming:
        for out in outgoing:
            edge_dicts.append({
                "source_node_id": inc["source_node_id"],
                "target_node_id": out["target_node_id"],
                "edge_type": "direct",
                "edge_label": "",
            })

    # Remove all edges involving this node
    edge_dicts[:] = [
        e for e in edge_dicts
        if e["source_node_id"] != step_id and e["target_node_id"] != step_id
    ]
    # Remove the node
    node_dicts[:] = [n for n in node_dicts if n["node_id"] != step_id]


def _patch_add_tool(
    node_dicts: list[dict], edge_dicts: list[dict], patch: dict
) -> None:
    step_id = patch.get("step_id")
    tool_spec = patch.get("tool")
    if not step_id or not tool_spec:
        raise ValueError("add_tool patch requires `step_id` and `tool`")

    tool_type = tool_spec if isinstance(tool_spec, str) else tool_spec.get("type", "")
    tool_component = TOOL_TYPE_MAP.get(tool_type)
    if not tool_component:
        raise ValueError(f"Unknown tool type '{tool_type}'")

    tool_node_id = f"{tool_component}_{step_id}_patched"
    tool_config: dict[str, Any] = {}
    if isinstance(tool_spec, dict):
        tool_extra = {k: v for k, v in tool_spec.items() if k != "type"}
        if tool_extra:
            tool_config["extra_config"] = tool_extra

    node_dicts.append({
        "node_id": tool_node_id,
        "component_type": tool_component,
        "is_entry_point": False,
        "position_x": 400,
        "position_y": 400,
        "config": tool_config,
    })
    edge_dicts.append({
        "source_node_id": tool_node_id,
        "target_node_id": step_id,
        "edge_type": "direct",
        "edge_label": "tool",
    })


def _patch_remove_tool(
    node_dicts: list[dict], edge_dicts: list[dict], patch: dict
) -> None:
    tool_node_id = patch.get("tool_node_id")
    if not tool_node_id:
        raise ValueError("remove_tool patch requires `tool_node_id`")

    edge_dicts[:] = [
        e for e in edge_dicts
        if e["source_node_id"] != tool_node_id and e["target_node_id"] != tool_node_id
    ]
    node_dicts[:] = [n for n in node_dicts if n["node_id"] != tool_node_id]


def _patch_update_config(node_dicts: list[dict], patch: dict) -> None:
    step_id = patch.get("step_id")
    updates = patch.get("config")
    if not step_id or not updates:
        raise ValueError("update_config patch requires `step_id` and `config`")

    nd = _find_node(node_dicts, step_id)
    if not nd:
        raise ValueError(f"Step '{step_id}' not found for update_config")

    config = nd.get("config", {})
    extra = config.get("extra_config", {})
    extra.update(updates)
    config["extra_config"] = extra
    nd["config"] = config


# ── Utilities ────────────────────────────────────────────────────────────────


def _strip_markdown_fences(code: str) -> str:
    """Strip markdown code fences that LLMs sometimes wrap around code snippets."""
    if not code:
        return code
    stripped = code.strip()
    if stripped.startswith("```"):
        # Remove opening fence (with optional language tag)
        stripped = re.sub(r"^```\w*\n?", "", stripped, count=1)
        # Remove closing fence
        stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def _unique_slug(name: str, db: Session) -> str:
    """Generate a unique slug from name, appending -2, -3 etc. if needed."""
    base = _slugify(name)
    if not base:
        base = "workflow"
    slug = base
    counter = 1
    while db.query(Workflow).filter_by(slug=slug).first() is not None:
        counter += 1
        slug = f"{base}-{counter}"
    return slug
