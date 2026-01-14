"""Handler dispatcher for routing callbacks to appropriate handlers."""

from typing import TYPE_CHECKING, Optional

from owl.core.handlers.base import CallbackContext
from owl.core.handlers.registry import HandlerRegistry
from owl.utils.debug import debug_callback

if TYPE_CHECKING:
    from owl.core.storage import Storage
    from owl.notifiers.base import TelegramCallbackNotifier


def _register_handlers() -> None:
    """Import handler modules to trigger registration.

    This function ensures all handler modules are imported, which causes
    the @HandlerRegistry.register() decorators to execute and register
    each handler with the registry.
    """
    # Import all handler modules to trigger registration
    # The imports are not used directly - they just run the decorators
    from owl.core.handlers import (  # noqa: F401
        approval,
        batch,
        chain,
        feedback,
        rules,
        stop,
        subagent,
    )


class HandlerDispatcher:
    """Routes callback data to appropriate handlers.

    This class dispatches Telegram callback queries to the appropriate
    handler based on the action type. Handlers are discovered via the
    HandlerRegistry, which uses decorator-based self-registration.

    Attributes:
        storage: Database storage instance
        notifier: Notifier implementing TelegramCallbackNotifier protocol

    Example:
        dispatcher = HandlerDispatcher(storage, notifier)
        await dispatcher.dispatch("approve:req123", "cb456", 789)
    """

    def __init__(
        self,
        storage: "Storage",
        notifier: "TelegramCallbackNotifier",
    ) -> None:
        self.storage = storage
        self.notifier = notifier

        # Ensure all handlers are registered
        _register_handlers()

    async def dispatch(
        self,
        callback_data: str,
        callback_id: str,
        message_id: Optional[int],
        original_text: str = "",
    ) -> None:
        """Dispatch callback to appropriate handler.

        Parses the callback_data to extract the action and target_id,
        then routes to the registered handler for that action.

        Args:
            callback_data: The callback_data from Telegram button (e.g., "approve:req123")
            callback_id: Telegram callback query ID
            message_id: Telegram message ID
            original_text: Original message text for restoration
        """
        if ":" not in callback_data:
            debug_callback("Invalid callback data format", data=callback_data)
            return

        # Split only on first colon to preserve compound target IDs
        action, target_id = callback_data.split(":", 1)
        debug_callback("Dispatching callback", action=action, target_id=target_id[:20])

        handler = HandlerRegistry.create(action)
        if handler is None:
            debug_callback("No handler for action", action=action)
            return

        ctx = CallbackContext(
            target_id=target_id,
            callback_id=callback_id,
            message_id=message_id,
            storage=self.storage,
            notifier=self.notifier,
            original_text=original_text,
        )

        await handler.handle(ctx)

    def register(self, action: str, handler_cls: type) -> None:
        """Register a handler class for an action.

        Use this to add custom handlers or override default handlers at runtime.
        For most cases, use the @HandlerRegistry.register() decorator instead.

        Args:
            action: The action string (e.g., "approve", "deny", "add_rule")
            handler_cls: Handler class implementing CallbackHandler protocol
        """
        HandlerRegistry._handlers[action] = handler_cls
