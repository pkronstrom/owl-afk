"""Approval and denial handlers."""

from pyafk.core.handlers.base import CallbackContext, check_request_pending
from pyafk.utils.debug import debug_callback
from pyafk.utils.formatting import format_project_id, format_tool_summary


class ApproveHandler:
    """Handle approve callback.

    Resolves the request as approved, updates the Telegram message,
    and logs an audit event.
    """

    async def handle(self, ctx: CallbackContext) -> None:
        """Approve the request."""
        try:
            debug_callback("ApproveHandler called", request_id=ctx.target_id)
            request = await ctx.storage.get_request(ctx.target_id)
            if not request:
                debug_callback("Request not found", request_id=ctx.target_id)
                await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
                if ctx.message_id:
                    await ctx.notifier.edit_message(ctx.message_id, "Request expired")
                return

            # Skip if already resolved (handles duplicate callbacks from multiple pollers)
            if not await check_request_pending(
                request, ctx, debug_callback, ctx.target_id
            ):
                return

            debug_callback("Resolving request", request_id=ctx.target_id)
            await ctx.storage.resolve_request(
                request_id=ctx.target_id,
                status="approved",
                resolved_by="user",
            )
            debug_callback("Request resolved", request_id=ctx.target_id)

            # Note: callback already answered by poller with "" to prevent Telegram spinner
            # We just update the message content

            # Update message with approval status
            msg_id = ctx.message_id or request.telegram_msg_id
            debug_callback(
                "Editing message for approval",
                msg_id=msg_id,
                ctx_msg_id=ctx.message_id,
                request_msg_id=request.telegram_msg_id,
            )
            if msg_id:
                session = await ctx.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                tool_summary = format_tool_summary(
                    request.tool_name, request.tool_input
                )
                await ctx.notifier.edit_message(
                    msg_id,
                    f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>",
                )
            else:
                debug_callback("No message_id to edit!", request_id=ctx.target_id)

            await ctx.storage.log_audit(
                event_type="response",
                session_id=request.session_id,
                details={
                    "request_id": ctx.target_id,
                    "action": "approve",
                    "resolved_by": "user",
                },
            )
        except Exception as e:
            debug_callback(
                "Error in ApproveHandler", error=str(e)[:100], request_id=ctx.target_id
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")


class DenyHandler:
    """Handle deny callback.

    Resolves the request as denied, updates the Telegram message,
    and logs an audit event.
    """

    async def handle(self, ctx: CallbackContext) -> None:
        """Deny the request."""
        try:
            debug_callback("DenyHandler called", request_id=ctx.target_id)
            request = await ctx.storage.get_request(ctx.target_id)
            if not request:
                debug_callback("Request not found", request_id=ctx.target_id)
                await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
                if ctx.message_id:
                    await ctx.notifier.edit_message(ctx.message_id, "Request expired")
                return

            # Skip if already resolved (handles duplicate callbacks from multiple pollers)
            if not await check_request_pending(
                request, ctx, debug_callback, ctx.target_id
            ):
                return

            await ctx.storage.resolve_request(
                request_id=ctx.target_id,
                status="denied",
                resolved_by="user",
            )

            # Note: callback already answered by poller with "" to prevent Telegram spinner
            # We just update the message content

            # Update message with denial status
            msg_id = ctx.message_id or request.telegram_msg_id
            if msg_id:
                session = await ctx.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                tool_summary = format_tool_summary(
                    request.tool_name, request.tool_input
                )
                await ctx.notifier.edit_message(
                    msg_id,
                    f"<i>{project_id}</i>\n❌ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>",
                )

            await ctx.storage.log_audit(
                event_type="response",
                session_id=request.session_id,
                details={
                    "request_id": ctx.target_id,
                    "action": "deny",
                    "resolved_by": "user",
                },
            )
        except Exception as e:
            debug_callback(
                "Error in DenyHandler", error=str(e)[:100], request_id=ctx.target_id
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")
