"""Credential CRUD + test + models endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from config import settings
from database import get_db
from models.user import UserRole
from models.credential import (
    BaseCredential,
    GatewayCredential,
    GitCredential,
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

# LLM credentials are no longer created, updated, or stored by pipelit.
# Raw provider API keys live exclusively in agentgateway (managed via the
# admin providers API / agentgateway config.d). Any attempt to manage an
# ``llm``-typed credential through this router is rejected with 410 Gone.
LLM_CREDENTIALS_GONE_DETAIL = (
    "LLM credentials are now managed by agentgateway. Creating, updating, "
    "or testing 'llm' credentials in pipelit has been removed — configure "
    "providers and API keys through the agentgateway admin providers API."
)


def _reject_llm_credential() -> None:
    raise HTTPException(status_code=410, detail=LLM_CREDENTIALS_GONE_DETAIL)


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
        "agentgateway_backend": None,
    }
    # NOTE: no ``llm`` branch — LLM keys live in agentgateway, and pipelit
    # never serializes LLM provider secrets. Leftover llm-typed rows (kept
    # for legacy llm_credential_id routing) serialize with an empty detail.
    if cred.credential_type == "gateway" and cred.gateway_credential:
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
    query = db.query(BaseCredential)
    if profile.role != UserRole.ADMIN:
        query = query.filter(BaseCredential.user_profile_id == profile.id)
    total = query.count()
    creds = query.offset(offset).limit(limit).all()
    return {"items": [_serialize_credential(c, db) for c in creds], "total": total}


@router.post("/", response_model=CredentialOut, status_code=201)
def create_credential(
    payload: CredentialIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if payload.credential_type == "llm":
        _reject_llm_credential()

    base = BaseCredential(
        user_profile_id=profile.id,
        name=payload.name,
        credential_type=payload.credential_type,
    )
    db.add(base)
    db.flush()

    detail = payload.detail or {}
    if payload.credential_type == "gateway":
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

    try:
        db.commit()
    except Exception:
        db.rollback()
        # Clean up orphaned gateway credential if DB commit fails
        if payload.credential_type == "gateway":
            try:
                get_gateway_client().delete_credential(payload.name)
            except Exception:
                logger.warning("Failed to clean up gateway credential %s after DB error", payload.name)
        raise
    db.refresh(base)

    return _serialize_credential(base, db)


@router.get("/{credential_id}/", response_model=CredentialOut)
def get_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    query = db.query(BaseCredential).filter(BaseCredential.id == credential_id)
    if profile.role != UserRole.ADMIN:
        query = query.filter(BaseCredential.user_profile_id == profile.id)
    cred = query.first()
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
    query = db.query(BaseCredential).filter(BaseCredential.id == credential_id)
    if profile.role != UserRole.ADMIN:
        query = query.filter(BaseCredential.user_profile_id == profile.id)
    cred = query.first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found.")

    if cred.credential_type == "llm":
        _reject_llm_credential()

    if payload.name is not None:
        cred.name = payload.name

    detail = payload.detail
    if detail:
        if cred.credential_type == "gateway" and cred.gateway_credential:
            gw = cred.gateway_credential
            gw_update_kwargs: dict = {}
            new_adapter_type = None
            if "token" in detail:
                gw_update_kwargs["token"] = detail["token"]
            if "adapter_type" in detail:
                new_adapter_type = detail["adapter_type"]
                gw_update_kwargs["adapter"] = detail["adapter_type"]
            if gw_update_kwargs:
                try:
                    get_gateway_client().update_credential(gw.gateway_credential_id, **gw_update_kwargs)
                except (GatewayUnavailableError, GatewayAPIError) as e:
                    db.rollback()
                    raise HTTPException(status_code=502, detail=str(e))
                if new_adapter_type is not None:
                    gw.adapter_type = new_adapter_type
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
    query = db.query(BaseCredential).filter(BaseCredential.id == credential_id)
    if profile.role != UserRole.ADMIN:
        query = query.filter(BaseCredential.user_profile_id == profile.id)
    cred = query.first()
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
    query = db.query(BaseCredential).filter(BaseCredential.id.in_(payload.ids))
    if profile.role != UserRole.ADMIN:
        query = query.filter(BaseCredential.user_profile_id == profile.id)
    creds = query.all()
    failed_gw: list[str] = []
    for cred in creds:
        if cred.gateway_credential:
            try:
                get_gateway_client().delete_credential(cred.gateway_credential.gateway_credential_id)
            except (GatewayUnavailableError, GatewayAPIError) as e:
                failed_gw.append(cred.gateway_credential.gateway_credential_id)
                logger.warning("Failed to delete gateway credential %s: %s", cred.gateway_credential.gateway_credential_id, e)
    if failed_gw:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to delete gateway credentials: {failed_gw}. Database unchanged.",
        )

    for cred in creds:
        db.delete(cred)
    db.commit()


# -- Activate / Deactivate endpoints ------------------------------------------


@router.post("/{credential_id}/activate/")
def activate_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    query = db.query(BaseCredential).filter(BaseCredential.id == credential_id)
    if profile.role != UserRole.ADMIN:
        query = query.filter(BaseCredential.user_profile_id == profile.id)
    cred = query.first()
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
    query = db.query(BaseCredential).filter(BaseCredential.id == credential_id)
    if profile.role != UserRole.ADMIN:
        query = query.filter(BaseCredential.user_profile_id == profile.id)
    cred = query.first()
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
    query = db.query(BaseCredential).filter(BaseCredential.id == credential_id)
    if profile.role != UserRole.ADMIN:
        query = query.filter(BaseCredential.user_profile_id == profile.id)
    cred = query.first()
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

    # LLM credentials: direct-provider testing removed — keys live in
    # agentgateway, pipelit has nothing to test them with.
    if cred.credential_type == "llm":
        _reject_llm_credential()

    raise HTTPException(
        status_code=400,
        detail=f"Credential type '{cred.credential_type}' does not support testing.",
    )


@router.get("/{credential_id}/models/", response_model=list[CredentialModelOut])
def list_credential_models(
    credential_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    """Removed: credential-derived model listing is gone.

    Models are listed from agentgateway (see api/available_models.py) —
    pipelit no longer holds provider API keys to query upstream /models.
    """
    _reject_llm_credential()
