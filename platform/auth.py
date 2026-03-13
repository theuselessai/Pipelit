"""Bearer token authentication dependency."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.user import APIKey, UserProfile, UserRole

bearer_scheme = HTTPBearer()

# Debounce interval for last_used_at updates (avoid write on every request)
_LAST_USED_DEBOUNCE = timedelta(minutes=1)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserProfile:
    """FastAPI dependency: validate Bearer token and return UserProfile.

    Supports both session tokens and named API keys.  Keys must be active
    and not expired.  Updates ``last_used_at`` with 1-minute debounce.
    """
    token = credentials.credentials
    api_key = db.query(APIKey).filter(APIKey.key == token).first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )

    # Check key is active
    if not api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has been revoked.",
        )

    # Check expiration
    if api_key.expires_at is not None:
        now = datetime.now(timezone.utc)
        expires = api_key.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired.",
            )

    # Debounced last_used_at update (best-effort, never blocks auth)
    now = datetime.now(timezone.utc)
    if api_key.last_used_at is None or (now - _ensure_tz(api_key.last_used_at)) > _LAST_USED_DEBOUNCE:
        try:
            api_key.last_used_at = now
            db.commit()
        except Exception:
            db.rollback()

    user = db.query(UserProfile).filter(UserProfile.id == api_key.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    return user


def _ensure_tz(dt: datetime) -> datetime:
    """Add UTC tzinfo if datetime is naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def require_admin(
    user: UserProfile = Depends(get_current_user),
) -> UserProfile:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return user


def verify_gateway_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> None:
    """FastAPI dependency: validate gateway inbound token."""
    if not settings.GATEWAY_INBOUND_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gateway token not configured",
        )
    if not secrets.compare_digest(credentials.credentials, settings.GATEWAY_INBOUND_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid gateway token",
        )
