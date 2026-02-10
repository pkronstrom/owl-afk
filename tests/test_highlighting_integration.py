"""Integration tests for syntax highlighting feature end-to-end."""

from owl.notifiers.telegram import format_approval_message
from owl.utils.formatting import format_auto_approval_message
from owl.utils.results import format_tool_result


def test_bash_python_full_flow():
    """Full flow: approval message + result for a python command."""
    msg = format_approval_message(
        request_id="r1",
        session_id="s1",
        tool_name="Bash",
        tool_input='{"command": "python train.py"}',
        project_path="/home/user/ml-project",
    )
    assert '<pre><code class="language-python">' in msg
    assert "python train.py" in msg

    result = format_tool_result(
        "Bash",
        '{"command": "python train.py"}',
        {"stdout": "Epoch 1: loss=0.5\nEpoch 2: loss=0.3", "exit_code": 0},
    )
    assert '<pre><code class="language-python">' in result
    assert "loss=0.3" in result

    combined = f"{msg}\n─────────\n{result}"
    assert len(combined) < 4096


def test_bash_git_fallback():
    """Git commands should fall back to bash highlighting."""
    msg = format_approval_message(
        request_id="r1",
        session_id="s1",
        tool_name="Bash",
        tool_input='{"command": "git status"}',
        project_path="/home/user/project",
    )
    assert '<pre><code class="language-bash">' in msg


def test_edit_tool_full_flow():
    """Full flow: approval message + success for edit."""
    msg = format_approval_message(
        request_id="r1",
        session_id="s1",
        tool_name="Edit",
        tool_input='{"file_path": "src/app.py", "old_string": "x", "new_string": "y"}',
        project_path="/home/user/project",
    )
    assert '<pre><code class="language-python">' in msg

    result = format_tool_result(
        "Edit",
        '{"file_path": "src/app.py"}',
        {"success": True},
    )
    assert "\u2713" in result

    combined = f"{msg}\n───────── {result}"
    assert len(combined) < 4096


def test_auto_approval_highlighting():
    """Auto-approval notifications should also be highlighted."""
    msg = format_auto_approval_message(
        tool_name="Bash",
        tool_input='{"command": "cargo test"}',
        project_path="/home/user/rust-project",
        session_id="s1",
    )
    assert '<pre><code class="language-rust">' in msg
    assert "cargo test" in msg


def test_bash_result_with_error():
    """Failed bash command should show exit code."""
    result = format_tool_result(
        "Bash",
        '{"command": "python fail.py"}',
        {"stdout": "Traceback:\n  File fail.py\nNameError: x", "exit_code": 1},
    )
    assert "Traceback" in result
    assert "exit code 1" in result


def test_unknown_tool_uses_pre_block():
    """All tools should use <pre><code> blocks for highlighting."""
    msg = format_approval_message(
        request_id="r1",
        session_id="s1",
        tool_name="WebSearch",
        tool_input='{"query": "hello world"}',
    )
    assert "<pre>" in msg
    assert '<code class="language-bash">' in msg
