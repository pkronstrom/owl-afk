"""Formatting utilities for owl."""

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


def format_auto_approval_message(
    tool_name: str,
    tool_input: Optional[str],
    project_path: Optional[str],
    session_id: str,
) -> str:
    """Format auto-approval notification message.

    Args:
        tool_name: Name of the tool (e.g., "Bash")
        tool_input: JSON tool input
        project_path: Project path for display
        session_id: Session ID for display

    Returns:
        HTML-formatted message string
    """
    project_id = format_project_id(project_path, session_id)

    # Always use the original tool_input - shows full command for both
    # single commands and chains
    summary = format_tool_summary(tool_name, tool_input)

    return (
        f"<i>{escape_html(project_id)}</i>\n"
        f"{format_tool_call_html(tool_name, summary, prefix='\u21bb ')}"
    )


def format_tool_call_html(tool_name: str, summary: str, prefix: str = "") -> str:
    """Format a tool call as HTML with syntax highlighting.

    Returns the tool name + summary as highlighted HTML. Used by all message
    types (approval, resolved, auto-approval, chain, denial) for consistent
    formatting.

    Args:
        tool_name: Name of the tool (Bash, Edit, etc.)
        summary: Raw tool input summary (will be HTML-escaped internally)
        prefix: Optional prefix icon (e.g. "✓ ", "✗ ", "↻ ")

    Returns:
        HTML string with <pre><code> block or inline <code>.
    """
    from owl.utils.languages import detect_bash_language, detect_file_language

    lang = "bash"
    if tool_name == "Bash":
        lang = detect_bash_language(summary)
    elif tool_name in ("Edit", "Write"):
        lang = detect_file_language(summary) or "bash"

    escaped = escape_html(summary)
    tool_label = f"{escape_html(prefix)}<b>[{escape_html(tool_name)}]</b>"

    return f"{tool_label}\n" f'<pre><code class="language-{lang}">{escaped}</code></pre>'


def format_tool_summary(tool_name: str, tool_input: Optional[str]) -> str:
    """Extract the most relevant field from tool_input JSON.

    Returns raw (unescaped) summary string. Callers should pass the result
    to format_tool_call_html() which handles HTML escaping.

    Args:
        tool_name: Name of the tool (Bash, Edit, etc.)
        tool_input: JSON string of tool input

    Returns:
        Raw summary string.
    """
    import json

    if not tool_input:
        return ""

    try:
        data = json.loads(tool_input)
    except (json.JSONDecodeError, TypeError):
        return str(tool_input)[:100]

    # Extract the most relevant field
    summary: str
    if "command" in data:
        summary = str(data["command"])
    elif "file_path" in data:
        summary = str(data["file_path"])
    elif "content" in data:
        summary = str(data.get("file_path", "(content)"))
    elif "path" in data:
        summary = str(data["path"])
    elif "url" in data:
        summary = str(data["url"])
    else:
        summary = json.dumps(data)

    return summary
