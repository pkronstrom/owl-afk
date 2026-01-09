"""Rule management handlers."""

from pyafk.core.handlers.base import CallbackContext
from pyafk.utils.debug import debug_callback


class CancelRuleHandler:
    """Cancel rule selection and restore original keyboard."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Cancel rule selection and restore approval buttons."""
        request_id = ctx.target_id
        debug_callback("CancelRuleHandler called", request_id=request_id)

        request = await ctx.storage.get_request(request_id)
        if not request:
            await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
            if ctx.message_id:
                await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
            return

        await ctx.notifier.answer_callback(ctx.callback_id, "Cancelled")

        # Restore original message with approval keyboard
        if ctx.message_id:
            await ctx.notifier.restore_approval_keyboard(
                ctx.message_id,
                request_id,
                request.session_id,
                request.tool_name,
                request.tool_input,
            )
