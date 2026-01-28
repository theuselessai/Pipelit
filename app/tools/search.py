"""Web search tools using SearXNG."""
import logging
from typing import Optional

import httpx
from langchain_core.tools import tool

from app.config import settings

logger = logging.getLogger(__name__)


@tool
def web_search(query: str, num_results: int = 10) -> str:
    """
    Search the web using SearXNG.

    Args:
        query: The search query
        num_results: Number of results to return (default 10)

    Returns:
        Formatted search results with title, URL, and snippet
    """
    try:
        url = f"{settings.SEARXNG_BASE_URL}/search"
        params = {
            "q": query,
            "format": "json",
            "pageno": 1,
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])[:num_results]

        if not results:
            return f"No results found for: {query}"

        output_lines = [f"Search results for: {query}\n"]
        for i, result in enumerate(results, 1):
            title = result.get("title", "No title")
            url = result.get("url", "")
            snippet = result.get("content", "No description")
            output_lines.append(f"{i}. {title}")
            output_lines.append(f"   URL: {url}")
            output_lines.append(f"   {snippet}\n")

        return "\n".join(output_lines)

    except httpx.HTTPError as e:
        logger.error(f"SearXNG HTTP error: {e}")
        return f"Search failed: HTTP error - {str(e)}"
    except Exception as e:
        logger.error(f"SearXNG error: {e}")
        return f"Search failed: {str(e)}"


@tool
def web_search_news(query: str, num_results: int = 10) -> str:
    """
    Search for news articles using SearXNG.

    Args:
        query: The search query
        num_results: Number of results to return (default 10)

    Returns:
        Formatted news results with title, URL, date, and snippet
    """
    try:
        url = f"{settings.SEARXNG_BASE_URL}/search"
        params = {
            "q": query,
            "format": "json",
            "categories": "news",
            "pageno": 1,
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])[:num_results]

        if not results:
            return f"No news found for: {query}"

        output_lines = [f"News results for: {query}\n"]
        for i, result in enumerate(results, 1):
            title = result.get("title", "No title")
            url = result.get("url", "")
            snippet = result.get("content", "No description")
            published = result.get("publishedDate", "")
            output_lines.append(f"{i}. {title}")
            if published:
                output_lines.append(f"   Date: {published}")
            output_lines.append(f"   URL: {url}")
            output_lines.append(f"   {snippet}\n")

        return "\n".join(output_lines)

    except httpx.HTTPError as e:
        logger.error(f"SearXNG HTTP error: {e}")
        return f"News search failed: HTTP error - {str(e)}"
    except Exception as e:
        logger.error(f"SearXNG error: {e}")
        return f"News search failed: {str(e)}"


@tool
def web_search_images(query: str, num_results: int = 5) -> str:
    """
    Search for images using SearXNG.

    Args:
        query: The search query
        num_results: Number of results to return (default 5)

    Returns:
        Formatted image results with title and URL
    """
    try:
        url = f"{settings.SEARXNG_BASE_URL}/search"
        params = {
            "q": query,
            "format": "json",
            "categories": "images",
            "pageno": 1,
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])[:num_results]

        if not results:
            return f"No images found for: {query}"

        output_lines = [f"Image results for: {query}\n"]
        for i, result in enumerate(results, 1):
            title = result.get("title", "No title")
            img_url = result.get("img_src", result.get("url", ""))
            source = result.get("source", "")
            output_lines.append(f"{i}. {title}")
            if source:
                output_lines.append(f"   Source: {source}")
            output_lines.append(f"   Image URL: {img_url}\n")

        return "\n".join(output_lines)

    except httpx.HTTPError as e:
        logger.error(f"SearXNG HTTP error: {e}")
        return f"Image search failed: HTTP error - {str(e)}"
    except Exception as e:
        logger.error(f"SearXNG error: {e}")
        return f"Image search failed: {str(e)}"


def get_search_tools() -> list:
    """Return all search tools."""
    return [web_search, web_search_news, web_search_images]
