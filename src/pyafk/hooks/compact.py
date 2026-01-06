"""PreCompact hook handler - notify on context compaction."""

import sys
from pathlib import Path
from typing import Optional

from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.config import Config, get_pyafk_dir


async def handle_pre_compact(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle PreCompact hook - notify user about context compaction.

    Args:
        hook_input: Dict with trigger (manual/auto), custom_instructions, session_id
        pyafk_dir: Path to pyafk directory

    Returns:
        Empty response (allow compaction to proceed)
    """
    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    config = Config(pyafk_dir)

    # Only notify if pyafk is enabled and Telegram is configured
    if config.get_mode() != "on":
        return {}

    if not config.telegram_bot_token or not config.telegram_chat_id:
        return {}

    trigger = hook_input.get("trigger", "unknown")
    session_id = hook_input.get("session_id", "unknown")
    cwd = hook_input.get("cwd", "")

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
        print(f"[pyafk] PreCompact notification sent ({trigger})", file=sys.stderr)
    except Exception as e:
        print(f"[pyafk] PreCompact notification failed: {e}", file=sys.stderr)
    finally:
        await notifier.close()

    return {}
