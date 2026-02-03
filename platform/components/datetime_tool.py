"""Date & Time tool component — current date/time."""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.tools import tool

from components import register


@register("datetime")
def datetime_factory(node):
    """Return a LangChain tool that returns current date/time."""
    extra = node.component_config.extra_config or {}
    tz_name = extra.get("timezone")

    @tool
    def get_datetime() -> str:
        """Get the current date and time."""
        try:
            if tz_name:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(tz_name)
            else:
                tz = timezone.utc
            now = datetime.now(tz)
            return now.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception as e:
            return f"Error: {e}"

    return get_datetime
