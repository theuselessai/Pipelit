from django.shortcuts import get_object_or_404
from ninja import Router

from apps.workflows.models import WorkflowTrigger

from .schemas import TriggerIn, TriggerOut, TriggerUpdate
from .workflows import _get_workflow

router = Router(tags=["triggers"])


@router.get("/{slug}/triggers/", response=list[TriggerOut])
def list_triggers(request, slug: str):
    wf = _get_workflow(slug, request.auth)
    return wf.triggers.all()


@router.post("/{slug}/triggers/", response={201: TriggerOut})
def create_trigger(request, slug: str, payload: TriggerIn):
    wf = _get_workflow(slug, request.auth)
    trigger = WorkflowTrigger.objects.create(workflow=wf, **payload.dict())
    return 201, trigger


@router.patch("/{slug}/triggers/{trigger_id}/", response=TriggerOut)
def update_trigger(request, slug: str, trigger_id: int, payload: TriggerUpdate):
    wf = _get_workflow(slug, request.auth)
    trigger = get_object_or_404(wf.triggers, id=trigger_id)
    for attr, value in payload.dict(exclude_unset=True).items():
        setattr(trigger, attr, value)
    trigger.save()
    return trigger


@router.delete("/{slug}/triggers/{trigger_id}/", response={204: None})
def delete_trigger(request, slug: str, trigger_id: int):
    wf = _get_workflow(slug, request.auth)
    trigger = get_object_or_404(wf.triggers, id=trigger_id)
    trigger.delete()
    return 204, None
