"""Main hook handler dispatcher."""

import json
import sys
from pathlib import Path
from typing import Optional

from owl.fast_path import FastPathResult, check_fast_path


async def handle_hook(
    hook_type: str,
    hook_input: dict,
    owl_dir: Optional[Path] = None,
) -> dict:
    """Handle a Claude Code hook.

    Args:
        hook_type: Hook event name
        hook_input: Parsed JSON from stdin
        owl_dir: Path to owl directory

    Returns:
        Response dict to output as JSON
    """
    if hook_type == "PreToolUse":
        from owl.hooks.pretool import handle_pretool_use
        return await handle_pretool_use(hook_input, owl_dir)
    elif hook_type == "PostToolUse":
        from owl.hooks.posttool import handle_posttool_use
        return await handle_posttool_use(hook_input, owl_dir)
    elif hook_type == "PermissionRequest":
        from owl.hooks.permission import handle_permission_request
        return await handle_permission_request(hook_input, owl_dir)
    elif hook_type == "SubagentStop":
        from owl.hooks.subagent import handle_subagent_stop
        return await handle_subagent_stop(hook_input, owl_dir)
    elif hook_type == "Stop":
        from owl.hooks.stop import handle_stop
        return await handle_stop(hook_input, owl_dir)
    elif hook_type == "SessionStart":
        from owl.hooks.session import handle_session_start
        return await handle_session_start(hook_input, owl_dir)
    elif hook_type == "PreCompact":
        from owl.hooks.compact import handle_pre_compact
        return await handle_pre_compact(hook_input, owl_dir)
    elif hook_type == "SessionEnd":
        from owl.hooks.session import handle_session_end
        return await handle_session_end(hook_input, owl_dir)
    else:
        return {"error": f"Unknown hook type: {hook_type}"}


def main():
    """CLI entry point for hooks."""
    import asyncio

    from owl.utils.config import get_owl_dir
    from owl.utils.debug import log_error

    if len(sys.argv) < 3 or sys.argv[1] != "hook":
        print(json.dumps({"error": "Usage: owl hook <HookType>"}))
        sys.exit(1)

    hook_type = sys.argv[2]
    owl_dir = get_owl_dir()

    # Fast path check first
    result = check_fast_path(owl_dir)
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

    # Run async handler with error logging
    try:
        response = asyncio.run(handle_hook(hook_type, hook_input, owl_dir))
        print(json.dumps(response))
    except Exception as e:
        # Log the full error with traceback (always, even if debug is off)
        log_error(
            "hook",
            f"Hook {hook_type} crashed: {type(e).__name__}: {e}",
            exc=e,
        )
        # Return empty dict to gracefully fall back to CLI approval
        print(json.dumps({}))
