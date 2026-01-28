"""LangChain LLM service - replaces aichat HTTP/subprocess calls."""
import logging
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import settings

logger = logging.getLogger(__name__)


def _message_to_langchain(msg: dict):
    """Convert a dict message to a LangChain message object."""
    role = msg.get("role", "user")
    content = msg.get("content", "")
    if role == "system":
        return SystemMessage(content=content)
    elif role == "assistant":
        return AIMessage(content=content)
    else:
        return HumanMessage(content=content)


def strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from response."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def get_context_window() -> int:
    """Get context window size from settings."""
    return settings.DEFAULT_CONTEXT_WINDOW


def get_compress_threshold() -> int:
    """Get compression threshold."""
    return int(get_context_window() * settings.COMPRESS_RATIO)


def create_llm(
    model: str | None = None,
    temperature: float | None = None,
    **kwargs,
) -> BaseChatModel:
    """
    Create a LangChain chat model based on config.

    Args:
        model: Override model name (defaults to settings.LLM_MODEL)
        temperature: Override temperature (defaults to settings.LLM_TEMPERATURE)
        **kwargs: Additional kwargs passed to the LLM constructor
    """
    model = model or settings.LLM_MODEL
    temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
    provider = settings.LLM_PROVIDER.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=settings.LLM_API_KEY,
            **kwargs,
        )

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            temperature=temperature,
            api_key=settings.LLM_API_KEY,
            **kwargs,
        )

    elif provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=settings.LLM_API_KEY or "not-needed",
            base_url=settings.LLM_BASE_URL,
            **kwargs,
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


class LLMService:
    """LLM service wrapping LangChain for sync usage (RQ workers)."""

    def __init__(self, llm: BaseChatModel | None = None):
        self.llm = llm or create_llm()

    def chat(self, messages: list[dict]) -> str:
        """Send messages and get response."""
        lc_messages = [_message_to_langchain(m) for m in messages]
        response = self.llm.invoke(lc_messages)
        return response.content

    def summarize(self, text: str) -> str:
        """Summarize text."""
        prompt = (
            "Summarize this conversation in 200 words or less. "
            "Focus on key topics, decisions, and context needed to continue.\n\n"
            f"{text}"
        )
        return self.chat([{"role": "user", "content": prompt}])
