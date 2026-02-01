"""Control flow components — loop, wait, error_handler — stubs."""

from components import register


@register("loop")
def loop_factory(node):
    def loop_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'loop' not yet implemented. "
            "Requires iteration state management."
        )

    return loop_node


@register("wait")
def wait_factory(node):
    def wait_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'wait' not yet implemented. "
            "Requires timer/scheduler integration."
        )

    return wait_node


@register("error_handler")
def error_handler_factory(node):
    def error_handler_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'error_handler' not yet implemented. "
            "Requires try/catch wrapper logic."
        )

    return error_handler_node
