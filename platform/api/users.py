"""User management + API key management endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models.user import APIKey, UserProfile, UserRole
from schemas.users import (
    APIKeyCreateIn,
    APIKeyCreatedOut,
    APIKeyOut,
    SelfUpdateIn,
    UserCreateIn,
    UserListOut,
    UserOut,
    UserUpdateIn,
)

logger = logging.getLogger(__name__)

users_router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _user_to_out(user: UserProfile, db: Session) -> UserOut:
    key_count = db.query(APIKey).filter(
        APIKey.user_id == user.id, APIKey.is_active == True  # noqa: E712
    ).count()
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        first_name=user.first_name,
        last_name=user.last_name,
        created_at=user.created_at,
        mfa_enabled=user.mfa_enabled,
        key_count=key_count,
    )


def _create_api_key(
    db: Session, user_id: int, name: str, expires_at: datetime | None = None,
) -> APIKey:
    raw_key = str(uuid.uuid4())
    key = APIKey(
        user_id=user_id,
        key=raw_key,
        name=name,
        prefix=raw_key[:8],
        expires_at=expires_at,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


# ═══════════════════════════════════════════════════════════════════════════════
# Self-service endpoints  (must be registered BEFORE /{user_id} routes)
# ═══════════════════════════════════════════════════════════════════════════════


@users_router.get("/me", response_model=UserOut)
def get_own_profile(
    user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _user_to_out(user, db)


@users_router.patch("/me", response_model=UserOut)
def update_own_profile(
    payload: SelfUpdateIn,
    user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.password is not None:
        user.password_hash = _hash_password(payload.password)
    if payload.first_name is not None:
        user.first_name = payload.first_name
    if payload.last_name is not None:
        user.last_name = payload.last_name
    db.commit()
    db.refresh(user)
    return _user_to_out(user, db)


@users_router.post("/me/keys", response_model=APIKeyCreatedOut, status_code=201)
def create_own_key(
    payload: APIKeyCreateIn,
    user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    key = _create_api_key(db, user.id, payload.name, payload.expires_at)
    return APIKeyCreatedOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        is_active=key.is_active,
        key=key.key,
    )


@users_router.get("/me/keys", response_model=list[APIKeyOut])
def list_own_keys(
    user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    keys = db.query(APIKey).filter(APIKey.user_id == user.id).order_by(APIKey.created_at.desc()).all()
    return [APIKeyOut.model_validate(k) for k in keys]


@users_router.delete("/me/keys/{key_id}", status_code=204)
def revoke_own_key(
    key_id: int,
    user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    key = db.query(APIKey).filter(APIKey.id == key_id, APIKey.user_id == user.id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found.")
    key.is_active = False
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# Admin-only user CRUD
# ═══════════════════════════════════════════════════════════════════════════════


@users_router.post("/", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreateIn,
    admin: UserProfile = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.role not in (UserRole.ADMIN, UserRole.NORMAL):
        raise HTTPException(status_code=400, detail="Invalid role. Must be 'admin' or 'normal'.")
    existing = db.query(UserProfile).filter(UserProfile.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists.")

    user = UserProfile(
        username=payload.username,
        password_hash=_hash_password(payload.password),
        role=payload.role,
        first_name=payload.first_name or "",
        last_name=payload.last_name or "",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_to_out(user, db)


@users_router.get("/", response_model=UserListOut)
def list_users(
    offset: int = 0,
    limit: int = 50,
    admin: UserProfile = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.query(UserProfile).count()
    users = db.query(UserProfile).offset(offset).limit(limit).all()
    return UserListOut(
        users=[_user_to_out(u, db) for u in users],
        total=total,
    )


@users_router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    admin: UserProfile = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(UserProfile).filter(UserProfile.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return _user_to_out(user, db)


@users_router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdateIn,
    admin: UserProfile = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(UserProfile).filter(UserProfile.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if payload.role is not None:
        if payload.role not in (UserRole.ADMIN, UserRole.NORMAL):
            raise HTTPException(status_code=400, detail="Invalid role.")
        user.role = payload.role
    if payload.password is not None:
        user.password_hash = _hash_password(payload.password)
    if payload.first_name is not None:
        user.first_name = payload.first_name
    if payload.last_name is not None:
        user.last_name = payload.last_name
    db.commit()
    db.refresh(user)
    return _user_to_out(user, db)


@users_router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    admin: UserProfile = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(UserProfile).filter(UserProfile.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    # Soft-delete: deactivate all API keys
    db.query(APIKey).filter(APIKey.user_id == user.id).update({"is_active": False})
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# Admin key management for any user
# ═══════════════════════════════════════════════════════════════════════════════


@users_router.post("/{user_id}/keys", response_model=APIKeyCreatedOut, status_code=201)
def create_user_key(
    user_id: int,
    payload: APIKeyCreateIn,
    admin: UserProfile = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(UserProfile).filter(UserProfile.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    key = _create_api_key(db, user.id, payload.name, payload.expires_at)
    return APIKeyCreatedOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        is_active=key.is_active,
        key=key.key,
    )


@users_router.get("/{user_id}/keys", response_model=list[APIKeyOut])
def list_user_keys(
    user_id: int,
    admin: UserProfile = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(UserProfile).filter(UserProfile.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    keys = db.query(APIKey).filter(APIKey.user_id == user.id).order_by(APIKey.created_at.desc()).all()
    return [APIKeyOut.model_validate(k) for k in keys]


@users_router.delete("/{user_id}/keys/{key_id}", status_code=204)
def revoke_user_key(
    user_id: int,
    key_id: int,
    admin: UserProfile = Depends(require_admin),
    db: Session = Depends(get_db),
):
    key = db.query(APIKey).filter(APIKey.id == key_id, APIKey.user_id == user_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found.")
    key.is_active = False
    db.commit()
