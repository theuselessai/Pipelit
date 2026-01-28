"""Base agent factory for creating LangChain agents."""
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from app.services.llm import create_llm

logger = logging.getLogger(__name__)


class AgentWrapper:
    """Wraps a langgraph react agent to provide a compatible invoke interface."""

    def __init__(self, graph):
        self.graph = graph

    def invoke(self, inputs: dict) -> dict:
        message = inputs.get("input", "")
        chat_history = inputs.get("chat_history", [])

        # Convert dict history to LangChain message objects
        lc_messages = []
        for msg in chat_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            elif role == "system":
                lc_messages.append(SystemMessage(content=content))

        lc_messages.append(HumanMessage(content=message))

        result = self.graph.invoke({"messages": lc_messages})
        messages = result.get("messages", [])
        # Last AI message is the final output
        output = ""
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.type == "ai" and msg.content:
                output = msg.content
                break
        return {"output": output}


def create_agent_executor(
    tools: list,
    system_prompt: str,
    model: str | None = None,
    temperature: float | None = None,
    max_iterations: int = 10,
) -> AgentWrapper:
    """
    Create a LangGraph react agent with the given tools and system prompt.

    Args:
        tools: List of LangChain tools
        system_prompt: System prompt for the agent
        model: Override model name
        temperature: Override temperature
        max_iterations: Max agent iterations
    """
    llm = create_llm(model=model, temperature=temperature)

    graph = create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )

    return AgentWrapper(graph)
