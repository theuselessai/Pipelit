"""AIChat API client - sync version for RQ workers."""
import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Cache for model context windows
_model_context_windows: dict[str, int] = {}


def strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from response."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def get_context_window(model: str) -> int:
    """Get context window for a model."""
    model_id = model.split(":")[-1] if ":" in model else model
    return _model_context_windows.get(model_id, settings.DEFAULT_CONTEXT_WINDOW)


def get_compress_threshold(model: str) -> int:
    """Get compression threshold for a model."""
    return int(get_context_window(model) * settings.COMPRESS_RATIO)


def set_model_context_windows(windows: dict[str, int]) -> None:
    """Set model context windows from external source."""
    global _model_context_windows
    _model_context_windows = windows


class AIChatService:
    """Synchronous AIChat API client for RQ workers."""

    def __init__(self, timeout: float = 120.0):
        """Initialize with timeout."""
        self.timeout = timeout
        self.base_url = settings.AICHAT_BASE_URL
        self.model = settings.AICHAT_MODEL

    def chat(self, messages: list[dict], stream: bool = False) -> str:
        """Send messages to AIChat and get response."""
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": stream,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    def summarize(self, text: str) -> str:
        """Summarize text using AIChat."""
        prompt = (
            "Summarize this conversation in 200 words or less. "
            "Focus on key topics, decisions, and context needed to continue.\n\n"
            f"{text}"
        )
        return self.chat([{"role": "user", "content": prompt}])


class AsyncAIChatService:
    """Asynchronous AIChat API client for bot handlers."""

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        """Initialize with optional HTTP client."""
        self._client = http_client
        self._owns_client = http_client is None
        self.base_url = settings.AICHAT_BASE_URL
        self.model = settings.AICHAT_MODEL

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def chat(self, messages: list[dict], stream: bool = False) -> str:
        """Send messages to AIChat and get response."""
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "stream": stream,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    async def fetch_model_context_windows(self) -> dict[str, int]:
        """Fetch context windows from Venice.ai API."""
        if not settings.VENICE_API_KEY:
            logger.warning("VENICE_API_KEY not set, using default context window")
            return {}

        try:
            client = await self._get_client()
            response = await client.get(
                f"{settings.VENICE_API_BASE}/models",
                headers={"Authorization": f"Bearer {settings.VENICE_API_KEY}"},
            )
            response.raise_for_status()

            windows = {
                model["id"]: model["model_spec"]["availableContextTokens"]
                for model in response.json()["data"]
                if "model_spec" in model
                and "availableContextTokens" in model["model_spec"]
            }

            set_model_context_windows(windows)
            logger.info(f"Fetched context windows for {len(windows)} models")
            return windows

        except Exception as e:
            logger.error(f"Failed to fetch model context windows: {e}")
            return {}

    async def close(self) -> None:
        """Close HTTP client if owned."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
