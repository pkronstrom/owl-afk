"""Tests for formatting utilities."""

from owl.utils.formatting import format_auto_approval_message


def test_format_auto_approval_message_single_command():
    """Should format single command auto-approval message."""
    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "git status"}',
        project_path="/home/user/project",
        session_id="session-123",
    )

    assert "user/project" in msg
    assert "↻" in msg  # Auto-approve icon
    assert "[Bash]" in msg
    assert "git status" in msg


def test_format_auto_approval_message_chain():
    """Should format chain with original command."""
    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "git add . && git commit -m test && git push"}',
        project_path="/home/user/project",
        session_id="session-123",
    )

    assert "user/project" in msg
    assert "↻" in msg  # Auto-approve icon
    assert "[Bash]" in msg
    # Shows the original chain command (truncated at 100 chars)
    assert "git add" in msg
    assert "git commit" in msg


def test_format_auto_approval_message_no_project_path():
    """Should use session ID when no project path."""
    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "ls"}',
        project_path=None,
        session_id="abc12345-long-session-id",
    )

    assert "abc12345" in msg  # First 8 chars of session ID
    assert "↻" in msg  # Auto-approve icon


def test_format_auto_approval_message_escapes_html():
    """Should escape HTML in command."""
    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "echo <script>alert(1)</script>"}',
        project_path="/home/user/project",
        session_id="session-123",
    )

    assert "&lt;script&gt;" in msg
    assert "<script>" not in msg


def test_format_auto_approval_uses_pre_block():
    """Auto-approval message should use <pre><code> block."""
    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "python train.py"}',
        project_path="/home/user/project",
        session_id="session-123",
    )
    assert '<pre><code class="language-python">' in msg
    assert "python train.py" in msg
