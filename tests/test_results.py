"""Tests for tool result formatting."""

from owl.utils.results import format_tool_result, should_show_result


def test_should_show_result_bash():
    assert should_show_result("Bash") is True


def test_should_show_result_grep():
    assert should_show_result("Grep") is True


def test_should_show_result_glob():
    assert should_show_result("Glob") is True


def test_should_show_result_edit():
    assert should_show_result("Edit") is True


def test_should_show_result_write():
    assert should_show_result("Write") is True


def test_should_show_result_read():
    assert should_show_result("Read") is False


def test_should_show_result_task():
    assert should_show_result("Task") is False


def test_format_bash_result_with_output():
    result = format_tool_result(
        tool_name="Bash",
        tool_input='{"command": "python train.py"}',
        tool_response={"stdout": "Epoch 1: loss=0.3\nDone.", "exit_code": 0},
    )
    assert "Epoch 1: loss=0.3" in result
    assert "Done." in result
    assert '<pre><code class="language-python">' in result


def test_format_bash_result_nonzero_exit():
    result = format_tool_result(
        tool_name="Bash",
        tool_input='{"command": "python fail.py"}',
        tool_response={"stdout": "Error: file not found", "exit_code": 1},
    )
    assert "exit code 1" in result.lower() or "exit_code: 1" in result


def test_format_bash_result_truncates_long_output():
    long_output = "x" * 4000
    result = format_tool_result(
        tool_name="Bash",
        tool_input='{"command": "cat bigfile"}',
        tool_response={"stdout": long_output, "exit_code": 0},
    )
    assert len(result) <= 3200
    assert "truncated" in result.lower()


def test_format_edit_success():
    result = format_tool_result(
        tool_name="Edit",
        tool_input='{"file_path": "foo.py"}',
        tool_response={"success": True},
    )
    assert "\u2713" in result


def test_format_edit_failure():
    result = format_tool_result(
        tool_name="Edit",
        tool_input='{"file_path": "foo.py"}',
        tool_response={"error": "old_string not found"},
    )
    assert "\u2717" in result
    assert "old_string not found" in result


def test_format_write_success():
    result = format_tool_result(
        tool_name="Write",
        tool_input='{"file_path": "foo.py"}',
        tool_response={"success": True},
    )
    assert "\u2713" in result


def test_format_grep_result():
    result = format_tool_result(
        tool_name="Grep",
        tool_input='{"pattern": "TODO"}',
        tool_response={"content": "src/foo.py:10: # TODO fix this"},
    )
    assert "TODO fix this" in result
