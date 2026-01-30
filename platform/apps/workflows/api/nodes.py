from django.shortcuts import get_object_or_404
from ninja import Router

from apps.workflows.models import ComponentConfig, WorkflowEdge, WorkflowNode

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
    cc = ComponentConfig.objects.create(
        component_type=data["component_type"],
        system_prompt=config_data.get("system_prompt", ""),
        extra_config=config_data.get("extra_config", {}),
        llm_model_id=config_data.get("llm_model_id"),
    )
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
        for k, v in config_data.items():
            if k == "llm_model_id":
                cc.llm_model_id = v
            else:
                setattr(cc, k, v)
        cc.save()
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
    node.component_config.delete()
    node.delete()
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
