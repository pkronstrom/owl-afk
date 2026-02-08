"""Stop/session end handlers."""

from owl.core.handlers.base import CallbackContext
from owl.core.handlers.registry import HandlerRegistry
from owl.utils.debug import debug_callback


@HandlerRegistry.register("stop_ok")
class StopOkHandler:
    """Handle stop OK button - let Claude stop normally."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Mark session stop as acknowledged."""
        session_id = ctx.target_id
        debug_callback("StopOkHandler called", session_id=session_id)

        await ctx.storage.resolve_stop(session_id, "ok")
        await ctx.notifier.answer_callback(ctx.callback_id, "OK")

        if ctx.message_id:
            await ctx.notifier.edit_message(
                ctx.message_id,
                "✓ Session ended",
            )


@HandlerRegistry.register("stop_comment")
class StopCommentHandler:
    """Handle stop Comment button - prompt for message to Claude."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Prompt user for a message to send to Claude."""
        session_id = ctx.target_id
        debug_callback("StopCommentHandler called", session_id=session_id)

        await ctx.notifier.answer_callback(ctx.callback_id, "Reply with your message")

        # Send continue prompt
        prompt_msg_id = await ctx.notifier.send_continue_prompt()
        if prompt_msg_id:
            await ctx.storage.set_stop_comment_prompt(session_id, prompt_msg_id)

        # Update the original message
        if ctx.message_id:
            await ctx.notifier.edit_message(
                ctx.message_id,
                "⏳ Waiting for your message...",
                parse_mode=None,
            )
