"""Trigger components — pass-through nodes for all trigger types."""

from components import register


def _make_trigger_passthrough(component_type: str):
    """Factory for trigger pass-through components."""

    @register(component_type)
    def factory(config):
        def run(state: dict) -> dict:
            return state
        return run

    return factory


for _ct in (
    "trigger_telegram",
    "trigger_schedule",
    "trigger_manual",
    "trigger_workflow",
    "trigger_error",
    "trigger_chat",
):
    _make_trigger_passthrough(_ct)
