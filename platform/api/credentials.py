"""Credential CRUD + test + models endpoints."""

from __future__ import annotations

import logging

import httpx

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.credential import (
    BaseCredential,
    GatewayCredential,
    GitCredential,
    LLMProviderCredential,
    ToolCredential,
)
from models.user import UserProfile
from schemas.credential import (
    CredentialIn,
    CredentialModelOut,
    CredentialOut,
    CredentialTestOut,
    CredentialUpdate,
)
from services.gateway_client import GatewayAPIError, GatewayUnavailableError, get_gateway_client

logger = logging.getLogger(__name__)

router = APIRouter()

ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-4-20250514",
    "claude-opus-4-0-20250514",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
]

MINIMAX_MODELS = [
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
    "MiniMax-M2.1",
    "MiniMax-M2.1-highspeed",
    "MiniMax-M2",
]


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "****"
    return value[:4] + "****" + value[-4:]


def _serialize_credential(cred: BaseCredential, db: Session) -> dict:
    data = {
        "id": cred.id,
        "name": cred.name,
        "credential_type": cred.credential_type,
        "created_at": cred.created_at,
        "updated_at": cred.updated_at,
        "detail": {},
    }
    if cred.credential_type == "llm" and cred.llm_credential:
        llm = cred.llm_credential
        data["detail"] = {
            "provider_type": llm.provider_type,
            "api_key": _mask(llm.api_key),
            "base_url": llm.base_url,
            "organization_id": llm.organization_id,
            "custom_headers": llm.custom_headers,
        }
    elif cred.credential_type == "gateway" and cred.gateway_credential:
        gw = cred.gateway_credential
        data["detail"] = {
            "gateway_credential_id": gw.gateway_credential_id,
            "adapter_type": gw.adapter_type,
        }
    elif cred.credential_type == "git" and cred.git_credential:
        git = cred.git_credential
        data["detail"] = {
            "provider": git.provider,
            "credential_type": git.credential_type,
            "username": git.username,
            "ssh_private_key": "****" if git.ssh_private_key else "",
            "access_token": _mask(git.access_token) if git.access_token else "",
        }
    elif cred.credential_type == "tool" and cred.tool_credential:
        tool = cred.tool_credential
        data["detail"] = {
            "tool_type": tool.tool_type,
            "config": tool.config,
            "is_preferred": tool.is_preferred,
        }
    return data


