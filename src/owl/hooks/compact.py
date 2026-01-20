"""PreCompact hook handler - notify on context compaction."""

import sys
from pathlib import Path
from typing import Optional

from owl.notifiers.telegram import TelegramNotifier
from owl.utils.config import Config, get_owl_dir


async def handle_pre_compact(
    hook_input: dict,
    owl_dir: Optional[Path] = None,
) -> dict:
    """Handle PreCompact hook - notify user about context compaction.

    Args:
        hook_input: Dict with trigger (manual/auto), custom_instructions, session_id
        owl_dir: Path to owl directory

    Returns:
        Empty response (allow compaction to proceed)
    """
    if owl_dir is None:
        owl_dir = get_owl_dir()

    config = Config(owl_dir)
    cwd = hook_input.get("cwd", "")

    # Only notify if owl is enabled for this project and Telegram is configured
    if not config.is_enabled_for_project(cwd):
        return {}

    if not config.telegram_bot_token or not config.telegram_chat_id:
        return {}

    trigger = hook_input.get("trigger", "unknown")
    session_id = hook_input.get("session_id", "unknown")

    # Format project name from cwd
    project_name = Path(cwd).name if cwd else "unknown"

    # Send notification
    notifier = TelegramNotifier(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
    )

    emoji = "🔄" if trigger == "auto" else "📦"
    trigger_text = "Auto-compacting" if trigger == "auto" else "Manual compact"

    message = f"{emoji} <b>{trigger_text}</b>\n<i>{project_name}</i> ({session_id[:8]})"

    try:
        await notifier.send_message(message, parse_mode="HTML")
        try:
            print(f"[owl] PreCompact notification sent ({trigger})", file=sys.stderr)
        except BrokenPipeError:
            pass
    except Exception as e:
        try:
            print(f"[owl] PreCompact notification failed: {e}", file=sys.stderr)
        except BrokenPipeError:
            pass
    finally:
        await notifier.close()

    return {}
