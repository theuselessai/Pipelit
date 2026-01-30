"""Subworkflow component — stub."""

from apps.workflows.components import register


@register("workflow")
def subworkflow_factory(node):
    def subworkflow_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'workflow' (subworkflow) not yet implemented. "
            "Requires recursive builder invocation."
        )

    return subworkflow_node
