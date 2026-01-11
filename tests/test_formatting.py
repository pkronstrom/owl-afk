"""Tests for formatting utilities."""

from pyafk.utils.formatting import format_auto_approval_message


def test_format_auto_approval_message_single_command():
    """Should format single command auto-approval message."""
    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "git status"}',
        project_path="/home/user/project",
        session_id="session-123",
    )

    assert "user/project" in msg
    assert "Auto-approved" in msg
    assert "git status" in msg


def test_format_auto_approval_message_chain():
    """Should format chain auto-approval message."""
    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "git add . && git commit"}',
        project_path="/home/user/project",
        session_id="session-123",
        is_chain=True,
        chain_commands=["git add .", "git commit -m 'test'", "git push"],
    )

    assert "user/project" in msg
    assert "Auto-approved" in msg
    assert "3 commands" in msg
    assert "git add" in msg


def test_format_auto_approval_message_chain_truncation():
    """Should truncate long chain commands."""
    long_commands = [
        "echo 'this is a very long command that exceeds thirty characters'",
        "second command",
        "third command",
        "fourth command",
        "fifth command",
    ]

    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "..."}',
        project_path="/home/user/project",
        session_id="session-123",
        is_chain=True,
        chain_commands=long_commands,
    )

    assert "5 commands" in msg
    assert "(+2 more)" in msg  # 5 - 3 preview = 2 more


def test_format_auto_approval_message_no_project_path():
    """Should use session ID when no project path."""
    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "ls"}',
        project_path=None,
        session_id="abc12345-long-session-id",
    )

    assert "abc12345" in msg  # First 8 chars of session ID
    assert "Auto-approved" in msg


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
