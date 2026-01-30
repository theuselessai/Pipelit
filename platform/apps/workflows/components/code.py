"""Code execution component — stub."""

from apps.workflows.components import register


@register("code")
def code_factory(node):
    def code_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'code' not yet implemented. "
            "Requires sandbox/exec infrastructure."
        )

    return code_node
