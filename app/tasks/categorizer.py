"""Categorizer task: classifies messages via LangChain LLM, then enqueues execution."""

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.gateway.confirmation import ConfirmationHandler
from app.gateway.executor import Executor
from app.gateway.router import ExecutionStrategy, RouteResult, parse_categorizer_output
from app.services.llm import create_llm
from app.services.telegram import send_message

logger = logging.getLogger(__name__)

CATEGORIZER_SYSTEM_PROMPT = """You are a message categorizer. Classify the user's message into one of the available execution strategies and return ONLY valid JSON.

## Available Strategies

- **AGENT**: Tasks that require tool use — running commands, browsing the web, reading files, etc.
- **DYNAMIC_PLAN**: Complex multi-step tasks requiring planning and multiple agents
- **CHAT**: Regular conversation, questions, greetings, opinions, or anything that doesn't need tools

## Available Targets

### Agents (strategy: "agent")
- `system_agent` — ANY request to run a command, check disk/memory/network, read/write files, list directories, check processes, or interact with the operating system. If the user asks you to "run", "execute", "check", "show", "list", or do anything that requires shell access, use this agent.
- `browser_agent` — Web browsing: navigate to URLs, take screenshots, click, type, fill forms, scroll pages.
- `search_agent` — Web search: search the internet for information, news, images. Use for queries like "search for", "find information about", "what's the latest news on", "look up".
- `research_agent` — Text analysis, comparison, and summarization tasks that don't need shell, browser, or web search.

### Dynamic Plan (strategy: "dynamic")
Use when the task requires multiple steps across different agents, research + comparison, or sequential actions with "then/and/finally".

### Chat (strategy: "chat")
Target is always `chat`. Use for regular conversation, questions, greetings, or anything not matching above.

## Important Rules

- When in doubt between "chat" and "agent", prefer "agent" if the user is asking you to DO something (run a command, check something, browse a site).
- Phrases like "can you run X", "run X", "execute X", "check X", "what's my IP" are ALL system_agent tasks, not chat.
- Only use "chat" for genuine conversation where no tools are needed.
- You may receive recent conversation history for context. Use it to understand follow-up messages. For example, if the previous exchange involved a system_agent task and the user says "yes run it", "do it", "yes please execute that", route to the same agent — not to chat.
- Short acknowledgments like "good", "great", "ok", "thanks", "cool", "nice" are ALWAYS chat — they are not requesting any action.

## Confirmation Rules

Set `requires_confirmation` to `true` when the message involves any of:
- Buying, ordering, purchasing, checkout, payment
- Deleting, removing files or data
- Sending, submitting, posting content externally
- Installing or uninstalling software
- Rebooting, shutting down, restarting systems

## Output Format

Return ONLY a JSON object, no markdown fences, no explanation:

{"strategy": "agent", "target": "system_agent", "requires_confirmation": false}"""

STRATEGY_DESCRIPTIONS = {
    ExecutionStrategy.AGENT: "Agent task",
    ExecutionStrategy.DYNAMIC_PLAN: "Multi-step plan",
    ExecutionStrategy.CHAT: "Conversation",
}


def categorize_and_execute(
    message: str,
    user_id: int,
    chat_id: int,
    message_id: int,
    session_id: str,
) -> None:
    """
    Classify a message using LangChain LLM, then enqueue the real task.

    Called as an RQ task from the handler.
    """
    raw_output = _run_categorizer(message, user_id)
    route = parse_categorizer_output(raw_output, message)

    logger.info(
        f"Categorized to {route.strategy.value}: {route.target} "
        f"(confirm={route.requires_confirmation})"
    )

    # Handle confirmation
    if route.requires_confirmation:
        handler = ConfirmationHandler(
            timeout_minutes=settings.CONFIRMATION_TIMEOUT_MINUTES
        )
        task_id = handler.create_pending_task(
            user_id=user_id,
            chat_id=chat_id,
            message=message,
            target=route.target,
            strategy=route.strategy.value,
        )
        desc = STRATEGY_DESCRIPTIONS.get(route.strategy, "Task")
        msg = handler.format_confirmation_message(
            handler.get_pending_task(task_id),
            f"{desc}: {route.target}",
        )
        send_message(chat_id, msg, reply_to_message_id=message_id)
        return

    # Execute the routed task
    executor = Executor()
    job_id = executor.execute(
        route=route,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        session_id=session_id,
    )

    # Send status for non-chat routes
    if route.strategy != ExecutionStrategy.CHAT:
        status_msg = {
            ExecutionStrategy.AGENT: f"Processing with {route.target}",
            ExecutionStrategy.DYNAMIC_PLAN: "Creating execution plan...",
        }
        send_message(
            chat_id,
            f"{status_msg.get(route.strategy, 'Processing...')}\nJob: {job_id[:8]}",
            reply_to_message_id=message_id,
        )

    logger.info(f"Enqueued job {job_id} for user {user_id}")


def _run_categorizer(message: str, user_id: int) -> str:
    """Run LangChain-based categorizer and return raw output."""
    try:
        llm = create_llm(
            model=settings.categorizer_model,
            temperature=0,
        )

        # Load recent conversation history for context-aware routing
        from app.db.repository import get_repository
        repo = get_repository()
        conversation = repo.get_conversation(user_id)

        # Include last few exchanges so the categorizer understands follow-ups
        recent = conversation[-6:] if conversation else []
        context_lines = []
        for msg in recent:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")[:200]
            context_lines.append(f"{role}: {content}")

        if context_lines:
            contextualized_message = (
                "Recent conversation:\n"
                + "\n".join(context_lines)
                + f"\n\nNew message to classify:\n{message}"
            )
        else:
            contextualized_message = message

        response = llm.invoke([
            SystemMessage(content=CATEGORIZER_SYSTEM_PROMPT),
            HumanMessage(content=contextualized_message),
        ])
        return response.content.strip()
    except Exception as e:
        logger.error(f"LLM categorizer error: {e}")
        return ""
