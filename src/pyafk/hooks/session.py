"""Session hook handlers - SessionStart and SessionEnd."""

import sys
from pathlib import Path
from typing import Optional

from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.config import Config, get_pyafk_dir


async def handle_session_start(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle SessionStart hook - notify new session.

    Args:
        hook_input: Dict with source (startup/resume/clear/compact), session_id
        pyafk_dir: Path to pyafk directory

    Returns:
        Empty response
    """
    # SessionStart is handled silently for now
    # Could add smart rules loading here in the future
    return {}


async def handle_session_end(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle SessionEnd hook - notify session ended.

    Args:
        hook_input: Dict with reason (clear/logout/prompt_input_exit/other), session_id
        pyafk_dir: Path to pyafk directory

    Returns:
        Empty response
    """
    if pyafk_dir is None:
        pyafk_dir = get_pyafk_dir()

    config = Config(pyafk_dir)
    cwd = hook_input.get("cwd", "")

    # Only notify if pyafk is enabled for this project and Telegram is configured
    if not config.is_enabled_for_project(cwd):
        return {}

    if not config.telegram_bot_token or not config.telegram_chat_id:
        return {}

    reason = hook_input.get("reason", "unknown")
    session_id = hook_input.get("session_id", "unknown")

    # Format project name from cwd
    project_name = Path(cwd).name if cwd else "unknown"

    # Send notification
    notifier = TelegramNotifier(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
    )

    reason_emoji = {
        "clear": "🧹",
        "logout": "👋",
        "prompt_input_exit": "⏹️",
        "other": "🔚",
    }
    emoji = reason_emoji.get(reason, "🔚")

    message = f"{emoji} <b>Session ended</b> ({reason})\n<i>{project_name}</i> ({session_id[:8]})"

    try:
        await notifier.send_message(message, parse_mode="HTML")
        print(f"[pyafk] SessionEnd notification sent ({reason})", file=sys.stderr)
    except Exception as e:
        print(f"[pyafk] SessionEnd notification failed: {e}", file=sys.stderr)
    finally:
        await notifier.close()

    return {}
