"""Auth token endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.user import APIKey, UserProfile
from schemas.auth import MeResponse, SetupRequest, SetupStatusResponse, TokenRequest, TokenResponse

router = APIRouter()


def _verify_password(stored_hash: str, password: str) -> bool:
    """Verify password against stored hash."""
    from passlib.hash import pbkdf2_sha256

    if not stored_hash:
        return False
    return pbkdf2_sha256.verify(password, stored_hash)


@router.post("/token/", response_model=TokenResponse, responses={401: {"description": "Invalid credentials"}})
def obtain_token(payload: TokenRequest, db: Session = Depends(get_db)):
    user = db.query(UserProfile).filter(UserProfile.username == payload.username).first()
    if not user or not _verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    api_key = db.query(APIKey).filter(APIKey.user_id == user.id).first()
    if api_key:
        api_key.key = str(uuid.uuid4())
    else:
        api_key = APIKey(user_id=user.id, key=str(uuid.uuid4()))
        db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"key": api_key.key}


@router.get("/me/", response_model=MeResponse)
def me(user: UserProfile = Depends(get_current_user)):
    return {"username": user.username}


@router.get("/setup-status/", response_model=SetupStatusResponse)
def setup_status(db: Session = Depends(get_db)):
    has_users = db.query(UserProfile).first() is not None
    return {"needs_setup": not has_users}


@router.post("/setup/", response_model=TokenResponse, responses={409: {"description": "User already exists"}})
def setup(payload: SetupRequest, db: Session = Depends(get_db)):
    if db.query(UserProfile).first() is not None:
        raise HTTPException(status_code=409, detail="Setup already completed.")

    from passlib.hash import pbkdf2_sha256

    user = UserProfile(
        username=payload.username,
        password_hash=pbkdf2_sha256.hash(payload.password),
    )
    db.add(user)
    db.flush()

    api_key = APIKey(user_id=user.id, key=str(uuid.uuid4()))
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"key": api_key.key}
