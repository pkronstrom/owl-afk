"""PreToolUse hook handler."""

import json
from pathlib import Path
from typing import Optional

from pyafk.core.manager import ApprovalManager
from pyafk.fast_path import FastPathResult, check_fast_path


def _make_response(decision: str, reason: str = "") -> dict:
    """Build hook response in Claude Code's expected format.

    Args:
        decision: "allow" or "deny"
        reason: Optional reason for the decision

    Note: PreToolUse does NOT support additionalContext.
    Use PostToolUse hook for message delivery.
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


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
        Response dict with hookSpecificOutput for Claude Code
    """
    import sys

    fast_result = check_fast_path(pyafk_dir)
    if fast_result == FastPathResult.APPROVE:
        return _make_response("allow", "pyafk fast path: approve all")
    elif fast_result == FastPathResult.DENY:
        return _make_response("deny", "pyafk fast path: deny all")

    tool_name = hook_input.get("tool_name", "Unknown")
    tool_input = hook_input.get("tool_input")

    # Debug: log to stderr what we're processing
    print(f"[pyafk] Processing: {tool_name}", file=sys.stderr)
    session_id = hook_input.get("session_id", "unknown")
    context = hook_input.get("tool_context")

    if isinstance(tool_input, dict):
        description = tool_input.get("description")
        tool_input_str = json.dumps(tool_input)
    else:
        description = None
        tool_input_str = str(tool_input) if tool_input else None

    # Try multiple field names for project path
    project_path = (
        hook_input.get("project_path")
        or hook_input.get("cwd")
        or hook_input.get("working_directory")
        or hook_input.get("workingDirectory")
    )

    manager = ApprovalManager(pyafk_dir=pyafk_dir)
    try:
        result, denial_reason = await manager.request_approval(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input_str,
            context=context,
            description=description,
            project_path=project_path,
        )

        # Handle "fallback" - return empty response to trigger CLI prompt
        if result == "fallback":
            return {}

        # Note: Message delivery moved to PostToolUse hook (PreToolUse doesn't support additionalContext)

        # Map internal result to Claude Code's expected values
        decision = "allow" if result == "approve" else "deny"
        if denial_reason:
            reason = f"pyafk: denied - {denial_reason}"
        else:
            reason = f"pyafk: {'allowed' if decision == 'allow' else 'denied'} via Telegram"

        return _make_response(decision, reason)
    finally:
        await manager.close()


if __name__ == "__main__":
    from pyafk.hooks.runner import run_hook
    run_hook(handle_pretool_use)
