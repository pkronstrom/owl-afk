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

        Target ID format: request_id (looks up session_id and tool_name from storage)
        """
        request_id = ctx.target_id

        # Look up the originating request to get session_id and tool_name
        source_request = await ctx.storage.get_request(request_id)
        if not source_request:
            debug_callback("Source request not found", request_id=request_id)
            await ctx.notifier.answer_callback(ctx.callback_id, "Request expired")
            return

        session_id = source_request.session_id
        tool_name = source_request.tool_name

        debug_callback(
            "ApproveAllHandler called",
            request_id=request_id,
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


def _extract_mcp_server_prefix(tool_name: str) -> tuple[str, str] | None:
    """Extract MCP server prefix and pretty label from tool name.

    Returns (prefix, label) e.g. ("mcp__figma__", "Figma") or None.
    """
    if not tool_name.startswith("mcp__"):
        return None
    parts = tool_name.split("__", 2)
    if len(parts) < 3:
        return None
    server_name = parts[1]
    prefix = f"mcp__{server_name}__"
    label = server_name.replace("_", " ").title()
    return prefix, label


@HandlerRegistry.register("mcp_allow_all")
class McpAllowAllHandler:
    """Approve all pending requests from an MCP server and add wildcard rule."""

    async def handle(self, ctx: CallbackContext) -> None:
        request_id = ctx.target_id

        source_request = await ctx.storage.get_request(request_id)
        if not source_request:
            debug_callback("Source request not found", request_id=request_id)
            await ctx.notifier.answer_callback(ctx.callback_id, "Request expired")
            return

        session_id = source_request.session_id
        tool_name = source_request.tool_name
        mcp_info = _extract_mcp_server_prefix(tool_name) if tool_name else None

        if not mcp_info:
            debug_callback("Not an MCP tool", tool_name=tool_name)
            await ctx.notifier.answer_callback(ctx.callback_id, "Not an MCP tool")
            return

        prefix, label = mcp_info
        debug_callback(
            "McpAllowAllHandler called",
            request_id=request_id,
            session_id=session_id,
            prefix=prefix,
            label=label,
        )

        try:
            pending = await ctx.storage.get_pending_requests()

            # Approve all pending requests from this MCP server (any session)
            to_approve = [
                r for r in pending
                if r.tool_name and r.tool_name.startswith(prefix)
            ]
            debug_callback("Filtered MCP to_approve", count=len(to_approve), prefix=prefix)

            for request in to_approve:
                debug_callback(
                    "Approving request", request_id=request.id, tool=request.tool_name
                )
                await ctx.storage.resolve_request(
                    request_id=request.id,
                    status="approved",
                    resolved_by=f"user:mcp_allow_all:{prefix}",
                )
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

            # Add wildcard rule for all tools from this MCP server
            from owl.core.rules import RulesEngine

            pattern = f"{prefix}*(*)"
            engine = RulesEngine(ctx.storage)
            await engine.add_rule(
                pattern, "approve", priority=0, created_via=f"telegram:mcp_allow_all"
            )
            debug_callback("Added MCP server rule", pattern=pattern)

            debug_callback(
                "MCP allow all complete",
                approved=len(to_approve),
                label=label,
            )
            await ctx.notifier.answer_callback(
                ctx.callback_id,
                f"Approved {len(to_approve)} + rule for all {label} tools",
            )
        except Exception as e:
            debug_callback(
                "Error in McpAllowAllHandler",
                error=str(e)[:100],
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")
