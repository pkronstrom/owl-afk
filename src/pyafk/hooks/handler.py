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
    """Handle a Claude Code hook.

    Args:
        hook_type: Hook event name
        hook_input: Parsed JSON from stdin
        pyafk_dir: Path to pyafk directory

    Returns:
        Response dict to output as JSON
    """
    if hook_type == "PreToolUse":
        from pyafk.hooks.pretool import handle_pretool_use
        return await handle_pretool_use(hook_input, pyafk_dir)
    elif hook_type == "PostToolUse":
        from pyafk.hooks.posttool import handle_posttool_use
        return await handle_posttool_use(hook_input, pyafk_dir)
    elif hook_type == "PermissionRequest":
        from pyafk.hooks.permission import handle_permission_request
        return await handle_permission_request(hook_input, pyafk_dir)
    elif hook_type == "SubagentStop":
        from pyafk.hooks.subagent import handle_subagent_stop
        return await handle_subagent_stop(hook_input, pyafk_dir)
    elif hook_type == "Stop":
        from pyafk.hooks.stop import handle_stop
        return await handle_stop(hook_input, pyafk_dir)
    elif hook_type == "SessionStart":
        from pyafk.hooks.session import handle_session_start
        return await handle_session_start(hook_input, pyafk_dir)
    elif hook_type == "PreCompact":
        from pyafk.hooks.compact import handle_pre_compact
        return await handle_pre_compact(hook_input, pyafk_dir)
    elif hook_type == "SessionEnd":
        from pyafk.hooks.session import handle_session_end
        return await handle_session_end(hook_input, pyafk_dir)
    else:
        return {"error": f"Unknown hook type: {hook_type}"}


def main():
    """CLI entry point for hooks."""
    import asyncio

    if len(sys.argv) < 3 or sys.argv[1] != "hook":
        print(json.dumps({"error": "Usage: pyafk hook <HookType>"}))
        sys.exit(1)

    hook_type = sys.argv[2]

    # Fast path check first
    result = check_fast_path()
    if result == FastPathResult.APPROVE:
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)
    elif result == FastPathResult.DENY:
        print(json.dumps({"decision": "deny"}))
        sys.exit(0)
    elif result == FastPathResult.FALLBACK:
        # Return empty to fall back to Claude's CLI approval
        print(json.dumps({}))
        sys.exit(0)

    # Read stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input"}))
        sys.exit(1)

    # Run async handler
    response = asyncio.run(handle_hook(hook_type, hook_input))
    print(json.dumps(response))
