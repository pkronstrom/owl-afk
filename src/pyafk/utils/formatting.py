"""Formatting utilities for pyafk."""

from typing import Optional


def format_project_id(project_path: Optional[str], session_id: str) -> str:
    """Format project path for display.

    Returns last 2 path components or short session ID.
    """
    if project_path:
        parts = project_path.rstrip("/").split("/")
        return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return session_id[:8]


def truncate_command(cmd: str, max_len: int = 60) -> str:
    """Truncate command for display."""
    if len(cmd) <= max_len:
        return cmd
    return cmd[: max_len - 3] + "..."


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_tool_summary(tool_name: str, tool_input: Optional[str]) -> str:
    """Format tool input for display.

    Extracts the most relevant field from tool_input JSON and escapes HTML.

    Args:
        tool_name: Name of the tool (Bash, Edit, etc.)
        tool_input: JSON string of tool input

    Returns:
        Formatted and escaped summary string (max 100 chars).
    """
    import json

    if not tool_input:
        return ""

    try:
        data = json.loads(tool_input)
    except (json.JSONDecodeError, TypeError):
        return escape_html(str(tool_input)[:100])

    # Extract the most relevant field
    summary: str
    if "command" in data:
        summary = str(data["command"])
    elif "file_path" in data:
        summary = str(data["file_path"])
    elif "path" in data:
        summary = str(data["path"])
    elif "url" in data:
        summary = str(data["url"])
    else:
        summary = json.dumps(data)

    # Truncate if too long
    if len(summary) > 100:
        summary = summary[:100] + "..."

    return escape_html(summary)
