import httpx
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.credentials.models import (
    BaseCredentials,
    GitCredential,
    LLMProviderCredentials,
    TelegramCredential,
    ToolCredential,
)

from .schemas import (
    CredentialIn,
    CredentialModelOut,
    CredentialOut,
    CredentialTestOut,
    CredentialUpdate,
)

router = Router(tags=["credentials"])

ANTHROPIC_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-opus-4-0-20250514",
    "claude-haiku-3-5-20241022",
    "claude-3-5-sonnet-20241022",
]


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
            "provider_type": llm.provider_type,
            "api_key": _mask(llm.api_key),
            "base_url": llm.base_url,
            "organization_id": llm.organization_id,
            "custom_headers": llm.custom_headers,
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
            provider_type=detail.get("provider_type", "openai_compatible"),
            api_key=detail.get("api_key", ""),
            base_url=detail.get("base_url", ""),
            organization_id=detail.get("organization_id", ""),
            custom_headers=detail.get("custom_headers", {}),
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
            for field in ("provider_type", "api_key", "base_url", "organization_id", "custom_headers"):
                if field in detail:
                    setattr(llm, field, detail[field])
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


# -- Test & Models endpoints ---------------------------------------------------


@router.post("/{credential_id}/test/", response=CredentialTestOut)
def test_credential(request, credential_id: int):
    cred = get_object_or_404(
        BaseCredentials.objects.select_related("llm_credential"),
        id=credential_id,
        credential_type="llm",
    )
    llm = cred.llm_credential
    try:
        if llm.provider_type == "anthropic":
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": llm.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-3-5-20241022",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                timeout=15,
            )
            if resp.status_code >= 400:
                return {"ok": False, "error": resp.text[:500]}
        else:
            base_url = llm.base_url.rstrip("/") if llm.base_url else "https://api.openai.com/v1"
            resp = httpx.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {llm.api_key}"},
                timeout=15,
            )
            if resp.status_code >= 400:
                return {"ok": False, "error": resp.text[:500]}
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


@router.get("/{credential_id}/models/", response=list[CredentialModelOut])
def list_credential_models(request, credential_id: int):
    cred = get_object_or_404(
        BaseCredentials.objects.select_related("llm_credential"),
        id=credential_id,
        credential_type="llm",
    )
    llm = cred.llm_credential

    if llm.provider_type == "anthropic":
        return [{"id": m, "name": m} for m in ANTHROPIC_MODELS]

    base_url = llm.base_url.rstrip("/") if llm.base_url else "https://api.openai.com/v1"
    try:
        resp = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {llm.api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        models = sorted(data, key=lambda m: m.get("id", ""))
        return [{"id": m["id"], "name": m["id"]} for m in models]
    except Exception:
        return []
