"""PreToolUse hook handler."""

import json
from pathlib import Path
from typing import Optional

from pyafk.core.manager import ApprovalManager
from pyafk.fast_path import FastPathResult, check_fast_path


async def handle_pretool_use(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle PreToolUse hook.

    Args:
        hook_input: Dict with tool_name, tool_input, session_id, tool_context,
            project_path fields from Claude Code
        pyafk_dir: Path to pyafk directory

    Returns:
        Response dict with "decision" key ("approve" or "deny")
    """
    fast_result = check_fast_path(pyafk_dir)
    if fast_result == FastPathResult.APPROVE:
        return {"decision": "approve"}
    elif fast_result == FastPathResult.DENY:
        return {"decision": "deny"}

    tool_name = hook_input.get("tool_name", "Unknown")
    tool_input = hook_input.get("tool_input")
    session_id = hook_input.get("session_id", "unknown")
    context = hook_input.get("tool_context")

    if isinstance(tool_input, dict):
        description = tool_input.get("description")
        tool_input_str = json.dumps(tool_input)
    else:
        description = None
        tool_input_str = str(tool_input) if tool_input else None

    project_path = hook_input.get("project_path")

    manager = ApprovalManager(pyafk_dir=pyafk_dir)
    try:
        result = await manager.request_approval(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input_str,
            context=context,
            description=description,
            project_path=project_path,
        )
        return {"decision": result}
    finally:
        await manager.close()
