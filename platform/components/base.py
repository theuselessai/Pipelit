"""Base protocol for workflow components."""

from __future__ import annotations

from typing import Any, Callable, Protocol


class ComponentFactory(Protocol):
    """Protocol for component factories.

    A factory receives a WorkflowNode and returns a LangGraph node function
    that takes WorkflowState and returns a state update dict.
    """

    def __call__(self, node: Any) -> Callable[[dict], dict]: ...
