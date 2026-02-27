"""Auth token endpoint + MFA endpoints."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from auth import get_current_user
from config import PipelitConfig, get_pipelit_dir, save_conf
from database import get_db
from models.user import APIKey, UserProfile
from schemas.auth import (
    EnvironmentInfo,
    MeResponse,
    MFADisableRequest,
    MFALoginVerifyRequest,
    MFASetupResponse,
    MFAStatusResponse,
    MFAVerifyRequest,
    RootfsStatusResponse,
    SetupRequest,
    SetupStatusResponse,
    TokenRequest,
    TokenResponse,
)
from services.environment import build_environment_report, refresh_capabilities
from services.mfa import generate_secret, get_provisioning_uri, verify_code
from services.rootfs import get_golden_dir, is_rootfs_ready

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_password(stored_hash: str, password: str) -> bool:
    """Verify password against stored bcrypt hash."""
    if not stored_hash:
        return False

    import bcrypt

    try:
        return bcrypt.checkpw(password.encode(), stored_hash.encode())
    except (ValueError, UnicodeDecodeError):
        return False


# ---------------------------------------------------------------------------
# Existing auth endpoints (modified for MFA)
# ---------------------------------------------------------------------------


@router.post("/token/", response_model=TokenResponse, responses={401: {"description": "Invalid credentials"}})
def obtain_token(payload: TokenRequest, db: Session = Depends(get_db)):
    user = db.query(UserProfile).filter(UserProfile.username == payload.username).first()
    if not user or not _verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    # If MFA is enabled, don't issue a token yet — client must complete MFA
    if user.mfa_enabled:
        return {"key": "", "requires_mfa": True}

    api_key = db.query(APIKey).filter(APIKey.user_id == user.id).first()
    if api_key:
        api_key.key = str(uuid.uuid4())
    else:
        api_key = APIKey(user_id=user.id, key=str(uuid.uuid4()))
        db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"key": api_key.key, "requires_mfa": False}


@router.get("/me/", response_model=MeResponse)
def me(user: UserProfile = Depends(get_current_user)):
    return {"username": user.username, "mfa_enabled": user.mfa_enabled}


@router.get("/setup-status/", response_model=SetupStatusResponse)
def setup_status(db: Session = Depends(get_db)):
    has_users = db.query(UserProfile).first() is not None
    if has_users:
        return {"needs_setup": False, "environment": None}

    env = build_environment_report()
    return {"needs_setup": True, "environment": env}


@router.post("/setup/", response_model=TokenResponse, responses={409: {"description": "User already exists"}})
def setup(payload: SetupRequest, db: Session = Depends(get_db)):
    if db.query(UserProfile).first() is not None:
        raise HTTPException(status_code=409, detail="Setup already completed.")

    import bcrypt

    user = UserProfile(
        username=payload.username,
        password_hash=bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode(),
    )
    db.add(user)
    db.flush()

    api_key = APIKey(user_id=user.id, key=str(uuid.uuid4()))
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    # Write conf.json with setup config + detected environment
    try:
        env = build_environment_report()
        conf = PipelitConfig(
            setup_completed=True,
            sandbox_mode=payload.sandbox_mode or env.get("sandbox_mode", "auto"),
            database_url=payload.database_url or "",
            redis_url=payload.redis_url or "",
            log_level=payload.log_level or "",
            platform_base_url=payload.platform_base_url or "",
            detected_environment=env,
        )
        save_conf(conf)

        # Create default workspace directory
        workspace_dir = get_pipelit_dir() / "workspaces" / "default"
        workspace_dir.mkdir(parents=True, exist_ok=True)

        # If bwrap mode, enqueue rootfs preparation
        if env.get("sandbox_mode") == "bwrap" and not env.get("rootfs_ready"):
            try:
                from redis import Redis
                from rq import Queue

                from config import settings

                q = Queue(connection=Redis.from_url(settings.REDIS_URL))
                from tasks import prepare_rootfs_job

                q.enqueue(prepare_rootfs_job, tier=2)
            except Exception:
                logger.warning("Failed to enqueue rootfs preparation job", exc_info=True)
    except Exception:
        logger.warning("Failed to write conf.json during setup", exc_info=True)

    return {"key": api_key.key, "requires_mfa": False}


@router.post("/setup/recheck/", response_model=dict, responses={409: {"description": "Setup already completed"}})
def setup_recheck(db: Session = Depends(get_db)):
    """Re-run environment detection during setup wizard."""
    if db.query(UserProfile).first() is not None:
        raise HTTPException(status_code=409, detail="Setup already completed.")

    refresh_capabilities()
    env = build_environment_report()
    return {"environment": env}


@router.get("/setup/rootfs-status/", response_model=RootfsStatusResponse, responses={409: {"description": "Setup already completed"}})
def rootfs_status(db: Session = Depends(get_db)):
    """Check rootfs provisioning status during setup wizard."""
    if db.query(UserProfile).first() is not None:
        raise HTTPException(status_code=409, detail="Setup already completed.")

    golden_dir = get_golden_dir()
    ready = is_rootfs_ready(golden_dir)
    lock_path = golden_dir.parent / ".rootfs.lock"
    preparing = not ready and lock_path.exists()

    return {"ready": ready, "preparing": preparing, "error": None}


# ---------------------------------------------------------------------------
# MFA endpoints (authenticated)
# ---------------------------------------------------------------------------


@router.post("/mfa/setup/", response_model=MFASetupResponse)
def mfa_setup(user: UserProfile = Depends(get_current_user), db: Session = Depends(get_db)):
    """Generate a TOTP secret. Does NOT enable MFA until /mfa/verify/ is called."""
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled.")

    secret = generate_secret()
    user.totp_secret = secret
    db.commit()

    uri = get_provisioning_uri(secret, user.username)
    return {"secret": secret, "provisioning_uri": uri}


@router.post("/mfa/verify/", response_model=MFAStatusResponse)
def mfa_verify(
    payload: MFAVerifyRequest,
    user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify a TOTP code and enable MFA on the account."""
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled.")
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Call /mfa/setup/ first.")

    valid, step = verify_code(user.totp_secret, payload.code, user.id, user.totp_last_used_at)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid TOTP code.")

    user.mfa_enabled = True
    user.totp_last_used_at = step
    db.commit()
    return {"mfa_enabled": True}


