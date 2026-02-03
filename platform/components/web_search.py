"""Web Search tool component — SearXNG search."""

from __future__ import annotations

import httpx
from langchain_core.tools import tool

from components import register


@register("web_search")
def web_search_factory(node):
    """Return a LangChain tool that searches via SearXNG."""
    extra = node.component_config.extra_config or {}
    searxng_url = extra.get("searxng_url", "http://localhost:8888")

    @tool
    def web_search(query: str) -> str:
        """Search the web using SearXNG. Returns top results."""
        try:
            resp = httpx.get(
                f"{searxng_url.rstrip('/')}/search",
                params={"q": query, "format": "json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])[:5]
            if not results:
                return "No results found."
            lines = []
            for r in results:
                lines.append(f"- {r.get('title', '')}\n  {r.get('url', '')}\n  {r.get('content', '')[:200]}")
            return "\n\n".join(lines)
        except Exception as e:
            return f"Search error: {e}"

    return web_search
