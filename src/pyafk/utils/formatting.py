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
    return cmd[:max_len - 3] + "..."


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
