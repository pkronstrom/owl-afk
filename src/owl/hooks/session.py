"""Session hook handlers - SessionStart and SessionEnd."""

import sys
from pathlib import Path
from typing import Optional

from owl.notifiers.telegram import TelegramNotifier
from owl.utils.config import Config, get_owl_dir


async def handle_session_start(
    hook_input: dict,
    owl_dir: Optional[Path] = None,
) -> dict:
    """Handle SessionStart hook - notify new session.

    Args:
        hook_input: Dict with source (startup/resume/clear/compact), session_id
        owl_dir: Path to owl directory

    Returns:
        Empty response
    """
    # SessionStart is handled silently for now
    # Could add smart rules loading here in the future
    return {}


async def handle_session_end(
    hook_input: dict,
    owl_dir: Optional[Path] = None,
) -> dict:
    """Handle SessionEnd hook - notify session ended.

    Args:
        hook_input: Dict with reason (clear/logout/prompt_input_exit/other), session_id
        owl_dir: Path to owl directory

    Returns:
        Empty response
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

    reason = hook_input.get("reason", "unknown")
    session_id = hook_input.get("session_id", "unknown")

    # Format project name from cwd
    project_name = Path(cwd).name if cwd else "unknown"

    # Send notification
    notifier = TelegramNotifier(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
    )

    reason_icon = {
        "clear": "×",
        "logout": "—",
        "prompt_input_exit": "■",
        "other": "—",
    }
    icon = reason_icon.get(reason, "—")

    message = f"{icon} <b>Session ended</b> ({reason})\n<i>{project_name}</i> ({session_id[:8]})"

    try:
        await notifier.send_message(message, parse_mode="HTML")
        try:
            print(f"[owl] SessionEnd notification sent ({reason})", file=sys.stderr)
        except BrokenPipeError:
            pass
    except Exception as e:
        try:
            print(f"[owl] SessionEnd notification failed: {e}", file=sys.stderr)
        except BrokenPipeError:
            pass
    finally:
        await notifier.close()

    return {}
