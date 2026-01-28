"""Research agent for analysis and summarization tasks."""
from app.agents.base import AgentWrapper, create_agent_executor
from app.tools.research import get_research_tools

RESEARCH_PROMPT = """You are a research and analysis agent. You can analyze text, compare items, and provide structured summaries.

Be thorough but concise. Provide clear analysis with actionable insights."""


def create_research_agent() -> AgentWrapper:
    """Create a research agent with research tools."""
    return create_agent_executor(
        tools=get_research_tools(),
        system_prompt=RESEARCH_PROMPT,
        temperature=0.3,
    )
