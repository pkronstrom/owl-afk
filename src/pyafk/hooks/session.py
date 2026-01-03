"""SessionStart hook handler."""

from pathlib import Path
from typing import Optional


async def handle_session_start(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle SessionStart hook - notify new session."""
    return {}
