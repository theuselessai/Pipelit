"""Browser agent for web browsing tasks."""
from app.agents.base import AgentWrapper, create_agent_executor
from app.tools.browser import get_browser_tools

BROWSER_PROMPT = """You are a web browsing agent. You can navigate to URLs, take screenshots, click elements, type text, and extract page content.

Be concise in your responses. Navigate to the requested pages and report what you find.
When taking screenshots, include the [IMAGE:path] marker in your response."""


def create_browser_agent() -> AgentWrapper:
    """Create a browser agent with browser tools."""
    return create_agent_executor(
        tools=get_browser_tools(),
        system_prompt=BROWSER_PROMPT,
        temperature=0,
    )
