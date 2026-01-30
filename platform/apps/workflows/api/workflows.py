from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.workflows.models import Workflow

from .schemas import WorkflowDetailOut, WorkflowIn, WorkflowOut, WorkflowUpdate

router = Router(tags=["workflows"])


def _get_workflow(slug: str, profile):
    return get_object_or_404(
        Workflow.objects.filter(
            Q(owner=profile) | Q(collaborators__user_profile=profile)
        ).distinct(),
        slug=slug,
    )


@router.get("/", response=list[WorkflowOut])
def list_workflows(request):
    profile = request.auth
    return Workflow.objects.filter(
        Q(owner=profile) | Q(collaborators__user_profile=profile)
    ).distinct()


@router.post("/", response={201: WorkflowOut})
def create_workflow(request, payload: WorkflowIn):
    profile = request.auth
    data = payload.dict()
    data["owner"] = profile
    wf = Workflow.objects.create(**data)
    return 201, wf


@router.get("/{slug}/", response=WorkflowDetailOut)
def get_workflow(request, slug: str):
    return _get_workflow(slug, request.auth)


@router.patch("/{slug}/", response=WorkflowOut)
def update_workflow(request, slug: str, payload: WorkflowUpdate):
    wf = _get_workflow(slug, request.auth)
    for attr, value in payload.dict(exclude_unset=True).items():
        setattr(wf, attr, value)
    wf.save()
    return wf


@router.delete("/{slug}/", response={204: None})
def delete_workflow(request, slug: str):
    wf = _get_workflow(slug, request.auth)
    wf.soft_delete()
    return 204, None
