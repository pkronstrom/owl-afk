"""Unified hook response helpers."""

from typing import Optional


def make_hook_response(
    hook_event: str,
    decision: Optional[str] = None,
    reason: str = "",
    additional_context: Optional[str] = None,
) -> dict:
    """Build hook response in Claude Code's expected format.

    Args:
        hook_event: Hook event name (PreToolUse, PostToolUse, PermissionRequest, etc.)
        decision: Permission decision for PreToolUse/PermissionRequest ("allow" or "deny")
        reason: Reason for the decision
        additional_context: Additional context for PostToolUse hook

    Returns:
        Response dict ready for JSON serialization.
    """
    output: dict = {
        "hookSpecificOutput": {
            "hookEventName": hook_event,
        }
    }

    if decision is not None:
        output["hookSpecificOutput"]["permissionDecision"] = decision
        output["hookSpecificOutput"]["permissionDecisionReason"] = reason

    if additional_context is not None:
        output["hookSpecificOutput"]["additionalContext"] = additional_context

    return output
