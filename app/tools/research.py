"""Research tools for the research agent."""
from langchain_core.tools import tool

from app.services.llm import create_llm


@tool
def analyze_text(text: str, instruction: str) -> str:
    """Analyze or summarize text according to the given instruction."""
    llm = create_llm()
    prompt = f"{instruction}\n\nText:\n{text}"
    response = llm.invoke(prompt)
    return response.content


@tool
def compare_items(items: str, criteria: str) -> str:
    """Compare multiple items based on given criteria. Items should be separated by '---'."""
    llm = create_llm()
    prompt = (
        f"Compare the following items based on these criteria: {criteria}\n\n"
        f"Items:\n{items}\n\n"
        "Provide a structured comparison with pros/cons and a recommendation."
    )
    response = llm.invoke(prompt)
    return response.content


def get_research_tools() -> list:
    """Return all research tools."""
    return [analyze_text, compare_items]
