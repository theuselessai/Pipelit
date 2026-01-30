"""HTTP request component — stub."""

from apps.workflows.components import register


@register("http_request")
def http_request_factory(node):
    def http_request_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'http_request' not yet implemented. "
            "Requires httpx integration."
        )

    return http_request_node
