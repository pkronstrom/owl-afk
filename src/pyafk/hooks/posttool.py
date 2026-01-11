"""PostToolUse hook handler - delivers pending messages."""

from pathlib import Path
from typing import Optional

from pyafk.core.storage import Storage
from pyafk.hooks.response import make_hook_response
from pyafk.utils.config import Config, get_pyafk_dir
from pyafk.utils.debug import debug


async def handle_posttool_use(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle PostToolUse hook - deliver pending messages.

    Args:
        hook_input: Dict with session_id and other fields from Claude Code
        pyafk_dir: Path to pyafk directory

    Returns:
        Response dict with hookSpecificOutput for Claude Code
    """
    import sys

    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    config = Config(pyafk_dir)

    # Pass through when mode is off
    if config.get_mode() != "on":
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

        print(f"[pyafk] Delivering {len(pending)} pending message(s)", file=sys.stderr)

        return make_hook_response("PostToolUse", additional_context=additional_context)

    finally:
        await storage.close()


if __name__ == "__main__":
    from pyafk.hooks.runner import run_hook

    run_hook(handle_posttool_use)
