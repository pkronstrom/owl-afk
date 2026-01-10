"""Feedback/message handlers for deny with message."""

from pyafk.core.handlers.base import CallbackContext
from pyafk.core.handlers.registry import HandlerRegistry
from pyafk.utils.debug import debug_callback


@HandlerRegistry.register("deny_msg")
class DenyWithMessageHandler:
    """Handle deny with message button - prompt for feedback."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Prompt user for denial feedback."""
        request_id = ctx.target_id
        debug_callback("DenyWithMessageHandler called", request_id=request_id)

        request = await ctx.storage.get_request(request_id)
        if not request:
            await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
            if ctx.message_id:
                await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
            return

        # Send feedback prompt
        prompt_msg_id = await ctx.notifier.send_feedback_prompt(request.tool_name)
        if prompt_msg_id:
            await ctx.storage.set_pending_feedback(prompt_msg_id, request_id)

        await ctx.notifier.answer_callback(ctx.callback_id, "Reply with feedback")
