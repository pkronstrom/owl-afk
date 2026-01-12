"""Stop hook handler - interactive approval before Claude stops."""

import asyncio
import time
from pathlib import Path
from typing import Optional

from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.config import Config, get_pyafk_dir


async def handle_stop(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle Stop hook - ask user for OK or Comment before stopping.

    1. Check for already-pending messages - deliver immediately
    2. Send interactive notification with OK/Comment buttons
    3. Wait for user response
    4. If OK: let Claude stop
    5. If Comment: block stop and deliver the message
    """
    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    config = Config(pyafk_dir)
    project_path = hook_input.get("cwd")

    # Pass through when mode is off, project not enabled, or hook is disabled
    if not config.is_enabled_for_project(project_path) or not config.stop_hook:
        return {}

    # Check Telegram config
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return {}

    session_id = hook_input.get("session_id", "unknown")

    storage = Storage(config.db_path)
    try:
        await storage.connect()

        # First check for already-pending messages (from /msg)
        pending = await storage.get_pending_messages(session_id)
        if pending:
            messages = []
            for msg_id, msg_text in pending:
                messages.append(f"- {msg_text}")
                await storage.mark_message_delivered(msg_id)

            reason = (
                "📨 The user sent you a message via remote approval:\n"
                + "\n".join(messages)
                + "\n\nPlease address this before stopping."
            )
            # Include both formats for compatibility with Claude Code
            return {
                "decision": "block",
                "reason": reason,
                "hookSpecificOutput": {
                    "hookEventName": "Stop",
                    "decision": "block",
                    "reason": reason,
                },
            }

        # No pending messages - send interactive notification
        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        msg_id = await notifier.send_stop_notification(
            session_id=session_id,
            project_path=project_path,
        )

        # Create pending stop entry
        await storage.create_pending_stop(session_id, msg_id)

        # Poll for response
        from pyafk.core.poller import Poller
        from pyafk.daemon import is_daemon_running

        poller = Poller(storage, notifier, pyafk_dir)

        timeout = 3600  # 1 hour
        start = time.monotonic()

        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    # Timeout - let Claude stop
                    return {}

                # Poll for updates (only if daemon not running)
                # Re-check each iteration in case daemon crashes
                if not is_daemon_running(pyafk_dir):
                    try:
                        await poller.process_updates_once()
                    except Exception:
                        pass

                # Check status
                entry = await storage.get_pending_stop(session_id)
                if entry and entry["status"] != "pending":
                    if entry["status"] == "comment" and entry["response"]:
                        # User sent a comment - block and deliver
                        reason = (
                            "📨 The user sent you a message via remote approval:\n"
                            f"- {entry['response']}\n\n"
                            "Please address this before stopping."
                        )
                        # Include both formats for compatibility with Claude Code
                        return {
                            "decision": "block",
                            "reason": reason,
                            "hookSpecificOutput": {
                                "hookEventName": "Stop",
                                "decision": "block",
                                "reason": reason,
                            },
                        }
                    else:
                        # OK - let Claude stop
                        return {}

                await asyncio.sleep(0.5)
        finally:
            await notifier.close()

    finally:
        await storage.close()


if __name__ == "__main__":
    from pyafk.hooks.runner import run_hook

    run_hook(handle_stop)
