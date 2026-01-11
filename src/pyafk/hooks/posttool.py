"""PostToolUse hook handler - delivers pending messages."""

import json
import time
from pathlib import Path
from typing import Optional

from pyafk.core.storage import Storage
from pyafk.hooks.response import make_hook_response
from pyafk.utils.config import Config, get_pyafk_dir


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

    # Debug log
    debug_log = pyafk_dir / "posttool_debug.log"

    def log(msg: str) -> None:
        with open(debug_log, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

    try:
        await storage.connect()

        session_id = hook_input.get("session_id", "unknown")
        log(f"session_id={session_id}")

        # Check for pending messages from /msg command
        pending = await storage.get_pending_messages(session_id)
        log(f"pending_messages={len(pending) if pending else 0}")

        if not pending:
            return {}  # No messages, return empty response

        # Build additional context with all pending messages
        messages = []
        for msg_id, msg_text in pending:
            messages.append(f"- {msg_text}")
            await storage.mark_message_delivered(msg_id)
            log(f"  Delivering: {msg_text[:50]}")

        additional_context = (
            "📨 The user sent you a message via remote approval:\n"
            + "\n".join(messages)
        )

        print(f"[pyafk] Delivering {len(pending)} pending message(s)", file=sys.stderr)
        log(f"additionalContext: {additional_context[:100]}")

        response = make_hook_response(
            "PostToolUse", additional_context=additional_context
        )
        log(f"Response: {json.dumps(response)[:200]}")
        return response

    finally:
        await storage.close()


if __name__ == "__main__":
    from pyafk.hooks.runner import run_hook

    run_hook(handle_posttool_use)
