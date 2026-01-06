"""Stop hook handler - delivers pending messages before Claude stops."""

from pathlib import Path
from typing import Optional

from pyafk.core.storage import Storage
from pyafk.utils.config import Config, get_pyafk_dir


async def handle_stop(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle Stop hook - deliver pending messages before Claude stops.

    If there are pending /msg messages, block the stop and deliver them.
    This ensures messages reach Claude even if no tool calls happen.
    """
    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    config = Config(pyafk_dir)

    # Pass through when mode is off
    if config.get_mode() != "on":
        return {}

    session_id = hook_input.get("session_id", "unknown")

    storage = Storage(config.db_path)
    try:
        await storage.connect()

        # Check for pending messages
        pending = await storage.get_pending_messages(session_id)

        if not pending:
            return {}  # No messages, let Claude stop

        # Build message content
        messages = []
        for msg_id, msg_text in pending:
            messages.append(f"- {msg_text}")
            await storage.mark_message_delivered(msg_id)

        reason = (
            "📨 The user sent you a message via remote approval:\n"
            + "\n".join(messages)
            + "\n\nPlease address this before stopping."
        )

        # Block the stop and deliver messages
        return {
            "decision": "block",
            "reason": reason,
        }

    finally:
        await storage.close()
