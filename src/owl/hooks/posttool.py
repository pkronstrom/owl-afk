"""PostToolUse hook handler - delivers pending messages."""

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
    """Handle PostToolUse hook - deliver pending messages.

    Args:
        hook_input: Dict with session_id and other fields from Claude Code
        owl_dir: Path to owl directory

    Returns:
        Response dict with hookSpecificOutput for Claude Code
    """
    import sys

    if owl_dir is None:
        owl_dir = get_owl_dir()

    config = Config(owl_dir)
    project_path = hook_input.get("cwd")

    # Pass through when mode is off or project not enabled
    if not config.is_enabled_for_project(project_path):
        return {}

    storage = Storage(config.db_path)

    try:
        await storage.connect()

        session_id = hook_input.get("session_id", "unknown")
        debug("posttool", f"session_id={session_id}")

        # Check for pending messages from /msg command
        pending = await storage.get_pending_messages(session_id)
        debug("posttool", f"pending_messages={len(pending) if pending else 0}")

        if not pending:
            return {}  # No messages, return empty response

        # Build additional context with all pending messages
        messages = []
        for msg_id, msg_text in pending:
            messages.append(f"- {msg_text}")
            await storage.mark_message_delivered(msg_id)
            debug("posttool", f"Delivering: {msg_text[:50]}")

        additional_context = (
            "📨 The user sent you a message via remote approval:\n"
            + "\n".join(messages)
        )

        try:
            print(f"[owl] Delivering {len(pending)} pending message(s)", file=sys.stderr)
        except BrokenPipeError:
            pass

        return make_hook_response("PostToolUse", additional_context=additional_context)

    finally:
        await storage.close()


if __name__ == "__main__":
    from owl.hooks.runner import run_hook

    run_hook(handle_posttool_use)
