"""PreToolUse hook handler."""

import json
from pathlib import Path
from typing import Optional

from owl.core.manager import ApprovalManager
from owl.fast_path import FastPathResult, check_fast_path
from owl.hooks.response import make_hook_response
from owl.utils.config import Config


async def handle_pretool_use(
    hook_input: dict,
    owl_dir: Optional[Path] = None,
) -> dict:
    """Handle PreToolUse hook.

    Args:
        hook_input: Dict with tool_name, tool_input, session_id, tool_context,
            project_path fields from Claude Code
        owl_dir: Path to owl directory

    Returns:
        Response dict with hookSpecificOutput for Claude Code
    """
    import sys

    fast_result = check_fast_path(owl_dir)
    if fast_result == FastPathResult.APPROVE:
        return make_hook_response(
            "PreToolUse", decision="allow", reason="owl fast path: approve all"
        )
    elif fast_result == FastPathResult.DENY:
        return make_hook_response(
            "PreToolUse", decision="deny", reason="owl fast path: deny all"
        )
    elif fast_result == FastPathResult.FALLBACK:
        return {}  # Fall back to Claude's CLI approval

    tool_name = hook_input.get("tool_name", "Unknown")
    tool_input = hook_input.get("tool_input")

    # Debug: log to stderr what we're processing
    try:
        print(f"[owl] Processing: {tool_name}", file=sys.stderr)
    except BrokenPipeError:
        pass  # Parent process closed stderr, continue silently
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

    # Load config and check if enabled for this project
    config = Config(owl_dir)
    if not config.is_enabled_for_project(project_path):
        return {}  # Fall back to CLI approval

    manager = ApprovalManager(
        owl_dir=owl_dir,
        timeout=config.timeout_seconds,
        timeout_action=config.timeout_action,
        config=config,
    )
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
            reason = f"owl: denied - {denial_reason}"
        else:
            reason = (
                f"owl: {'allowed' if decision == 'allow' else 'denied'} via Telegram"
            )

        return make_hook_response("PreToolUse", decision=decision, reason=reason)
    finally:
        await manager.close()


if __name__ == "__main__":
    from owl.hooks.runner import run_hook

    run_hook(handle_pretool_use)
