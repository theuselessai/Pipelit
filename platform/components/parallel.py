"""Parallel execution component — stub."""

from components import register


@register("parallel")
def parallel_factory(node):
    def parallel_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'parallel' not yet implemented. "
            "Requires ThreadPoolExecutor and branch management."
        )

    return parallel_node
