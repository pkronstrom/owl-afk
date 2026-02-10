"""Batch approval handlers for multiple requests."""

from owl.core.handlers.base import CallbackContext
from owl.core.handlers.registry import HandlerRegistry
from owl.utils.debug import debug_callback
from owl.utils.formatting import format_project_id, format_tool_call_html, format_tool_summary


@HandlerRegistry.register("approve_all")
class ApproveAllHandler:
    """Approve all pending requests for a session and tool type."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Approve all matching requests and add rule for future ones.

        Target ID format: session_id or session_id:tool_name
        """
        # Parse target_id: session_id or session_id:tool_name
        parts = ctx.target_id.split(":", 1)
        session_id = parts[0]
        tool_name = parts[1] if len(parts) > 1 else None

        debug_callback(
            "ApproveAllHandler called",
            session_id=session_id,
            tool_name=tool_name,
        )

        try:
            pending = await ctx.storage.get_pending_requests()
            debug_callback(
                "Found pending requests",
                count=len(pending),
                pending_session_ids=[r.session_id for r in pending],
            )

            # Filter by session and tool type
            to_approve = [
                r
                for r in pending
                if r.session_id == session_id
                and (tool_name is None or r.tool_name == tool_name)
            ]
            debug_callback("Filtered to_approve", count=len(to_approve))

            for request in to_approve:
                debug_callback(
                    "Approving request", request_id=request.id, tool=request.tool_name
                )
                await ctx.storage.resolve_request(
                    request_id=request.id,
                    status="approved",
                    resolved_by="user:approve_all",
                )
                # Update the Telegram message
                if request.telegram_msg_id:
                    session = await ctx.storage.get_session(request.session_id)
                    project_id = format_project_id(
                        session.project_path if session else None, request.session_id
                    )
                    tool_summary = format_tool_summary(
                        request.tool_name, request.tool_input
                    )
                    await ctx.notifier.edit_message(
                        request.telegram_msg_id,
                        f"<i>{project_id}</i>\n"
                        f"{format_tool_call_html(request.tool_name, tool_summary, prefix='\u2713 ')}",
                    )
                debug_callback("Request approved", request_id=request.id)

            # Add a rule to auto-approve future requests of this tool type
            rule_added = False
            if tool_name:
                from owl.core.rules import RulesEngine

                pattern = f"{tool_name}(*)"
                engine = RulesEngine(ctx.storage)
                await engine.add_rule(
                    pattern, "approve", priority=0, created_via="telegram:approve_all"
                )
                debug_callback("Added rule for future requests", pattern=pattern)
                rule_added = True

            tool_label = tool_name or "all"
            debug_callback(
                "Approve all complete",
                approved=len(to_approve),
                tool=tool_label,
                rule_added=rule_added,
            )

            if rule_added:
                await ctx.notifier.answer_callback(
                    ctx.callback_id,
                    f"Approved {len(to_approve)} + added rule for all {tool_name}",
                )
            else:
                await ctx.notifier.answer_callback(
                    ctx.callback_id,
                    f"Approved {len(to_approve)} {tool_label}",
                )
        except Exception as e:
            debug_callback(
                "Error in ApproveAllHandler",
                error=str(e)[:100],
                session_id=session_id,
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")
