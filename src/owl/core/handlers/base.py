"""Base classes for callback handlers."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    from owl.core.storage import ApprovalRequest, Storage
    from owl.notifiers.base import TelegramCallbackNotifier


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


async def check_request_pending(
    request: "ApprovalRequest",
    ctx: "CallbackContext",
    debug_fn: callable,
    request_id: str,
) -> bool:
    """Check if request is still pending, handle if already resolved.

    This helper implements the idempotency check pattern used across handlers.
    It checks if a request has already been resolved and handles the case
    gracefully by answering the callback, cleaning up stale keyboard,
    and returning False.

    Args:
        request: The approval request to check
        ctx: Callback context
        debug_fn: Debug logging function (debug_callback or debug_chain)
        request_id: Request ID for logging

    Returns:
        True if request is pending and handler should continue
        False if request was already resolved (handler should return early)
    """
    if request.status != "pending":
        debug_fn(
            "Request already resolved, cleaning up stale keyboard",
            request_id=request_id,
            status=request.status,
        )
        # Clean up stale keyboard by updating message to show resolved state
        if ctx.message_id:
            from owl.core.handlers.utils import format_resolved_message
            from owl.utils.formatting import format_project_id, format_tool_summary

            session = await ctx.storage.get_session(request.session_id)
            project_id = format_project_id(
                session.project_path if session else None, request.session_id
            )
            tool_summary = format_tool_summary(request.tool_name, request.tool_input)
            message = format_resolved_message(
                approved=(request.status == "approved"),
                project_id=project_id,
                tool_name=request.tool_name,
                tool_summary=tool_summary,
            )
            await ctx.notifier.edit_message(ctx.message_id, message)
        return False
    return True


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
