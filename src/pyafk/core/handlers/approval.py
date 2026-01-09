"""Approval and denial handlers."""

import json
from typing import Optional

from pyafk.core.handlers.base import CallbackContext
from pyafk.utils.debug import debug_callback
from pyafk.utils.formatting import escape_html, format_project_id


def _format_tool_summary(tool_name: str, tool_input: Optional[str]) -> str:
    """Format tool input for display.

    Extracts the most relevant field from tool input and formats it
    for display in Telegram messages.

    Args:
        tool_name: Name of the tool
        tool_input: JSON string of tool input

    Returns:
        Formatted summary string (HTML escaped)
    """
    if not tool_input:
        return ""

    try:
        data = json.loads(tool_input)
    except (json.JSONDecodeError, TypeError):
        return escape_html(str(tool_input)[:100])

    # Extract the most relevant field
    summary: str
    if "command" in data:
        summary = str(data["command"])
    elif "file_path" in data:
        summary = str(data["file_path"])
    elif "path" in data:
        summary = str(data["path"])
    elif "url" in data:
        summary = str(data["url"])
    else:
        summary = json.dumps(data)

    # Truncate if too long
    if len(summary) > 100:
        summary = summary[:100] + "..."

    return escape_html(summary)


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

            await ctx.storage.resolve_request(
                request_id=ctx.target_id,
                status="approved",
                resolved_by="user",
            )

            await ctx.notifier.answer_callback(ctx.callback_id, "Approved")

            # Update message with approval status
            msg_id = ctx.message_id or request.telegram_msg_id
            if msg_id:
                session = await ctx.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                tool_summary = _format_tool_summary(
                    request.tool_name, request.tool_input
                )
                await ctx.notifier.edit_message(
                    msg_id,
                    f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>",
                )

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

            await ctx.storage.resolve_request(
                request_id=ctx.target_id,
                status="denied",
                resolved_by="user",
            )

            await ctx.notifier.answer_callback(ctx.callback_id, "Denied")

            # Update message with denial status
            msg_id = ctx.message_id or request.telegram_msg_id
            if msg_id:
                session = await ctx.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                tool_summary = _format_tool_summary(
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
