"""Control flow components — loop, wait, error_handler."""

from components import register


@register("loop")
def loop_factory(node):
    """Extract array from source node output for iteration."""
    extra = node.component_config.extra_config
    source_node = extra.get("source_node")
    field = extra.get("field", "")

    def loop_node(state: dict) -> dict:
        data = None
        if source_node:
            source_output = state.get("node_outputs", {}).get(source_node, {})
            if field and isinstance(source_output, dict):
                data = source_output.get(field)
            else:
                data = source_output
        if not isinstance(data, list):
            data = [data] if data is not None else []

        return {"_loop": {"items": data}, "items": data, "results": []}

    return loop_node


@register("wait")
def wait_factory(node):
    """Delay downstream execution by a specified duration."""
    extra = node.component_config.extra_config
    duration = float(extra.get("duration", 0))
    unit = extra.get("unit", "seconds")
    multipliers = {"seconds": 1, "minutes": 60, "hours": 3600}
    delay = duration * multipliers.get(unit, 1)

    def wait_node(state: dict) -> dict:
        return {"_delay_seconds": delay, "output": f"Waited {duration} {unit}"}

    return wait_node


@register("error_handler")
def error_handler_factory(node):
    def error_handler_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'error_handler' not yet implemented. "
            "Requires try/catch wrapper logic."
        )

    return error_handler_node
