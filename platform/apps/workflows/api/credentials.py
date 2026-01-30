from django.shortcuts import get_object_or_404
from ninja import Router

from apps.credentials.models import (
    BaseCredentials,
    GitCredential,
    LLMModel,
    LLMProvider,
    LLMProviderCredentials,
    TelegramCredential,
    ToolCredential,
)

from .schemas import (
    CredentialIn,
    CredentialOut,
    CredentialUpdate,
    LLMModelOut,
    LLMProviderOut,
)

router = Router(tags=["credentials"])


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "****"
    return value[:4] + "****" + value[-4:]


def _serialize_credential(cred: BaseCredentials) -> dict:
    data = {
        "id": cred.id,
        "name": cred.name,
        "credential_type": cred.credential_type,
        "created_at": cred.created_at,
        "updated_at": cred.updated_at,
        "detail": {},
    }
    if cred.credential_type == "llm" and hasattr(cred, "llm_credential"):
        llm = cred.llm_credential
        data["detail"] = {
            "provider_id": llm.provider_id,
            "api_key": _mask(llm.api_key),
            "base_url": llm.base_url,
        }
    elif cred.credential_type == "telegram" and hasattr(cred, "telegram_credential"):
        tg = cred.telegram_credential
        data["detail"] = {
            "bot_token": _mask(tg.bot_token),
            "allowed_user_ids": tg.allowed_user_ids,
        }
    elif cred.credential_type == "git" and hasattr(cred, "git_credential"):
        git = cred.git_credential
        data["detail"] = {
            "provider": git.provider,
            "credential_type": git.credential_type,
            "username": git.username,
            "ssh_private_key": "****" if git.ssh_private_key else "",
            "access_token": _mask(git.access_token) if git.access_token else "",
        }
    elif cred.credential_type == "tool" and hasattr(cred, "tool_credential"):
        tool = cred.tool_credential
        data["detail"] = {
            "tool_type": tool.tool_type,
            "config": tool.config,
        }
    return data


@router.get("/", response=list[CredentialOut])
def list_credentials(request):
    creds = BaseCredentials.objects.select_related(
        "llm_credential", "telegram_credential", "git_credential", "tool_credential",
    ).all()
    return [_serialize_credential(c) for c in creds]


@router.post("/", response={201: CredentialOut})
def create_credential(request, payload: CredentialIn):
    base = BaseCredentials.objects.create(
        user_profile=request.auth,
        name=payload.name,
        credential_type=payload.credential_type,
    )
    detail = payload.detail or {}
    if payload.credential_type == "llm":
        LLMProviderCredentials.objects.create(
            base_credentials=base,
            provider_id=detail.get("provider_id"),
            api_key=detail.get("api_key", ""),
            base_url=detail.get("base_url", ""),
        )
    elif payload.credential_type == "telegram":
        TelegramCredential.objects.create(
            base_credentials=base,
            bot_token=detail.get("bot_token", ""),
            allowed_user_ids=detail.get("allowed_user_ids", ""),
        )
    elif payload.credential_type == "git":
        GitCredential.objects.create(
            base_credentials=base,
            provider=detail.get("provider", "github"),
            credential_type=detail.get("credential_type", "token"),
            ssh_private_key=detail.get("ssh_private_key", ""),
            access_token=detail.get("access_token", ""),
            username=detail.get("username", ""),
            webhook_secret=detail.get("webhook_secret", ""),
        )
    elif payload.credential_type == "tool":
        ToolCredential.objects.create(
            base_credentials=base,
            tool_type=detail.get("tool_type", "api"),
            config=detail.get("config", {}),
        )
    return 201, _serialize_credential(
        BaseCredentials.objects.select_related(
            "llm_credential", "telegram_credential", "git_credential", "tool_credential",
        ).get(id=base.id)
    )


@router.get("/{credential_id}/", response=CredentialOut)
def get_credential(request, credential_id: int):
    cred = get_object_or_404(
        BaseCredentials.objects.select_related(
            "llm_credential", "telegram_credential", "git_credential", "tool_credential",
        ),
        id=credential_id,
    )
    return _serialize_credential(cred)


@router.patch("/{credential_id}/", response=CredentialOut)
def update_credential(request, credential_id: int, payload: CredentialUpdate):
    cred = get_object_or_404(
        BaseCredentials.objects.select_related(
            "llm_credential", "telegram_credential", "git_credential", "tool_credential",
        ),
        id=credential_id,
    )
    if payload.name is not None:
        cred.name = payload.name
        cred.save()

    detail = payload.detail
    if detail:
        if cred.credential_type == "llm" and hasattr(cred, "llm_credential"):
            llm = cred.llm_credential
            if "provider_id" in detail:
                llm.provider_id = detail["provider_id"]
            if "api_key" in detail:
                llm.api_key = detail["api_key"]
            if "base_url" in detail:
                llm.base_url = detail["base_url"]
            llm.save()
        elif cred.credential_type == "telegram" and hasattr(cred, "telegram_credential"):
            tg = cred.telegram_credential
            if "bot_token" in detail:
                tg.bot_token = detail["bot_token"]
            if "allowed_user_ids" in detail:
                tg.allowed_user_ids = detail["allowed_user_ids"]
            tg.save()
        elif cred.credential_type == "git" and hasattr(cred, "git_credential"):
            git = cred.git_credential
            for field in ("provider", "credential_type", "ssh_private_key", "access_token", "username", "webhook_secret"):
                if field in detail:
                    setattr(git, field, detail[field])
            git.save()
        elif cred.credential_type == "tool" and hasattr(cred, "tool_credential"):
            tool = cred.tool_credential
            if "tool_type" in detail:
                tool.tool_type = detail["tool_type"]
            if "config" in detail:
                tool.config = detail["config"]
            tool.save()

    cred.refresh_from_db()
    return _serialize_credential(
        BaseCredentials.objects.select_related(
            "llm_credential", "telegram_credential", "git_credential", "tool_credential",
        ).get(id=cred.id)
    )


@router.delete("/{credential_id}/", response={204: None})
def delete_credential(request, credential_id: int):
    cred = get_object_or_404(BaseCredentials, id=credential_id)
    cred.delete()
    return 204, None


# ── LLM Providers & Models ──────────────────────────────────────────────────


@router.get("/llm-providers/", response=list[LLMProviderOut])
def list_llm_providers(request):
    return LLMProvider.objects.all()


@router.get("/llm-models/", response=list[LLMModelOut])
def list_llm_models(request, provider_id: int | None = None):
    qs = LLMModel.objects.select_related("provider").all()
    if provider_id is not None:
        qs = qs.filter(provider_id=provider_id)
    return qs
