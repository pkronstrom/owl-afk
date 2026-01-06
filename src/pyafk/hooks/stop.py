"""Stop hook handler - delivers pending messages before Claude stops."""

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
    """Handle Stop hook - notify user and wait for response before stopping.

    1. Check for already-pending messages - deliver immediately
    2. Send "about to stop" notification to Telegram
    3. Wait up to 30 seconds for user to send /msg
    4. If message received, block stop and deliver it
    5. If timeout, allow Claude to stop
    """
    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    config = Config(pyafk_dir)

    # Pass through when mode is off
    if config.get_mode() != "on":
        return {}

    # Check Telegram config
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return {}

    session_id = hook_input.get("session_id", "unknown")

    storage = Storage(config.db_path)
    try:
        await storage.connect()

        # First check for already-pending messages
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
            return {"decision": "block", "reason": reason}

        # No pending messages - notify user and wait
        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        # Send notification
        session_short = session_id[:8] if len(session_id) > 8 else session_id
        await notifier.send_message(
            f"⏸️ <b>Claude is about to stop</b> ({session_short})\n\n"
            f"Reply with /msg to continue the conversation.\n"
            f"<i>Waiting 30 seconds...</i>"
        )

        # Poll for messages (30 second timeout)
        from pyafk.core.poller import Poller
        from pyafk.daemon import is_daemon_running

        poller = Poller(storage, notifier, pyafk_dir)
        daemon_running = is_daemon_running(pyafk_dir)

        timeout = 30
        start = time.monotonic()

        while True:
            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                # Timeout - let Claude stop
                await notifier.send_message("✅ Session ended (no response)")
                return {}

            # Poll for updates (only if daemon not running)
            if not daemon_running:
                try:
                    await poller.process_updates_once()
                except Exception:
                    pass

            # Check for new messages
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

                await notifier.send_message("▶️ Continuing with your message...")
                return {"decision": "block", "reason": reason}

            await asyncio.sleep(0.5)

    finally:
        await storage.close()
