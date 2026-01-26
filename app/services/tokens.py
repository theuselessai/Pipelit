"""Token counting utilities."""
import tiktoken

# Token encoder (cl100k_base works for most modern models)
_encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(messages: list[dict]) -> int:
    """Count tokens in a conversation."""
    total = 0
    for message in messages:
        # ~4 tokens per message for role/formatting overhead
        total += 4
        total += len(_encoding.encode(message.get("content", "")))
    return total


def count_text_tokens(text: str) -> int:
    """Count tokens in a text string."""
    return len(_encoding.encode(text))
