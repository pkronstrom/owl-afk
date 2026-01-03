"""Main hook handler dispatcher."""

import json
import sys
from pathlib import Path
from typing import Optional

from pyafk.fast_path import FastPathResult, check_fast_path


async def handle_hook(
    hook_type: str,
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle a Claude Code hook."""
    if hook_type == "PreToolUse":
        from pyafk.hooks.pretool import handle_pretool_use
        return await handle_pretool_use(hook_input, pyafk_dir)
    elif hook_type == "Stop":
        from pyafk.hooks.stop import handle_stop
        return await handle_stop(hook_input, pyafk_dir)
    elif hook_type == "SessionStart":
        from pyafk.hooks.session import handle_session_start
        return await handle_session_start(hook_input, pyafk_dir)
    else:
        return {"error": f"Unknown hook type: {hook_type}"}
