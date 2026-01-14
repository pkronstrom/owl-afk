"""Subagent completion handlers."""

from owl.core.handlers.base import CallbackContext
from owl.core.handlers.registry import HandlerRegistry
from owl.utils.debug import debug_callback


@HandlerRegistry.register("subagent_ok")
class SubagentOkHandler:
    """Handle subagent OK button - let subagent stop normally."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Mark subagent as completed normally."""
        subagent_id = ctx.target_id
        debug_callback(
            "SubagentOkHandler called",
            subagent_id=subagent_id,
            message_id=ctx.message_id,
        )

        await ctx.storage.resolve_subagent(subagent_id, "ok")
        debug_callback("Resolved subagent", status="ok")

        await ctx.notifier.answer_callback(ctx.callback_id, "OK")

        if ctx.message_id:
            debug_callback("Editing message", message_id=ctx.message_id)
            await ctx.notifier.edit_message(
                ctx.message_id,
                "✅ Subagent finished",
            )
            debug_callback("Message edited")


@HandlerRegistry.register("subagent_continue")
class SubagentContinueHandler:
    """Handle subagent Continue button - prompt for instructions."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Prompt user for continuation instructions."""
        subagent_id = ctx.target_id
        debug_callback(
            "SubagentContinueHandler called",
            subagent_id=subagent_id,
            message_id=ctx.message_id,
        )

        await ctx.notifier.answer_callback(ctx.callback_id, "Reply with instructions")

        # Send continue prompt
        prompt_msg_id = await ctx.notifier.send_continue_prompt()
        debug_callback("Sent continue prompt", prompt_msg_id=prompt_msg_id)

        if prompt_msg_id:
            await ctx.storage.set_subagent_continue_prompt(subagent_id, prompt_msg_id)
            debug_callback("Stored continue prompt", subagent_id=subagent_id)

        # Update the original message to show waiting for instructions
        if ctx.message_id:
            await ctx.notifier.edit_message(
                ctx.message_id,
                "⏳ Waiting for instructions...",
                parse_mode=None,
            )
