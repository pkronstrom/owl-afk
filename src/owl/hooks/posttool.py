"""PostToolUse hook handler - delivers pending messages and tool results."""

import json
from pathlib import Path
from typing import Optional

from owl.core.storage import Storage
from owl.hooks.response import make_hook_response
from owl.utils.config import Config, get_owl_dir
from owl.utils.debug import debug


async def handle_posttool_use(
    hook_input: dict,
    owl_dir: Optional[Path] = None,
) -> dict:
    """Handle PostToolUse hook - deliver pending messages and optionally show results."""
    import sys

    if owl_dir is None:
        owl_dir = get_owl_dir()

    config = Config(owl_dir)
    project_path = hook_input.get("cwd")

    if not config.is_enabled_for_project(project_path):
        return {}

    storage = Storage(config.db_path)

    try:
        await storage.connect()

        session_id = hook_input.get("session_id", "unknown")
        debug("posttool", f"session_id={session_id}")

        # Tool results: edit the approval message with output
        if config.tool_results:
            await _maybe_edit_with_result(config, storage, hook_input, session_id)

        # Check for pending messages from /msg command
        pending = await storage.get_pending_messages(session_id)
        debug("posttool", f"pending_messages={len(pending) if pending else 0}")

        if not pending:
            return {}

        messages = []
        for msg_id, msg_text in pending:
            messages.append(f"- {msg_text}")
            await storage.mark_message_delivered(msg_id)
            debug("posttool", f"Delivering: {msg_text[:50]}")

        additional_context = (
            "The user sent you a message via remote approval:\n"
            + "\n".join(messages)
        )

        try:
            print(f"[owl] Delivering {len(pending)} pending message(s)", file=sys.stderr)
        except BrokenPipeError:
            pass

        return make_hook_response("PostToolUse", additional_context=additional_context)

    finally:
        await storage.close()


async def _maybe_edit_with_result(
    config: Config,
    storage: Storage,
    hook_input: dict,
    session_id: str,
) -> None:
    """Edit the original approval message to append tool result."""
    from owl.core.handlers.utils import format_resolved_message
    from owl.notifiers.telegram import TelegramNotifier
    from owl.utils.formatting import format_project_id, format_tool_summary
    from owl.utils.results import format_tool_result, should_show_result

    tool_name = hook_input.get("tool_name", "")
    if not should_show_result(tool_name):
        return

    tool_response = hook_input.get("tool_response")
    if tool_response is None:
        return

    request = await storage.get_latest_resolved_request(session_id, tool_name)
    if not request or not request.telegram_msg_id:
        debug("posttool", "No resolved request with telegram_msg_id found")
        return

    # Skip for chain requests — chain handler manages its own message updates
    chain_state = await storage.get_chain_state(request.telegram_msg_id)
    if chain_state is not None:
        debug("posttool", "Skipping result edit for chain request")
        return

    tool_input = hook_input.get("tool_input")
    tool_input_str = json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input or "")

    result_html = format_tool_result(tool_name, tool_input_str, tool_response)
    if not result_html:
        return

    project_path = hook_input.get("cwd")
    project_id = format_project_id(project_path, session_id)
    tool_summary = format_tool_summary(request.tool_name, request.tool_input)
    resolved_msg = format_resolved_message(
        approved=(request.status == "approved"),
        project_id=project_id,
        tool_name=request.tool_name,
        tool_summary=tool_summary,
    )

    # Budget-aware truncation: truncate result content before combining
    # to avoid cutting inside HTML tags
    max_message_length = 4000
    budget = max_message_length - len(resolved_msg) - 1  # -1 for newline
    if budget < 20:
        return  # Not enough room for a meaningful result
    if len(result_html) > budget:
        # Re-format with truncated content rather than slicing HTML
        result_html = "\u2026 (result too long)"

    new_text = f"{resolved_msg}\n{result_html}"

    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    try:
        success = await notifier.edit_message(
            message_id=request.telegram_msg_id,
            new_text=new_text,
        )
        debug("posttool", f"edit_message success={success} msg_id={request.telegram_msg_id}")
    except Exception as e:
        debug("posttool", f"edit_message error: {e}")
    finally:
        await notifier.close()


if __name__ == "__main__":
    from owl.hooks.runner import run_hook

    run_hook(handle_posttool_use)
