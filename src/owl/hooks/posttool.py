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
    from owl.notifiers.telegram import TelegramNotifier, format_approval_message
    from owl.utils.results import format_tool_result, should_show_result

    tool_name = hook_input.get("tool_name", "")
    if not should_show_result(tool_name):
        return

    tool_response = hook_input.get("tool_response")
    if tool_response is None:
        return

    request = await storage.get_latest_resolved_request(session_id)
    if not request or not request.telegram_msg_id:
        debug("posttool", "No resolved request with telegram_msg_id found")
        return

    tool_input = hook_input.get("tool_input")
    tool_input_str = json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input or "")

    result_html = format_tool_result(tool_name, tool_input_str, tool_response)
    if not result_html:
        return

    original_msg = format_approval_message(
        request_id=request.id,
        session_id=session_id,
        tool_name=request.tool_name,
        tool_input=request.tool_input,
        description=request.description,
    )

    new_text = f"{original_msg}\n─────────\n{result_html}"

    if len(new_text) > 4000:
        new_text = new_text[:4000] + "\n\u2026 (message truncated)"

    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    try:
        success = await notifier.edit_message(
            message_id=request.telegram_msg_id,
            new_text=new_text,
        )
        debug("posttool", f"edit_message success={success} msg_id={request.telegram_msg_id}")
    except Exception as e:
        debug("posttool", f"edit_message error: {e}")


if __name__ == "__main__":
    from owl.hooks.runner import run_hook

    run_hook(handle_posttool_use)
