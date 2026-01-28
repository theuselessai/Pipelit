"""System agent for shell commands, file operations, and system tasks."""
from app.agents.base import AgentWrapper, create_agent_executor
from app.tools.system import get_system_tools

SYSTEM_PROMPT = """You are a system administration agent. You can execute shell commands, read and write files, list directories, check disk usage, and monitor processes.

Be concise in your responses. When the user asks you to run a command or check something, execute it immediately using your tools — do not ask for confirmation. Report the results clearly.
If a command fails, explain why and suggest alternatives."""


def create_system_agent() -> AgentWrapper:
    """Create a system agent with system tools."""
    return create_agent_executor(
        tools=get_system_tools(),
        system_prompt=SYSTEM_PROMPT,
        temperature=0,
    )
