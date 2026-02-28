"""Settings API — read/update platform configuration."""

from __future__ import annotations

import logging
import shutil

from fastapi import APIRouter, Depends

from auth import get_current_user
from config import get_pipelit_dir, load_conf, save_conf, settings
from models.user import UserProfile
from schemas.settings import (
    PlatformConfigOut,
    SettingsResponse,
    SettingsUpdate,
    SettingsUpdateResponse,
)
from services.environment import (
    build_environment_report,
    detect_capabilities,
    detect_container,
    refresh_capabilities,
    resolve_sandbox_mode,
)
from services.rootfs import get_golden_dir, is_rootfs_ready

logger = logging.getLogger(__name__)

router = APIRouter()

# Fields that can be hot-reloaded without restarting the server process.
HOT_RELOADABLE = {"log_level", "zombie_execution_threshold_seconds"}

# Fields that require a server restart to take effect.
RESTART_REQUIRED = {
    "database_url",
    "redis_url",
    "platform_base_url",
    "sandbox_mode",
    "cors_allow_all_origins",
    "log_file",
}


def _build_config_out(conf) -> PlatformConfigOut:
    """Build PlatformConfigOut from a PipelitConfig + live settings."""
    return PlatformConfigOut(
        pipelit_dir=str(get_pipelit_dir()),
        sandbox_mode=conf.sandbox_mode or settings.SANDBOX_MODE,
        database_url=conf.database_url or settings.DATABASE_URL,
        redis_url=conf.redis_url or settings.REDIS_URL,
        log_level=conf.log_level or settings.LOG_LEVEL,
        log_file=conf.log_file or settings.LOG_FILE,
        platform_base_url=conf.platform_base_url or settings.PLATFORM_BASE_URL,
        cors_allow_all_origins=(
            conf.cors_allow_all_origins
            if conf.cors_allow_all_origins is not None
            else settings.CORS_ALLOW_ALL_ORIGINS
        ),
        zombie_execution_threshold_seconds=(
            conf.zombie_execution_threshold_seconds
            if conf.zombie_execution_threshold_seconds is not None
            else settings.ZOMBIE_EXECUTION_THRESHOLD_SECONDS
        ),
    )


def _build_environment_cached() -> dict:
    """Build environment report using cached capabilities (no subprocess probing)."""
    import platform as _platform

    container = detect_container()
    resolution = resolve_sandbox_mode(settings.SANDBOX_MODE)
    caps = detect_capabilities()  # uses cache if available

    bwrap_available = shutil.which("bwrap") is not None
    os_name = _platform.system()
    arch = _platform.machine()

    golden_dir = get_golden_dir()
    rootfs_ready = is_rootfs_ready(golden_dir)

    from services.environment import TIER1_TOOLS, TIER2_TOOLS, compute_setup_gate

    shell_tools = caps.get("shell_tools", {})
    if resolution.mode == "bwrap":
        tier1_met = True
    else:
        tier1_met = all(
            shell_tools.get(t, {}).get("available", False) for t in TIER1_TOOLS
        )
    tier2_warnings = [
        t
        for t in TIER2_TOOLS
        if not shell_tools.get(t, {}).get("available", False)
    ]

    passed, blocked_reason = compute_setup_gate(os_name, container, bwrap_available)

    return {
        "os": os_name,
        "arch": arch,
        "container": container,
        "bwrap_available": bwrap_available,
        "rootfs_ready": rootfs_ready,
        "sandbox_mode": resolution.mode,
        "capabilities": {
            "runtimes": caps.get("runtimes", {}),
            "shell_tools": shell_tools,
            "network": caps.get("network", {"dns": False, "http": False}),
        },
        "tier1_met": tier1_met,
        "tier2_warnings": tier2_warnings,
        "gate": {
            "passed": passed,
            "blocked_reason": blocked_reason,
        },
    }


@router.get("/", response_model=SettingsResponse)
def get_settings(user: UserProfile = Depends(get_current_user)):
    """Return current platform config + cached environment info."""
    conf = load_conf()
    config_out = _build_config_out(conf)
    environment = _build_environment_cached()
    return {"config": config_out, "environment": environment}


@router.patch("/", response_model=SettingsUpdateResponse)
def update_settings(
    payload: SettingsUpdate,
    user: UserProfile = Depends(get_current_user),
):
    """Update conf.json fields. Hot-reloads applicable settings in-process."""
    conf = load_conf()
    updates = payload.model_dump(exclude_unset=True)

    hot_reloaded: list[str] = []
    restart_required: list[str] = []

    for field_name, value in updates.items():
        # Write to conf.json model
        setattr(conf, field_name, value)

        if field_name in HOT_RELOADABLE:
            hot_reloaded.append(field_name)
        elif field_name in RESTART_REQUIRED:
            restart_required.append(field_name)

    # Persist to disk
    save_conf(conf)

    # Hot-reload applicable fields
    if "log_level" in updates:
        new_level = updates["log_level"]
        logging.getLogger().setLevel(new_level)
        settings.LOG_LEVEL = new_level
        logger.info("Hot-reloaded log_level to %s", new_level)

    if "zombie_execution_threshold_seconds" in updates:
        new_threshold = updates["zombie_execution_threshold_seconds"]
        settings.ZOMBIE_EXECUTION_THRESHOLD_SECONDS = new_threshold
        logger.info("Hot-reloaded zombie_execution_threshold_seconds to %s", new_threshold)

    config_out = _build_config_out(conf)
    return {
        "config": config_out,
        "hot_reloaded": hot_reloaded,
        "restart_required": restart_required,
    }


@router.post("/recheck-environment/", response_model=dict)
def recheck_environment(user: UserProfile = Depends(get_current_user)):
    """Force re-detection of environment capabilities."""
    refresh_capabilities()
    env = build_environment_report()
    return {"environment": env}
