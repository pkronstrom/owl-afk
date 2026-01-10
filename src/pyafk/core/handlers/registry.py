"""Handler registry for callback dispatching.

This module provides a decorator-based registry for callback handlers,
enabling self-registration of handlers with their action strings.

Example:
    @HandlerRegistry.register("approve")
    class ApproveHandler:
        async def handle(self, ctx: CallbackContext) -> None:
            ...

    # Later, get the handler:
    handler = HandlerRegistry.create("approve")
    await handler.handle(ctx)
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyafk.core.handlers.base import CallbackHandler


class HandlerRegistry:
    """Registry for callback handlers.

    Uses class-level storage to allow decorators to register handlers
    at import time. Handlers are stored as classes and instantiated
    on demand.
    """

    _handlers: dict[str, type["CallbackHandler"]] = {}

    @classmethod
    def register(cls, action: str):
        """Decorator to register a handler for an action.

        Args:
            action: The action string (e.g., "approve", "deny")

        Returns:
            Decorator function that registers the handler class

        Example:
            @HandlerRegistry.register("approve")
            class ApproveHandler:
                async def handle(self, ctx): ...
        """

        def decorator(handler_cls: type["CallbackHandler"]):
            cls._handlers[action] = handler_cls
            return handler_cls

        return decorator

    @classmethod
    def get(cls, action: str) -> Optional[type["CallbackHandler"]]:
        """Get handler class for action.

        Args:
            action: The action string

        Returns:
            Handler class or None if not registered
        """
        return cls._handlers.get(action)

    @classmethod
    def create(cls, action: str) -> Optional["CallbackHandler"]:
        """Create handler instance for action.

        Args:
            action: The action string

        Returns:
            Handler instance or None if not registered
        """
        handler_cls = cls.get(action)
        return handler_cls() if handler_cls else None

    @classmethod
    def actions(cls) -> list[str]:
        """Get list of registered action names.

        Returns:
            List of registered action strings
        """
        return list(cls._handlers.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered handlers.

        Primarily used for testing.
        """
        cls._handlers.clear()
