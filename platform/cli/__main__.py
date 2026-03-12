"""CLI for Pipelit platform setup and fixture loading.

Usage:
    cd platform && python -m cli setup --username admin --password secret
    cd platform && python -m cli apply-fixture default-agent --provider openai --model gpt-4o --api-key sk-...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid


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

        api_key = APIKey(user_id=user.id, key=str(uuid.uuid4()))
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
        ws = Workspace(name="default", path=workspace_path, user_profile_id=user.id)
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
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
