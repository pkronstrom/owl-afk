"""Stop hook handler."""

from pathlib import Path
from typing import Optional


async def handle_stop(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle Stop hook - notify that session ended."""
    # TODO: Send summary to Telegram
    return {}