@router.post("/mfa/disable/", response_model=MFAStatusResponse)
def mfa_disable(
    payload: MFADisableRequest,
    user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disable MFA after verifying a TOTP code."""
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled.")

    valid, _ = verify_code(user.totp_secret, payload.code, user.id, user.totp_last_used_at)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid TOTP code.")

    user.totp_secret = None
    user.mfa_enabled = False
    user.totp_last_used_at = None
    db.commit()
    return {"mfa_enabled": False}


@router.get("/mfa/status/", response_model=MFAStatusResponse)
def mfa_status(user: UserProfile = Depends(get_current_user)):
    """Return current MFA status."""
    return {"mfa_enabled": user.mfa_enabled}


@router.post("/mfa/reset/", response_model=MFAStatusResponse)
def mfa_reset(
    request: Request,
    db: Session = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    """Emergency MFA reset — only allowed from loopback addresses."""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="MFA reset only allowed from localhost.")

    user.totp_secret = None
    user.mfa_enabled = False
    user.totp_last_used_at = None
    db.commit()
    return {"mfa_enabled": False}


# ---------------------------------------------------------------------------
# MFA login completion (unauthenticated)
# ---------------------------------------------------------------------------


@router.post("/mfa/login-verify/", response_model=TokenResponse)
def mfa_login_verify(payload: MFALoginVerifyRequest, db: Session = Depends(get_db)):
    """Complete MFA login — accepts username + TOTP code, issues API key."""
    user = db.query(UserProfile).filter(UserProfile.username == payload.username).first()
    if not user or not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    valid, step = verify_code(user.totp_secret, payload.code, user.id, user.totp_last_used_at)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid TOTP code.")

    user.totp_last_used_at = step

    api_key = db.query(APIKey).filter(APIKey.user_id == user.id).first()
    if api_key:
        api_key.key = str(uuid.uuid4())
    else:
        api_key = APIKey(user_id=user.id, key=str(uuid.uuid4()))
        db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"key": api_key.key, "requires_mfa": False}
