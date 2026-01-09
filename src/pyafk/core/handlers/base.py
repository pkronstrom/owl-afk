"""Base classes for callback handlers."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    from pyafk.core.storage import Storage
    from pyafk.notifiers.base import TelegramCallbackNotifier


@dataclass
class CallbackContext:
    """Context passed to callback handlers.

    This dataclass carries all the information a handler needs to process
    a Telegram callback query.

    The notifier field uses TelegramCallbackNotifier protocol, which defines
    the Telegram-specific methods needed by handlers (answer_callback,
    edit_message_with_rule_keyboard, update_chain_progress, etc.).

    Attributes:
        target_id: The target identifier from callback data (request_id, session_id, etc.)
        callback_id: Telegram callback query ID for answering
        message_id: Telegram message ID for editing (None if not available)
        storage: Database storage instance
        notifier: Notifier implementing TelegramCallbackNotifier protocol
        original_text: Original message text (for restoration if needed)
    """

    target_id: str
    callback_id: str
    message_id: Optional[int]
    storage: "Storage"
    notifier: "TelegramCallbackNotifier"
    original_text: str = field(default="")


class CallbackHandler(Protocol):
    """Protocol for callback handlers.

    Implementations handle specific callback actions (approve, deny, add_rule, etc.)
    Each handler should be focused on a single action type.

    Example:
        class ApproveHandler:
            async def handle(self, ctx: CallbackContext) -> None:
                request = await ctx.storage.get_request(ctx.target_id)
                await ctx.storage.resolve_request(ctx.target_id, status="approved")
                await ctx.notifier.answer_callback(ctx.callback_id, "Approved")
    """

    async def handle(self, ctx: CallbackContext) -> None:
        """Handle the callback.

        Args:
            ctx: Callback context with all necessary dependencies

        Implementations should:
        1. Validate the request/target exists
        2. Perform the action
        3. Update storage
        4. Send appropriate response via notifier
        5. Handle errors gracefully
        """
        ...
