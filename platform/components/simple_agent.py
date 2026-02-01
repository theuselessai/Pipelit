"""Simple agent component — LangGraph react agent with tools (renamed from react_agent)."""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from components import register
from services.llm import resolve_llm_for_node


@register("simple_agent")
def simple_agent_factory(node):
    """Build a simple_agent graph node."""
    llm = resolve_llm_for_node(node)
    concrete = node.component_config.concrete
    system_prompt = getattr(concrete, "system_prompt", "")
    extra = node.component_config.extra_config
    node_id = node.node_id

    tools = _resolve_tools(node)

    agent = create_react_agent(
        llm,
        tools,
        prompt=SystemMessage(content=system_prompt) if system_prompt else None,
    )

    def simple_agent_node(state: dict) -> dict:
        messages = list(state.get("messages", []))
        result = agent.invoke({"messages": messages})
        out_messages = result.get("messages", [])

        final_content = ""
        for msg in reversed(out_messages):
            if hasattr(msg, "content") and msg.content and msg.type == "ai":
                final_content = msg.content
                break

        return {
            "messages": out_messages,
            "node_outputs": {node_id: final_content},
        }

    return simple_agent_node


def _resolve_tools(node) -> list:
    """Resolve LangChain tools from edge_label='tool' edges + WorkflowTool entries."""
    tools = []

    # Legacy: WorkflowTool entries
    try:
        from database import SessionLocal
        from models.tool import WorkflowTool, ToolDefinition
        db = SessionLocal()
        workflow_tools = (
            db.query(WorkflowTool)
            .join(ToolDefinition)
            .filter(WorkflowTool.workflow_id == node.workflow_id, WorkflowTool.enabled == True)
            .all()
        )
        for wt in workflow_tools:
            tool_def = wt.tool_definition
            tool = _load_tool(tool_def.name, tool_def.tool_type, wt.config_overrides)
            if tool is not None:
                tools.append(tool)
        db.close()
    except Exception:
        pass

    return tools


def _load_tool(name: str, tool_type: str, config_overrides: dict):
    """Load a LangChain tool by name. Returns None if not found."""
    _TOOL_MAP = {}

    try:
        from app.tools.system import (
            shell_execute,
            file_read,
            file_write,
            disk_usage,
        )

        _TOOL_MAP.update(
            {
                "shell_execute": shell_execute,
                "file_read": file_read,
                "file_write": file_write,
                "disk_usage": disk_usage,
            }
        )
    except ImportError:
        pass

    try:
        from app.tools.search import web_search, web_search_news

        _TOOL_MAP.update(
            {
                "web_search": web_search,
                "web_search_news": web_search_news,
            }
        )
    except ImportError:
        pass

    try:
        from app.tools.browser import navigate, screenshot, click, type_text, get_page_text

        _TOOL_MAP.update(
            {
                "navigate": navigate,
                "screenshot": screenshot,
                "click": click,
                "type_text": type_text,
                "get_page_text": get_page_text,
            }
        )
    except ImportError:
        pass

    try:
        from app.tools.research import analyze_text, compare_items

        _TOOL_MAP.update(
            {
                "analyze_text": analyze_text,
                "compare_items": compare_items,
            }
        )
    except ImportError:
        pass

    return _TOOL_MAP.get(name)
