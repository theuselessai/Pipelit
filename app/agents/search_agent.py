"""Web search agent using SearXNG."""
from app.agents.base import AgentWrapper, create_agent_executor
from app.tools.search import get_search_tools

SEARCH_PROMPT = """You are a web search agent. You can search the web for information using SearXNG.

Available tools:
- web_search: General web search for any topic
- web_search_news: Search specifically for news articles
- web_search_images: Search for images

Guidelines:
1. Use the appropriate search tool based on the user's request
2. For current events or recent information, prefer web_search_news
3. Summarize the most relevant results concisely
4. Include source URLs when citing information
5. If initial results are insufficient, try rephrasing the query
6. Be objective and present multiple perspectives when relevant"""


def create_search_agent() -> AgentWrapper:
    """Create a web search agent with SearXNG tools."""
    return create_agent_executor(
        tools=get_search_tools(),
        system_prompt=SEARCH_PROMPT,
        temperature=0.3,
    )
