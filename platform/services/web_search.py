"""Web search resolution service — auto-detects best search backend for agents."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def is_anthropic_native(credential) -> bool:
    """True Anthropic provider (not a proxy like minimax)."""
    return (
        credential.provider_type == "anthropic"
        and (not credential.base_url or "anthropic.com" in credential.base_url)
    )


def resolve_web_search_tools(credential, db, *, use_native_search: bool = False) -> tuple[list[dict], list]:
    """Resolve web search tools for an agent node.

    Priority:
    1. Anthropic native — explicit opt-in overrides SearXNG
    2. SearXNG — default for all providers (including Anthropic)
    3. None — no search available

    Returns (native_tools, langchain_tools):
        native_tools: dicts to inject into LLM bind_tools (server-side execution)
        langchain_tools: @tool functions for client-side execution
    """
    # Priority 1: Anthropic native (explicit opt-in overrides SearXNG)
    if use_native_search and is_anthropic_native(credential):
        logger.info("Web search: using Anthropic native search (opted in)")
        return [{"type": "web_search_20250305", "name": "web_search"}], []

    # Priority 2: SearXNG (default for everyone)
    searxng_cred = _find_searxng_credential(db)
    if searxng_cred:
        logger.info("Web search: using SearXNG")
        return [], [_create_searxng_tool(searxng_cred)]

    logger.warning("Web search: no search backend available")
    return [], []


def _find_searxng_credential(db):
    """Find SearXNG tool credential, preferring the one marked is_preferred."""
    from models.credential import BaseCredential, ToolCredential

    base = (
        db.query(BaseCredential)
        .join(ToolCredential)
        .filter(ToolCredential.tool_type == "searxng")
        .order_by(ToolCredential.is_preferred.desc(), BaseCredential.id)
        .first()
    )
    if base:
        logger.info(
            "SearXNG credential: %s (id=%d, preferred=%s)",
            base.name, base.id, base.tool_credential.is_preferred,
        )
    return base.tool_credential if base else None


def _create_searxng_tool(searxng_cred):
    """Create a LangChain @tool that calls SearXNG."""
    from langchain_core.tools import tool
    import httpx

    url = (searxng_cred.config or {}).get("url", "").rstrip("/")

    @tool
    def web_search(query: str) -> str:
        """Search the web for current information."""
        try:
            resp = httpx.get(
                f"{url}/search",
                params={"q": query, "format": "json"},
                timeout=15,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("SearXNG web search error: %s", e)
            return "Web search unavailable. Try answering from your knowledge."
        results = resp.json().get("results", [])[:5]
        return "\n\n".join(
            f"**{r.get('title', '')}**\n{r.get('content', '')}\nURL: {r.get('url', '')}"
            for r in results
        ) or "No results found."

    return web_search