@router.get("/")
def list_credentials(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    total = db.query(BaseCredential).count()
    creds = db.query(BaseCredential).offset(offset).limit(limit).all()
    return {"items": [_serialize_credential(c, db) for c in creds], "total": total}


@router.post("/", response_model=CredentialOut, status_code=201)
def create_credential(
    payload: CredentialIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    base = BaseCredential(
        user_profile_id=profile.id,
        name=payload.name,
        credential_type=payload.credential_type,
    )
    db.add(base)
    db.flush()

    detail = payload.detail or {}
    if payload.credential_type == "llm":
        sub = LLMProviderCredential(
            base_credentials_id=base.id,
            provider_type=detail.get("provider_type", "openai_compatible"),
            api_key=detail.get("api_key", ""),
            base_url=detail.get("base_url", ""),
            organization_id=detail.get("organization_id", ""),
            custom_headers=detail.get("custom_headers", {}),
        )
        db.add(sub)
    elif payload.credential_type == "gateway":
        adapter_type = detail.get("adapter_type", "")
        token = detail.get("token", "")
        config = detail.get("config")
        # Use name as the gateway credential ID (stable, user-chosen identifier)
        gw_credential_id = payload.name
        try:
            get_gateway_client().create_credential(
                id=gw_credential_id,
                adapter=adapter_type,
                token=token,
                config=config,
            )
        except (GatewayUnavailableError, GatewayAPIError) as e:
            db.rollback()
            raise HTTPException(status_code=502, detail=str(e))
        sub = GatewayCredential(
            base_credentials_id=base.id,
            gateway_credential_id=gw_credential_id,
            adapter_type=adapter_type,
        )
        db.add(sub)
    elif payload.credential_type == "git":
        sub = GitCredential(
            base_credentials_id=base.id,
            provider=detail.get("provider", "github"),
            credential_type=detail.get("credential_type", "token"),
            ssh_private_key=detail.get("ssh_private_key", ""),
            access_token=detail.get("access_token", ""),
            username=detail.get("username", ""),
            webhook_secret=detail.get("webhook_secret", ""),
        )
        db.add(sub)
    elif payload.credential_type == "tool":
        sub = ToolCredential(
            base_credentials_id=base.id,
            tool_type=detail.get("tool_type", "api"),
            config=detail.get("config", {}),
            is_preferred=detail.get("is_preferred", False),
        )
        db.add(sub)

    db.commit()
    db.refresh(base)
    return _serialize_credential(base, db)


@router.get("/{credential_id}/", response_model=CredentialOut)
def get_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    cred = db.query(BaseCredential).filter(BaseCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found.")
    return _serialize_credential(cred, db)


@router.patch("/{credential_id}/", response_model=CredentialOut)
def update_credential(
    credential_id: int,
    payload: CredentialUpdate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    cred = db.query(BaseCredential).filter(BaseCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found.")

    if payload.name is not None:
        cred.name = payload.name

    detail = payload.detail
    if detail:
        if cred.credential_type == "llm" and cred.llm_credential:
            llm = cred.llm_credential
            for field in ("provider_type", "api_key", "base_url", "organization_id", "custom_headers"):
                if field in detail:
                    setattr(llm, field, detail[field])
        elif cred.credential_type == "gateway" and cred.gateway_credential:
            gw = cred.gateway_credential
            gw_update_kwargs: dict = {}
            if "token" in detail:
                gw_update_kwargs["token"] = detail["token"]
            if "adapter_type" in detail:
                gw.adapter_type = detail["adapter_type"]
                gw_update_kwargs["adapter"] = detail["adapter_type"]
            if gw_update_kwargs:
                try:
                    get_gateway_client().update_credential(gw.gateway_credential_id, **gw_update_kwargs)
                except (GatewayUnavailableError, GatewayAPIError) as e:
                    db.rollback()
                    raise HTTPException(status_code=502, detail=str(e))
        elif cred.credential_type == "git" and cred.git_credential:
            git = cred.git_credential
            for field in ("provider", "credential_type", "ssh_private_key", "access_token", "username", "webhook_secret"):
                if field in detail:
                    setattr(git, field, detail[field])
        elif cred.credential_type == "tool" and cred.tool_credential:
            tool = cred.tool_credential
            if "tool_type" in detail:
                tool.tool_type = detail["tool_type"]
            if "config" in detail:
                tool.config = detail["config"]
            if "is_preferred" in detail:
                tool.is_preferred = detail["is_preferred"]

    db.commit()
    db.refresh(cred)
    return _serialize_credential(cred, db)


@router.delete("/{credential_id}/", status_code=204)
def delete_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    cred = db.query(BaseCredential).filter(BaseCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found.")
    if cred.gateway_credential:
        gw_cred = cred.gateway_credential
        try:
            get_gateway_client().delete_credential(gw_cred.gateway_credential_id)
        except (GatewayUnavailableError, GatewayAPIError) as e:
            raise HTTPException(status_code=502, detail=str(e))
    db.delete(cred)
    db.commit()


class BatchDeleteCredentialsIn(BaseModel):
    ids: list[int]


@router.post("/batch-delete/", status_code=204)
def batch_delete_credentials(
    payload: BatchDeleteCredentialsIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.ids:
        return
    creds = db.query(BaseCredential).filter(BaseCredential.id.in_(payload.ids)).all()
    for cred in creds:
        if cred.gateway_credential:
            try:
                get_gateway_client().delete_credential(cred.gateway_credential.gateway_credential_id)
            except (GatewayUnavailableError, GatewayAPIError) as e:
                logger.warning("Failed to delete gateway credential %s: %s", cred.gateway_credential.gateway_credential_id, e)
        db.delete(cred)
    db.commit()


# -- Activate / Deactivate endpoints ------------------------------------------


@router.post("/{credential_id}/activate/")
def activate_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    cred = db.query(BaseCredential).filter(BaseCredential.id == credential_id).first()
    if not cred or not cred.gateway_credential:
        raise HTTPException(status_code=404, detail="Gateway credential not found.")
    try:
        result = get_gateway_client().activate_credential(cred.gateway_credential.gateway_credential_id)
        return result
    except (GatewayUnavailableError, GatewayAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{credential_id}/deactivate/")
def deactivate_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    cred = db.query(BaseCredential).filter(BaseCredential.id == credential_id).first()
    if not cred or not cred.gateway_credential:
        raise HTTPException(status_code=404, detail="Gateway credential not found.")
    try:
        result = get_gateway_client().deactivate_credential(cred.gateway_credential.gateway_credential_id)
        return result
    except (GatewayUnavailableError, GatewayAPIError) as e:
        raise HTTPException(status_code=502, detail=str(e))


# -- Test & Models endpoints ---------------------------------------------------


@router.post("/{credential_id}/test/", response_model=CredentialTestOut)
def test_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    cred = db.query(BaseCredential).filter(BaseCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found.")

    # Gateway credential: check health via gateway admin API
    if cred.credential_type == "gateway" and cred.gateway_credential:
        gw_cred = cred.gateway_credential
        try:
            health_info = get_gateway_client().check_credential_health(gw_cred.gateway_credential_id)
        except (GatewayUnavailableError, GatewayAPIError) as e:
            return {"ok": False, "error": str(e)}
        if health_info is None:
            return {"ok": False, "detail": "not found in gateway"}
        return {"ok": True, "detail": health_info}

    if not cred.llm_credential:
        raise HTTPException(status_code=404, detail="LLM credential not found.")
    llm = cred.llm_credential
    is_custom_base = llm.base_url and "anthropic.com" not in llm.base_url
    try:
        if llm.provider_type == "anthropic" and not is_custom_base:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": llm.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                timeout=15,
            )
            if resp.status_code >= 400:
                return {"ok": False, "error": resp.text[:500]}
        elif llm.provider_type == "glm":
            base = llm.base_url.rstrip("/") if llm.base_url else "https://api.z.ai/api/paas/v4"
            resp = httpx.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {llm.api_key}"},
                timeout=15,
            )
            if resp.status_code in (401, 403):
                return {"ok": False, "error": "Authentication failed - invalid API key"}
            if resp.status_code >= 400:
                return {"ok": False, "error": resp.text[:500]}
        else:
            # Test auth by listing models — no valid model name needed
            base_url = llm.base_url.rstrip("/") if llm.base_url else "https://api.openai.com/v1"
            resp = httpx.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {llm.api_key}"},
                timeout=15,
            )
            if resp.status_code in (401, 403):
                return {"ok": False, "error": "Authentication failed - invalid API key"}
            if resp.status_code >= 400:
                return {"ok": False, "error": resp.text[:500]}
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


@router.get("/{credential_id}/models/", response_model=list[CredentialModelOut])
def list_credential_models(
    credential_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    cred = (
        db.query(BaseCredential)
        .filter(BaseCredential.id == credential_id, BaseCredential.credential_type == "llm")
        .first()
    )
    if not cred or not cred.llm_credential:
        raise HTTPException(status_code=404, detail="LLM credential not found.")
    llm = cred.llm_credential

    is_custom_base = llm.base_url and "anthropic.com" not in llm.base_url
    if llm.provider_type == "anthropic" and not is_custom_base:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=llm.api_key)
            page = client.models.list(limit=100)
            models = sorted(page.data, key=lambda m: m.id)
            return [{"id": m.id, "name": m.id} for m in models]
        except Exception:
            logger.debug("Anthropic models API failed, using fallback list", exc_info=True)
            return [{"id": m, "name": m} for m in ANTHROPIC_MODELS]

    if llm.provider_type == "glm":
        base_url = llm.base_url.rstrip("/") if llm.base_url else "https://api.z.ai/api/paas/v4"
    else:
        base_url = llm.base_url.rstrip("/") if llm.base_url else "https://api.openai.com/v1"
    try:
        resp = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {llm.api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict):
            data = body.get("data", [])
        elif isinstance(body, list):
            data = body
        else:
            logger.warning("Unexpected /models response format: %s", type(body).__name__)
            data = []
        models = sorted(data, key=lambda m: m.get("id", "") if isinstance(m, dict) else "")
        return [{"id": m["id"], "name": m["id"]} for m in models if isinstance(m, dict) and "id" in m]
    except Exception:
        if "minimax" in base_url.lower():
            return [{"id": m, "name": m} for m in MINIMAX_MODELS]
        return []
