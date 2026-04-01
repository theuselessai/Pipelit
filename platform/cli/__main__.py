"""CLI for Pipelit platform setup and fixture loading.

Usage:
    cd platform && python -m cli setup --username admin --password secret
    cd platform && python -m cli apply-fixture default-agent --provider openai --model gpt-4o --api-key sk-...
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys


def cmd_setup(args: argparse.Namespace) -> None:
    from database import SessionLocal
    from models.user import APIKey, UserProfile, UserRole

    db = SessionLocal()
    try:
        existing = db.query(UserProfile).first()
        if existing is not None:
            print(json.dumps({"username": existing.username, "setup_completed": True}))
            return

        import bcrypt

        user = UserProfile(
            username=args.username,
            password_hash=bcrypt.hashpw(args.password.encode(), bcrypt.gensalt()).decode(),
            role=UserRole.ADMIN,
        )
        db.add(user)
        db.flush()

        raw_key = secrets.token_urlsafe(32)
        api_key = APIKey(user_id=user.id, key=raw_key, name="default", prefix=raw_key[:8])
        db.add(api_key)
        db.commit()

        from config import PipelitConfig, get_pipelit_dir, save_conf
        from services.environment import build_environment_report

        env = build_environment_report()
        conf = PipelitConfig(
            setup_completed=True,
            sandbox_mode=args.sandbox_mode or env.get("sandbox_mode", "auto"),
            database_url=args.database_url or "",
            redis_url=args.redis_url or "",
            platform_base_url=args.platform_base_url or "",
            detected_environment=env,
        )
        save_conf(conf)

        from models.workspace import Workspace

        workspace_path = str(get_pipelit_dir() / "workspaces" / "default")
        os.makedirs(workspace_path, exist_ok=True)
        os.makedirs(os.path.join(workspace_path, ".tmp"), exist_ok=True)
        ws = Workspace(name="default", path=workspace_path, user_profile_id=user.id, allow_network=True)
        db.add(ws)
        db.commit()

        if env.get("sandbox_mode") == "bwrap" and not env.get("rootfs_ready"):
            from services.rootfs import prepare_golden_image

            prepare_golden_image(tier=2)

        print(json.dumps({"username": user.username, "setup_completed": True}))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def cmd_apply_fixture(args: argparse.Namespace) -> None:
    if args.fixture_name != "default-agent":
        print(json.dumps({"error": f"Unknown fixture: {args.fixture_name}"}), file=sys.stderr)
        sys.exit(1)

    from config import get_pipelit_dir
    from database import SessionLocal
    from models.credential import BaseCredential, LLMProviderCredential
    from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
    from models.user import UserProfile
    from models.workflow import Workflow

    db = SessionLocal()
    try:
        existing_wf = db.query(Workflow).filter(Workflow.slug == "default-agent").first()
        if existing_wf is not None:
            trigger_node = (
                db.query(WorkflowNode)
                .filter(
                    WorkflowNode.workflow_id == existing_wf.id,
                    WorkflowNode.component_type == "trigger_chat",
                )
                .first()
            )
            trigger_id = trigger_node.node_id if trigger_node else None
            print(json.dumps({"workflow_slug": "default-agent", "trigger_node_id": trigger_id}))
            return

        user = db.query(UserProfile).first()
        if user is None:
            print(json.dumps({"error": "No user found. Run 'setup' first."}), file=sys.stderr)
            sys.exit(1)

        base_cred = BaseCredential(
            user_profile_id=user.id,
            name=f"{args.provider} (default)",
            credential_type="llm",
        )
        db.add(base_cred)
        db.flush()

        llm_cred = LLMProviderCredential(
            base_credentials_id=base_cred.id,
            provider_type=args.provider,
            api_key=args.api_key,
            base_url=args.base_url or "",
        )
        db.add(llm_cred)
        db.flush()

        wf = Workflow(
            name="Default Agent",
            slug="default-agent",
            owner_id=user.id,
            is_active=True,
        )
        db.add(wf)
        db.flush()

        trigger_cfg = BaseComponentConfig(
            component_type="trigger_chat", is_active=True, priority=10
        )
        db.add(trigger_cfg)
        db.flush()
        trigger_node = WorkflowNode(
            workflow_id=wf.id,
            node_id="trigger_chat_1",
            component_type="trigger_chat",
            component_config_id=trigger_cfg.id,
            position_x=100,
            position_y=300,
        )
        db.add(trigger_node)

        model_cfg = BaseComponentConfig(
            component_type="ai_model",
            llm_credential_id=base_cred.id,
            model_name=args.model,
        )
        db.add(model_cfg)
        db.flush()
        model_node = WorkflowNode(
            workflow_id=wf.id,
            node_id="ai_model_1",
            component_type="ai_model",
            component_config_id=model_cfg.id,
            position_x=600,
            position_y=150,
        )
        db.add(model_node)

        agent_cfg = BaseComponentConfig(
            component_type="deep_agent",
            llm_model_config_id=model_cfg.id,
            extra_config={"conversation_memory": True},
        )
        db.add(agent_cfg)
        db.flush()
        agent_node = WorkflowNode(
            workflow_id=wf.id,
            node_id="deep_agent_1",
            component_type="deep_agent",
            component_config_id=agent_cfg.id,
            position_x=400,
            position_y=300,
        )
        db.add(agent_node)

        mr_cfg = BaseComponentConfig(component_type="memory_read")
        db.add(mr_cfg)
        db.flush()
        mr_node = WorkflowNode(
            workflow_id=wf.id,
            node_id="memory_read_1",
            component_type="memory_read",
            component_config_id=mr_cfg.id,
            position_x=600,
            position_y=450,
        )
        db.add(mr_node)

        mw_cfg = BaseComponentConfig(component_type="memory_write")
        db.add(mw_cfg)
        db.flush()
        mw_node = WorkflowNode(
            workflow_id=wf.id,
            node_id="memory_write_1",
            component_type="memory_write",
            component_config_id=mw_cfg.id,
            position_x=600,
            position_y=550,
        )
        db.add(mw_node)

        skill_path = str(get_pipelit_dir() / "workspaces" / "default" / "skills")
        skill_cfg = BaseComponentConfig(
            component_type="skill",
            extra_config={
                "skill_path": skill_path,
                "skill_source": "filesystem",
            },
        )
        db.add(skill_cfg)
        db.flush()
        skill_node = WorkflowNode(
            workflow_id=wf.id,
            node_id="skill_1",
            component_type="skill",
            component_config_id=skill_cfg.id,
            position_x=600,
            position_y=650,
        )
        db.add(skill_node)

        edges = [
            WorkflowEdge(
                workflow_id=wf.id,
                source_node_id="trigger_chat_1",
                target_node_id="deep_agent_1",
                edge_type="direct",
                edge_label="",
            ),
            WorkflowEdge(
                workflow_id=wf.id,
                source_node_id="ai_model_1",
                target_node_id="deep_agent_1",
                edge_type="direct",
                edge_label="llm",
            ),
            WorkflowEdge(
                workflow_id=wf.id,
                source_node_id="memory_read_1",
                target_node_id="deep_agent_1",
                edge_type="direct",
                edge_label="tool",
            ),
            WorkflowEdge(
                workflow_id=wf.id,
                source_node_id="memory_write_1",
                target_node_id="deep_agent_1",
                edge_type="direct",
                edge_label="tool",
            ),
            WorkflowEdge(
                workflow_id=wf.id,
                source_node_id="skill_1",
                target_node_id="deep_agent_1",
                edge_type="direct",
                edge_label="skill",
            ),
        ]
        db.add_all(edges)

        os.makedirs(skill_path, exist_ok=True)

        db.commit()

        print(json.dumps({"workflow_slug": "default-agent", "trigger_node_id": "trigger_chat_1"}))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _resolve_provider_name(credential) -> str:
    """Derive provider name from credential. Must NOT contain hyphens."""
    if credential.provider_type in ("openai", "anthropic", "glm"):
        return credential.provider_type
    # openai_compatible: sanitize the credential name
    base_name = credential.base_credentials.name or f"custom{credential.base_credentials_id}"
    # Remove hyphens (breaks route parsing), lowercase, replace spaces/underscores
    sanitized = base_name.lower().replace(" ", "_").replace("-", "_")
    # Remove non-alphanumeric except underscores
    sanitized = "".join(c for c in sanitized if c.isalnum() or c == "_")
    return sanitized or f"custom{credential.base_credentials_id}"


def _model_to_slug(model_name: str) -> str:
    """Convert model name to a filesystem-safe slug."""
    slug = model_name.lower().replace(" ", "-").replace("/", "-").replace(":", "-")
    # Keep only alphanumeric, hyphens, dots
    slug = "".join(c for c in slug if c.isalnum() or c in "-.")
    return slug or "default"


def _parse_base_url(base_url: str, provider_type: str = "") -> tuple[str, str]:
    """Parse a base_url into (host:port, path) for agentgateway overrides.

    Always includes the port (443 for HTTPS, 80 for HTTP) even when not
    explicitly present in the URL.  Appends the appropriate endpoint suffix
    based on provider_type.
    """
    from urllib.parse import urlparse

    if not base_url or not base_url.strip():
        return "", ""

    parsed = urlparse(base_url.rstrip("/"))
    host = parsed.hostname or ""
    port = parsed.port
    if host and not port:
        port = 443 if parsed.scheme == "https" else 80
    host_override = f"{host}:{port}" if host else ""
    path_override = parsed.path or ""

    # Append endpoint suffix
    if provider_type in ("openai_compatible", "glm", "openai"):
        if path_override and not path_override.endswith("/chat/completions"):
            path_override = path_override.rstrip("/") + "/chat/completions"
    elif provider_type == "anthropic":
        if path_override and not path_override.endswith("/messages"):
            path_override = path_override.rstrip("/") + "/messages"

    return host_override, path_override


def cmd_migrate_credentials(args: argparse.Namespace) -> None:
    """Migrate existing LLM credentials from DB to agentgateway provider/model structure."""
    from pathlib import Path

    from database import SessionLocal
    from models.credential import BaseCredential, LLMProviderCredential
    from models.node import BaseComponentConfig
    from services.agentgateway_config import (
        add_model,
        add_provider,
        list_providers,
        reassemble_config,
        remove_provider_key,
        write_provider_key,
    )

    if args.rollback:
        _rollback_migration(args)
        return

    db = SessionLocal()
    try:
        # Query all LLM credentials with their base credential (for name)
        credentials = (
            db.query(LLMProviderCredential)
            .join(BaseCredential, LLMProviderCredential.base_credentials_id == BaseCredential.id)
            .all()
        )

        if not credentials:
            print(json.dumps({"migrated": 0, "providers": 0, "models": 0, "message": "No LLM credentials found"}))
            return

        from config import settings

        agw_dir = Path(settings.AGENTGATEWAY_DIR) if settings.AGENTGATEWAY_DIR else None
        if not agw_dir and not args.dry_run:
            print(json.dumps({"error": "AGENTGATEWAY_DIR is not set"}), file=sys.stderr)
            sys.exit(1)

        # Group credentials by provider
        # Each provider gets one key + one _provider.yaml; each credential+model gets a model file
        providers_seen: dict[str, list] = {}  # provider_name -> [credential, ...]
        for cred in credentials:
            provider_name = _resolve_provider_name(cred)
            providers_seen.setdefault(provider_name, []).append(cred)

        providers_created = 0
        models_created = 0
        skipped = 0

        # Map base_credentials_id -> (provider_name, model_slug) for --populate-routes
        route_map: dict[int, str] = {}

        for provider_name, creds in providers_seen.items():
            # Use the first credential for provider-level config (key, host, path)
            first_cred = creds[0]

            # Check for existing provider dir/key
            if agw_dir and not args.dry_run:
                provider_dir_exists = (agw_dir / "config.d" / "backends" / provider_name).exists()
                key_exists = (agw_dir / "keys" / f"{provider_name}.key").exists()
            else:
                provider_dir_exists = False
                key_exists = False

            provider_already_exists = provider_dir_exists or key_exists

            if provider_already_exists and not args.force:
                skipped += len(creds)
                for c in creds:
                    print(
                        f"SKIP: {c.base_credentials.name} -> provider={provider_name} "
                        f"(already exists, use --force to overwrite)",
                        file=sys.stderr,
                    )
                continue

            # Parse base_url for host/path overrides
            host_override, path_override = _parse_base_url(
                first_cred.base_url or "", first_cred.provider_type
            )

            if args.dry_run:
                print(
                    f"DRY-RUN: provider={provider_name}, "
                    f"type={first_cred.provider_type}, "
                    f"host_override={host_override!r}, path_override={path_override!r}",
                    file=sys.stderr,
                )
                providers_created += 1
                for cred in creds:
                    model_name = cred.base_credentials.name or "default"
                    model_slug = _model_to_slug(model_name)
                    print(
                        f"DRY-RUN:   model={model_slug} (name={model_name})",
                        file=sys.stderr,
                    )
                    models_created += 1
                    route_map[cred.base_credentials_id] = f"{provider_name}-{model_slug}"
                continue

            # Write encrypted key file (one per provider, using first credential's key)
            write_provider_key(provider_name, first_cred.api_key)

            # Write _provider.yaml
            add_provider(
                provider=provider_name,
                provider_type=first_cred.provider_type,
                host_override=host_override,
                path_override=path_override,
            )
            providers_created += 1

            # Write model files for each credential
            for cred in creds:
                model_name = cred.base_credentials.name or "default"
                model_slug = _model_to_slug(model_name)

                # Check if model file exists
                if agw_dir:
                    model_file_exists = (
                        agw_dir / "config.d" / "backends" / provider_name / f"{model_slug}.yaml"
                    ).exists()
                else:
                    model_file_exists = False

                if model_file_exists and not args.force:
                    skipped += 1
                    print(
                        f"SKIP: model {model_slug} in {provider_name} (already exists)",
                        file=sys.stderr,
                    )
                    continue

                add_model(
                    provider=provider_name,
                    model_slug=model_slug,
                    model_name=model_name,
                    reassemble=False,
                )
                models_created += 1
                route_map[cred.base_credentials_id] = f"{provider_name}-{model_slug}"

        # Single reassemble at the end
        if not args.dry_run and (providers_created > 0 or models_created > 0):
            reassemble_config()

        # Optionally populate backend_route on component_configs
        routes_updated = 0
        if args.populate_routes and route_map and not args.dry_run:
            configs = (
                db.query(BaseComponentConfig)
                .filter(BaseComponentConfig.llm_credential_id.isnot(None))
                .all()
            )
            for cfg in configs:
                route = route_map.get(cfg.llm_credential_id)
                if route:
                    cfg.backend_route = route
                    routes_updated += 1
            if routes_updated:
                db.commit()

        result = {
            "providers": providers_created,
            "models": models_created,
            "skipped": skipped,
            "routes_updated": routes_updated,
        }
        print(json.dumps(result))
        summary_parts = [
            f"{providers_created} providers created",
            f"{models_created} models created",
        ]
        if skipped:
            summary_parts.append(f"{skipped} skipped")
        if routes_updated:
            summary_parts.append(f"{routes_updated} routes updated")
        print(", ".join(summary_parts), file=sys.stderr)
    except Exception:
        raise
    finally:
        db.close()


def _rollback_migration(args: argparse.Namespace) -> None:
    """Reverse a credential migration: delete provider dirs + keys, reassemble, disable."""
    import shutil
    from pathlib import Path

    from config import settings
    from database import SessionLocal
    from models.node import BaseComponentConfig
    from services.agentgateway_config import list_providers, reassemble_config, remove_provider_key

    agw_dir = Path(settings.AGENTGATEWAY_DIR) if settings.AGENTGATEWAY_DIR else None
    if not agw_dir:
        print(json.dumps({"error": "AGENTGATEWAY_DIR is not set"}), file=sys.stderr)
        sys.exit(1)

    providers = list_providers()
    if not providers:
        print(json.dumps({"rolled_back": 0, "message": "No providers found"}))
        return

    removed = 0
    for name in providers:
        if args.dry_run:
            print(f"DRY-RUN: would remove provider={name} (directory + key)", file=sys.stderr)
            removed += 1
            continue

        provider_dir = agw_dir / "config.d" / "backends" / name
        if provider_dir.exists():
            shutil.rmtree(provider_dir)
        remove_provider_key(name)
        removed += 1

    if not args.dry_run and removed > 0:
        reassemble_config()

        # Set AGENTGATEWAY_ENABLED=false in .env
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        _set_env_var(env_path, "AGENTGATEWAY_ENABLED", "false")

    # Null out backend_route on all component_configs if --populate-routes was used
    routes_cleared = 0
    if args.populate_routes and not args.dry_run:
        db = SessionLocal()
        try:
            configs = (
                db.query(BaseComponentConfig)
                .filter(BaseComponentConfig.backend_route.isnot(None))
                .all()
            )
            for cfg in configs:
                cfg.backend_route = None
                routes_cleared += 1
            if routes_cleared:
                db.commit()
        finally:
            db.close()

    result = {"rolled_back": removed, "routes_cleared": routes_cleared}
    print(json.dumps(result))
    print(f"{removed} providers removed", file=sys.stderr)
    if routes_cleared:
        print(f"{routes_cleared} backend_route values cleared", file=sys.stderr)
    if not args.dry_run:
        print("Set AGENTGATEWAY_ENABLED=false in .env", file=sys.stderr)
        print("Please restart Pipelit to apply changes.", file=sys.stderr)


def _set_env_var(env_path: Path, key: str, value: str) -> None:
    """Set or update an environment variable in a .env file."""
    from pathlib import Path

    if env_path.exists():
        lines = env_path.read_text().splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n")
    else:
        env_path.write_text(f"{key}={value}\n")


def cmd_import_fixture(args: argparse.Namespace) -> None:
    """Import a workflow from a fixture JSON file."""
    from database import SessionLocal
    from models.credential import BaseCredential
    from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
    from models.user import UserProfile
    from models.workflow import Workflow

    if not os.path.isfile(args.file):
        print(json.dumps({"error": f"File not found: {args.file}"}), file=sys.stderr)
        sys.exit(1)

    with open(args.file, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}), file=sys.stderr)
            sys.exit(1)

    missing = [k for k in ("slug", "name", "nodes", "edges") if k not in data]
    if missing:
        print(json.dumps({"error": f"Missing required fields: {', '.join(missing)}"}), file=sys.stderr)
        sys.exit(1)

    slug = data["slug"]
    db = SessionLocal()
    try:
        if db.query(Workflow).filter(Workflow.slug == slug).first():
            print(json.dumps({"skipped": True, "workflow_slug": slug, "reason": "already exists"}))
            return

        user = db.query(UserProfile).first()
        if not user:
            print(json.dumps({"error": "No user found. Run 'setup' first."}), file=sys.stderr)
            sys.exit(1)

        # Resolve LLM credential — reuse first existing or create one
        llm_cred_base = db.query(BaseCredential).filter(BaseCredential.credential_type == "llm").first()
        if not llm_cred_base:
            print(json.dumps({"error": "No LLM credential found. Run 'apply-fixture default-agent' first."}), file=sys.stderr)
            sys.exit(1)
        cred_id = llm_cred_base.id

        # Resolve default model name from an ai_model node in the fixture
        default_model = ""
        for nd in data["nodes"]:
            if nd["component_type"] == "ai_model" and nd.get("config", {}).get("model_name"):
                default_model = nd["config"]["model_name"]
                break

        wf = Workflow(
            name=data["name"],
            slug=slug,
            description=data.get("description", ""),
            owner_id=user.id,
            is_active=data.get("is_active", True),
            max_execution_seconds=data.get("max_execution_seconds", 600),
        )
        db.add(wf)
        db.flush()

        # Build llm edge map: target_node_id → source_node_id (ai_model)
        llm_edge_map: dict[str, str] = {}
        for ed in data["edges"]:
            if ed.get("edge_label") == "llm":
                llm_edge_map[ed["target_node_id"]] = ed["source_node_id"]

        # Create nodes
        node_configs: dict[str, BaseComponentConfig] = {}

        for nd in data["nodes"]:
            cfg = nd["config"]
            extra = cfg.get("extra_config") or {}
            # input_template lives inside extra_config, not as a top-level column
            if cfg.get("input_template"):
                extra["input_template"] = cfg["input_template"]
            cc = BaseComponentConfig(
                component_type=nd["component_type"],
                system_prompt=cfg.get("system_prompt") or "",
                extra_config=extra,
                is_active=cfg.get("is_active", True),
                priority=cfg.get("priority", 0),
            )

            # Wire LLM fields for ai_model nodes
            if nd["component_type"] == "ai_model":
                cc.llm_credential_id = cred_id
                cc.model_name = cfg.get("model_name") or default_model
                if cfg.get("temperature") is not None:
                    cc.temperature = cfg["temperature"]
                if cfg.get("max_tokens") is not None:
                    cc.max_tokens = cfg["max_tokens"]

            # Trigger config
            if cfg.get("trigger_config"):
                cc.trigger_config = cfg["trigger_config"]

            db.add(cc)
            db.flush()
            node_configs[nd["node_id"]] = cc

        # Wire llm_model_config_id via edge relationships
        for agent_id, model_id in llm_edge_map.items():
            if agent_id in node_configs and model_id in node_configs:
                node_configs[agent_id].llm_model_config_id = node_configs[model_id].id

        db.flush()

        # Create WorkflowNode rows
        for nd in data["nodes"]:
            node = WorkflowNode(
                workflow_id=wf.id,
                node_id=nd["node_id"],
                label=nd.get("label") or nd["node_id"],
                component_type=nd["component_type"],
                component_config_id=node_configs[nd["node_id"]].id,
                position_x=nd.get("position_x", 0),
                position_y=nd.get("position_y", 0),
                is_entry_point=nd.get("is_entry_point", False),
                interrupt_before=nd.get("interrupt_before", False),
                interrupt_after=nd.get("interrupt_after", False),
            )
            db.add(node)

        # Create edges
        for ed in data["edges"]:
            edge = WorkflowEdge(
                workflow_id=wf.id,
                source_node_id=ed["source_node_id"],
                target_node_id=ed["target_node_id"],
                edge_type=ed.get("edge_type", "direct"),
                edge_label=ed.get("edge_label", ""),
                condition_value=ed.get("condition_value", ""),
                condition_mapping=ed.get("condition_mapping"),
                priority=ed.get("priority", 0),
            )
            db.add(edge)

        db.commit()

        trigger = next((n["node_id"] for n in data["nodes"] if n["component_type"].startswith("trigger_")), None)
        print(json.dumps({
            "workflow_slug": slug,
            "trigger_node_id": trigger,
            "nodes": len(data["nodes"]),
            "edges": len(data["edges"]),
        }))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="cli", description="Pipelit platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sp_setup = sub.add_parser("setup", help="Bootstrap first admin user and platform config")
    sp_setup.add_argument("--username", required=True)
    sp_setup.add_argument(
        "--password",
        default=os.environ.get("PIPELIT_SETUP_PASSWORD"),
        help="Admin password (or set PIPELIT_SETUP_PASSWORD env var)",
    )
    sp_setup.add_argument("--sandbox-mode", default=None)
    sp_setup.add_argument("--database-url", default=None)
    sp_setup.add_argument("--redis-url", default=None)
    sp_setup.add_argument("--platform-base-url", default=None)

    sp_fixture = sub.add_parser("apply-fixture", help="Apply a named fixture to the database")
    sp_fixture.add_argument("fixture_name", help="Fixture to apply (e.g. default-agent)")
    sp_fixture.add_argument("--provider", required=True, help="LLM provider type")
    sp_fixture.add_argument("--model", required=True, help="LLM model name")
    sp_fixture.add_argument(
        "--api-key",
        default=os.environ.get("PIPELIT_LLM_API_KEY"),
        help="LLM provider API key (or set PIPELIT_LLM_API_KEY env var)",
    )
    sp_fixture.add_argument("--base-url", default=None, help="LLM provider base URL")

    sp_import = sub.add_parser("import-fixture", help="Import a workflow from a fixture JSON file")
    sp_import.add_argument("file", help="Path to fixture JSON file")

    sp_migrate = sub.add_parser(
        "migrate-credentials",
        help="Migrate LLM credentials from DB to agentgateway filesystem",
    )
    sp_migrate.add_argument("--rollback", action="store_true", help="Reverse the migration")
    sp_migrate.add_argument("--force", action="store_true", help="Overwrite existing provider dirs and key files")
    sp_migrate.add_argument("--dry-run", action="store_true", help="Print what would be done without writing files")
    sp_migrate.add_argument("--populate-routes", action="store_true", help="Set backend_route on existing component_configs")

    args = parser.parse_args()

    if args.command == "setup" and not args.password:
        parser.error("--password is required (or set PIPELIT_SETUP_PASSWORD env var)")
    if args.command == "apply-fixture" and not args.api_key:
        parser.error("--api-key is required (or set PIPELIT_LLM_API_KEY env var)")

    try:
        if args.command == "setup":
            cmd_setup(args)
        elif args.command == "apply-fixture":
            cmd_apply_fixture(args)
        elif args.command == "import-fixture":
            cmd_import_fixture(args)
        elif args.command == "migrate-credentials":
            cmd_migrate_credentials(args)
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
