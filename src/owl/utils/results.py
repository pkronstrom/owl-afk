"""Tool result formatting for Telegram messages."""

import json
from typing import Any

from owl.utils.formatting import escape_html

RESULT_TOOLS = {"Bash", "Grep", "Glob", "Edit", "Write"}
MAX_RESULT_LENGTH = 3000


def should_show_result(tool_name: str) -> bool:
    """Whether to show results for this tool type."""
    return tool_name in RESULT_TOOLS


def format_tool_result(tool_name: str, tool_input: str, tool_response: Any) -> str:
    """Format a tool result as HTML for appending to a Telegram message."""
    if tool_name == "Bash":
        return _format_bash_result(tool_input, tool_response)
    elif tool_name in ("Edit", "Write"):
        return _format_edit_write_result(tool_response)
    elif tool_name in ("Grep", "Glob"):
        return _format_search_result(tool_response)
    return ""


def _format_bash_result(tool_input: str, tool_response: Any) -> str:
    """Format Bash command output with language-detected highlighting."""
    command = ""
    try:
        data = json.loads(tool_input)
        command = data.get("command", "")
    except (json.JSONDecodeError, TypeError):
        pass

    output = ""
    if isinstance(tool_response, dict):
        output = tool_response.get("stdout", "") or tool_response.get("output", "") or ""
        stderr = tool_response.get("stderr", "")
        if stderr:
            output = output + "\n" + stderr if output else stderr
    elif isinstance(tool_response, str):
        output = tool_response
    else:
        output = str(tool_response) if tool_response else ""

    exit_code = tool_response.get("exit_code", 0) if isinstance(tool_response, dict) else 0

    if not output.strip():
        if exit_code != 0:
            return f"\u2717 exit code {exit_code}"
        return "\u2713"

    truncated = False
    if len(output) > MAX_RESULT_LENGTH:
        output = output[-MAX_RESULT_LENGTH:]
        truncated = True

    escaped = escape_html(output.strip())
    parts = []
    if truncated:
        parts.append("\u2026 (truncated)")
    parts.append(f'<pre><code class="language-shell-session">{escaped}</code></pre>')

    if exit_code != 0:
        parts.append(f"exit code {exit_code}")

    return "\n".join(parts)


def _format_edit_write_result(tool_response: Any) -> str:
    """Format Edit/Write result as simple success/fail indicator."""
    if isinstance(tool_response, dict) and tool_response.get("error"):
        return f"\u2717 {escape_html(str(tool_response['error']))}"
    return "\u2713"


def _format_search_result(tool_response: Any) -> str:
    """Format Grep/Glob result with bash highlighting."""
    output = ""
    if isinstance(tool_response, dict):
        output = tool_response.get("content", "") or tool_response.get("output", "") or ""
        if isinstance(output, list):
            output = "\n".join(str(item) for item in output)
    elif isinstance(tool_response, str):
        output = tool_response
    else:
        output = str(tool_response) if tool_response else ""

    if not output.strip():
        return "\u2713 (no matches)"

    if len(output) > MAX_RESULT_LENGTH:
        output = output[-MAX_RESULT_LENGTH:]
        escaped = escape_html(output.strip())
        return f'\u2026 (truncated)\n<pre><code class="language-shell-session">{escaped}</code></pre>'

    escaped = escape_html(output.strip())
    return f'<pre><code class="language-shell-session">{escaped}</code></pre>'
