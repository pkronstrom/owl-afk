"""Shared utilities for callback handlers."""

from typing import Optional

from owl.utils.formatting import format_tool_call_html


def format_resolved_message(
    approved: bool,
    project_id: str,
    tool_name: str,
    tool_summary: str,
    rule_label: Optional[str] = None,
) -> str:
    """Format a resolved approval message for Telegram.

    Args:
        approved: Whether the request was approved (True) or denied (False)
        project_id: Formatted project identifier
        tool_name: Name of the tool (Bash, Edit, etc.)
        tool_summary: Summary of tool input
        rule_label: Optional label if resolved via rule

    Returns:
        HTML-formatted message string
    """
    icon = "\u2713" if approved else "\u2717"
    base = f"<i>{project_id}</i>\n{format_tool_call_html(tool_name, tool_summary, prefix=icon + ' ')}"

    if rule_label:
        action = "Always" if approved else "Never"
        base += f"\n+ {action}: {rule_label}"

    return base
