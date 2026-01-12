"""PermissionRequest hook handler."""

import json
from pathlib import Path
from typing import Optional

from pyafk.hooks.response import make_hook_response


async def handle_permission_request(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle PermissionRequest hook.

    This is a fallback that intercepts permission dialogs.
    Routes to the same approval system as PreToolUse.

    Args:
        hook_input: Dict with tool_name, tool_input, session_id fields
        pyafk_dir: Path to pyafk directory

    Returns:
        Response dict with hookSpecificOutput for Claude Code
    """
    import sys

    from pyafk.core.manager import ApprovalManager
    from pyafk.fast_path import FastPathResult, check_fast_path
    from pyafk.utils.config import Config

    fast_result = check_fast_path(pyafk_dir)
    if fast_result == FastPathResult.APPROVE:
        return make_hook_response(
            "PermissionRequest", decision="allow", reason="pyafk fast path: approve all"
        )
    elif fast_result == FastPathResult.DENY:
        return make_hook_response(
            "PermissionRequest", decision="deny", reason="pyafk fast path: deny all"
        )
    elif fast_result == FastPathResult.FALLBACK:
        return {}  # Fall back to Claude's CLI approval

    tool_name = hook_input.get("tool_name", "Unknown")
    tool_input = hook_input.get("tool_input")

    print(f"[pyafk] PermissionRequest: {tool_name}", file=sys.stderr)
    session_id = hook_input.get("session_id", "unknown")

    if isinstance(tool_input, dict):
        description = tool_input.get("description")
        tool_input_str = json.dumps(tool_input)
    else:
        description = None
        tool_input_str = str(tool_input) if tool_input else None

    project_path = hook_input.get("cwd")

    # Load config and check if enabled for this project
    config = Config(pyafk_dir)
    if not config.is_enabled_for_project(project_path):
        return {}  # Fall back to CLI approval

    manager = ApprovalManager(
        pyafk_dir=pyafk_dir,
        timeout=config.timeout_seconds,
        timeout_action=config.timeout_action,
        config=config,
    )
    try:
        result, denial_reason = await manager.request_approval(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input_str,
            description=description,
            project_path=project_path,
        )
        decision = "allow" if result == "approve" else "deny"
        if denial_reason:
            reason = f"pyafk: denied - {denial_reason}"
        else:
            reason = (
                f"pyafk: {'allowed' if decision == 'allow' else 'denied'} via Telegram"
            )
        return make_hook_response("PermissionRequest", decision=decision, reason=reason)
    finally:
        await manager.close()
