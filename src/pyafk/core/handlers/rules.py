"""Rule management handlers."""

from pyafk.core.handlers.base import CallbackContext
from pyafk.utils.debug import debug_callback
from pyafk.utils.formatting import format_project_id, format_tool_summary
from pyafk.utils.pattern_generator import generate_rule_patterns


class AddRuleMenuHandler:
    """Show rule pattern options menu."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Show rule pattern options inline."""
        request_id = ctx.target_id
        debug_callback("AddRuleMenuHandler called", request_id=request_id)

        request = await ctx.storage.get_request(request_id)
        if not request:
            await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
            if ctx.message_id:
                await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
            return

        # Get session for project_path
        session = await ctx.storage.get_session(request.session_id)
        project_path = session.project_path if session else None

        # Generate pattern options
        patterns = generate_rule_patterns(
            request.tool_name, request.tool_input, project_path
        )
        if not patterns:
            await ctx.notifier.answer_callback(ctx.callback_id, "No patterns available")
            return

        await ctx.notifier.answer_callback(ctx.callback_id, "Choose pattern")

        # Edit message inline with pattern options
        if ctx.message_id:
            # Strip any previous rule prompt text for clean display
            base_text = (
                ctx.original_text.split("\n\n📝")[0]
                if "\n\n📝" in ctx.original_text
                else ctx.original_text
            )
            await ctx.notifier.edit_message_with_rule_keyboard(
                ctx.message_id, base_text, request_id, patterns
            )


class AddRulePatternHandler:
    """Handle rule pattern selection and create the rule."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Create rule from selected pattern and approve request."""
        # Parse target_id: request_id:pattern_index
        parts = ctx.target_id.rsplit(":", 1)
        if len(parts) != 2:
            debug_callback("Invalid add_rule_pattern format", target_id=ctx.target_id)
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid format")
            return

        request_id, idx_str = parts
        try:
            pattern_idx = int(idx_str)
        except ValueError:
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid pattern index")
            return

        debug_callback(
            "AddRulePatternHandler called",
            request_id=request_id,
            pattern_idx=pattern_idx,
        )

        try:
            request = await ctx.storage.get_request(request_id)
            if not request:
                await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
                if ctx.message_id:
                    await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
                return

            # Get session for project_path
            session = await ctx.storage.get_session(request.session_id)
            project_path = session.project_path if session else None

            # Get the selected pattern
            patterns = generate_rule_patterns(
                request.tool_name, request.tool_input, project_path
            )
            if not patterns:
                await ctx.notifier.answer_callback(
                    ctx.callback_id, "No patterns available"
                )
                return

            pattern, label = (
                patterns[pattern_idx] if pattern_idx < len(patterns) else patterns[0]
            )

            # Add the rule
            from pyafk.core.rules import RulesEngine

            engine = RulesEngine(ctx.storage)
            await engine.add_rule(
                pattern, "approve", priority=0, created_via="telegram"
            )

            # Also approve this request
            await ctx.storage.resolve_request(
                request_id=request_id,
                status="approved",
                resolved_by="user:add_rule",
            )

            # Update the message
            if ctx.message_id:
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                tool_summary = format_tool_summary(
                    request.tool_name, request.tool_input
                )
                await ctx.notifier.edit_message(
                    ctx.message_id,
                    f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> "
                    f"<code>{tool_summary}</code>\n📝 Always: {label}",
                )

            await ctx.notifier.answer_callback(ctx.callback_id, "Always rule added")
        except Exception as e:
            debug_callback(
                "Error in AddRulePatternHandler",
                error=str(e)[:100],
                request_id=request_id,
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")


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
