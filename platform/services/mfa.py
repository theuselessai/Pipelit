"""TOTP-based MFA service — generation, verification, rate limiting."""

from __future__ import annotations

import logging
import math
import time as _time

import pyotp
import redis as redis_lib

from config import settings

logger = logging.getLogger(__name__)

# Rate-limit / lockout constants
MAX_ATTEMPTS_PER_MINUTE = 5
MAX_CONSECUTIVE_FAILURES = 10
RATE_WINDOW_SECONDS = 60
LOCKOUT_SECONDS = 900  # 15 minutes


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


# ---------------------------------------------------------------------------
# Core TOTP helpers
# ---------------------------------------------------------------------------


def generate_secret() -> str:
    """Generate a new TOTP secret."""
    return pyotp.random_base32()


def get_provisioning_uri(secret: str, username: str, issuer: str = "Pipelit") -> str:
    """Return an otpauth:// URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def get_current_code(secret: str) -> str:
    """Return the current 6-digit TOTP code (for agent programmatic use)."""
    return pyotp.TOTP(secret).now()


# ---------------------------------------------------------------------------
# Verification with replay prevention + rate limiting
# ---------------------------------------------------------------------------


def _check_rate_limit(r: redis_lib.Redis, user_id: int) -> str | None:
    """Return an error message if rate-limited or locked out, else None."""
    lockout_key = f"mfa:lockout:{user_id}"
    if r.exists(lockout_key):
        return "Account temporarily locked due to too many failed attempts. Try again later."

    rate_key = f"mfa:rate:{user_id}"
    attempts = r.get(rate_key)
    if attempts and int(attempts) >= MAX_ATTEMPTS_PER_MINUTE:
        return "Too many MFA attempts. Please wait a minute."

    return None


def _record_attempt(r: redis_lib.Redis, user_id: int, success: bool) -> None:
    """Record an MFA attempt for rate limiting."""
    rate_key = f"mfa:rate:{user_id}"
    pipe = r.pipeline()
    pipe.incr(rate_key)
    pipe.expire(rate_key, RATE_WINDOW_SECONDS)
    pipe.execute()

    failure_key = f"mfa:failures:{user_id}"
    if success:
        r.delete(failure_key)
    else:
        pipe = r.pipeline()
        pipe.incr(failure_key)
        pipe.expire(failure_key, LOCKOUT_SECONDS)
        results = pipe.execute()

        failures = results[0]  # INCR returns new value
        if failures and int(failures) >= MAX_CONSECUTIVE_FAILURES:
            r.setex(f"mfa:lockout:{user_id}", LOCKOUT_SECONDS, "1")


def verify_code(
    secret: str,
    code: str,
    user_id: int,
    last_used_at: int | None,
    r: redis_lib.Redis | None = None,
) -> tuple[bool, int | None]:
    """Verify a TOTP code with replay prevention and rate limiting.

    Returns (is_valid, time_step_or_None).
    The caller should persist ``time_step`` as ``totp_last_used_at`` on success.
    """
    if r is None:
        r = _redis()

    # Rate limit check
    err = _check_rate_limit(r, user_id)
    if err:
        return False, None

    totp = pyotp.TOTP(secret)

    # Verify with valid_window=1 (allows +-1 time step)
    if not totp.verify(code, valid_window=1):
        _record_attempt(r, user_id, success=False)
        return False, None

    # Replay prevention: compute the current time step
    now_ts = int(_time.time())
    step = math.floor(now_ts / totp.interval)

    if last_used_at is not None and step <= last_used_at:
        # Same time step was already used — replay
        _record_attempt(r, user_id, success=False)
        return False, None

    _record_attempt(r, user_id, success=True)
    return True, step
