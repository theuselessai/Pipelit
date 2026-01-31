from django.shortcuts import get_object_or_404
from ninja import Router

from apps.workflows.models import WorkflowEdge, WorkflowNode
from apps.workflows.models.node import (
    COMPONENT_TYPE_TO_CONFIG,
    BaseComponentConfig,
    ModelComponentConfig,
    TriggerComponentConfig,
)

from .schemas import EdgeIn, EdgeOut, EdgeUpdate, NodeIn, NodeOut, NodeUpdate
from .workflows import _get_workflow

router = Router(tags=["nodes", "edges"])


# ── Nodes ─────────────────────────────────────────────────────────────────────


@router.get("/{slug}/nodes/", response=list[NodeOut])
def list_nodes(request, slug: str):
    wf = _get_workflow(slug, request.auth)
    return wf.nodes.all()


@router.post("/{slug}/nodes/", response={201: NodeOut})
def create_node(request, slug: str, payload: NodeIn):
    wf = _get_workflow(slug, request.auth)
    data = payload.dict()
    config_data = data.pop("config")
    component_type = data["component_type"]

    # Create the right config subclass
    ConfigClass = COMPONENT_TYPE_TO_CONFIG.get(component_type, BaseComponentConfig)

    kwargs = {
        "component_type": component_type,
        "extra_config": config_data.get("extra_config", {}),
    }

    # Add fields specific to the config subclass
    if hasattr(ConfigClass, "system_prompt"):
        kwargs["system_prompt"] = config_data.get("system_prompt", "")
    if issubclass(ConfigClass, ModelComponentConfig):
        kwargs["llm_credential_id"] = config_data.get("llm_credential_id")
        kwargs["model_name"] = config_data.get("model_name", "")
        for param in ("temperature", "max_tokens", "frequency_penalty", "presence_penalty", "top_p", "timeout", "max_retries", "response_format"):
            if config_data.get(param) is not None:
                kwargs[param] = config_data[param]
    elif issubclass(ConfigClass, TriggerComponentConfig):
        kwargs["credential_id"] = config_data.get("credential_id")
        kwargs["is_active"] = config_data.get("is_active", True)
        kwargs["priority"] = config_data.get("priority", 0)
        kwargs["trigger_config"] = config_data.get("trigger_config", {})

    cc = ConfigClass.objects.create(**kwargs)
    data["workflow"] = wf
    data["component_config"] = cc
    node = WorkflowNode.objects.create(**data)
    return 201, node


@router.patch("/{slug}/nodes/{node_id}/", response=NodeOut)
def update_node(request, slug: str, node_id: str, payload: NodeUpdate):
    wf = _get_workflow(slug, request.auth)
    node = get_object_or_404(wf.nodes, node_id=node_id)
    data = payload.dict(exclude_unset=True)
    config_data = data.pop("config", None)
    if config_data:
        cc = node.component_config
        concrete = cc.concrete
        model_fields = ("llm_credential_id", "model_name", "temperature", "max_tokens", "frequency_penalty", "presence_penalty", "top_p", "timeout", "max_retries", "response_format")
        trigger_fields = ("credential_id", "is_active", "priority", "trigger_config")
        for k, v in config_data.items():
            if k in model_fields:
                if isinstance(concrete, ModelComponentConfig):
                    setattr(concrete, k, v)
            elif k in trigger_fields:
                if isinstance(concrete, TriggerComponentConfig):
                    setattr(concrete, k, v)
            elif k == "system_prompt":
                if hasattr(concrete, "system_prompt"):
                    concrete.system_prompt = v
            elif k == "extra_config":
                cc.extra_config = v
            else:
                setattr(cc, k, v)
        cc.save()
        if concrete is not cc:
            concrete.save()
    for attr, value in data.items():
        setattr(node, attr, value)
    node.save()
    return node


@router.delete("/{slug}/nodes/{node_id}/", response={204: None})
def delete_node(request, slug: str, node_id: str):
    wf = _get_workflow(slug, request.auth)
    node = get_object_or_404(wf.nodes, node_id=node_id)
    # Delete edges referencing this node
    wf.edges.filter(source_node_id=node_id).delete()
    wf.edges.filter(target_node_id=node_id).delete()
    cc = node.component_config
    node.delete()
    # Deleting the base config cascades to the child table
    cc.delete()
    return 204, None


# ── Edges ─────────────────────────────────────────────────────────────────────


@router.get("/{slug}/edges/", response=list[EdgeOut])
def list_edges(request, slug: str):
    wf = _get_workflow(slug, request.auth)
    return wf.edges.all()


@router.post("/{slug}/edges/", response={201: EdgeOut})
def create_edge(request, slug: str, payload: EdgeIn):
    wf = _get_workflow(slug, request.auth)
    edge = WorkflowEdge.objects.create(workflow=wf, **payload.dict())
    return 201, edge


@router.patch("/{slug}/edges/{edge_id}/", response=EdgeOut)
def update_edge(request, slug: str, edge_id: int, payload: EdgeUpdate):
    wf = _get_workflow(slug, request.auth)
    edge = get_object_or_404(wf.edges, id=edge_id)
    for attr, value in payload.dict(exclude_unset=True).items():
        setattr(edge, attr, value)
    edge.save()
    return edge


@router.delete("/{slug}/edges/{edge_id}/", response={204: None})
def delete_edge(request, slug: str, edge_id: int):
    wf = _get_workflow(slug, request.auth)
    edge = get_object_or_404(wf.edges, id=edge_id)
    edge.delete()
    return 204, None
