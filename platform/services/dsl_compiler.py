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
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

import yaml
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

        nodes, edges = _build_graph(parsed, model_info, db)

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

    # Validate trigger
    trigger = parsed.get("trigger", "manual")
    if isinstance(trigger, str) and trigger not in TRIGGER_TYPE_MAP:
        raise ValueError(
            f"Unknown trigger type '{trigger}'. "
            f"Valid: {', '.join(TRIGGER_TYPE_MAP)}"
        )

    # Validate each step
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

    # Capability-based resolution
    if "capability" in model_spec:
        capability = model_spec["capability"]
        creds = (
            db.query(LLMProviderCredential)
            .join(BaseCredential, LLMProviderCredential.base_credentials_id == BaseCredential.id)
            .all()
        )
        for cred in creds:
            # Simple substring match on model name for v1
            if capability.lower() in (cred.provider_type or "").lower():
                return (cred.base_credentials_id, capability, model_spec.get("temperature"))
        # If no match on provider_type, return first available credential with the
        # capability as the model_name (the user knows which model they want)
        if creds:
            return (creds[0].base_credentials_id, capability, model_spec.get("temperature"))
        raise ValueError(f"No LLM credential found for capability '{capability}'")

    # Direct credential_id
    if "credential_id" in model_spec:
        return (
            model_spec["credential_id"],
            model_spec.get("model_name", ""),
            model_spec.get("temperature"),
        )

    return (None, None, None)


# ── Stage 3: Build graph ─────────────────────────────────────────────────────


def _build_graph(
    parsed: dict,
    model_info: tuple[int | None, str | None, float | None],
    db: Session,
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

    # ── Step nodes ───────────────────────────────────────────────────────
    for i, step in enumerate(parsed["steps"]):
        step_type = step["type"]
        step_component = STEP_TYPE_MAP[step_type]
        step_id = step.get("id", f"{step_component}_{i + 1}")
        is_first_exec = i == 0

        config: dict[str, Any] = {}

        if step_type == "code":
            config["code_snippet"] = step.get("snippet", "")
            config["code_language"] = step.get("language", "python")

        elif step_type == "agent":
            config["system_prompt"] = step.get("prompt", "")
            # Model: step-level override or workflow-level default
            step_model = step.get("model", {})
            if step_model:
                s_cred, s_model, s_temp = _resolve_model(step_model, None, db)
                config["llm_credential_id"] = s_cred
                config["model_name"] = s_model
                config["temperature"] = s_temp
            elif cred_id is not None:
                config["llm_credential_id"] = cred_id
                config["model_name"] = model_name
                config["temperature"] = temperature
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

        node_dict = {
            "node_id": step_id,
            "component_type": step_component,
            "is_entry_point": is_first_exec,
            "position_x": x_offset,
            "position_y": 200,
            "config": config,
        }
        nodes.append(node_dict)

        # Linear edge: prev → current
        edges.append({
            "source_node_id": prev_node_id,
            "target_node_id": step_id,
            "edge_type": "direct",
            "edge_label": "",
        })

        # ── Agent sub-components ─────────────────────────────────────────
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

    for sn in source_nodes:
        cfg = sn.component_config
        config_kwargs: dict[str, Any] = {"component_type": cfg.component_type}
        # Copy config fields
        for field in (
            "extra_config", "llm_credential_id", "model_name", "temperature",
            "max_tokens", "frequency_penalty", "presence_penalty", "top_p",
            "timeout", "max_retries", "response_format", "system_prompt",
            "code_language", "code_snippet", "credential_id", "is_active",
            "priority", "trigger_config",
        ):
            val = getattr(cfg, field, None)
            if val is not None:
                config_kwargs[field] = copy.deepcopy(val) if isinstance(val, (dict, list)) else val

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
    if "snippet" in patch:
        config["code_snippet"] = patch["snippet"]
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
        config["code_snippet"] = step.get("snippet", "")
        config["code_language"] = step.get("language", "python")
    elif step_type == "agent":
        config["system_prompt"] = step.get("prompt", "")
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
