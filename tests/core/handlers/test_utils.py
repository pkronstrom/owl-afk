"""Tests for handler utilities."""

from pyafk.core.handlers.utils import format_resolved_message


class TestFormatResolvedMessage:
    def test_approved_message(self):
        result = format_resolved_message(
            approved=True,
            project_id="own/pyafk",
            tool_name="Bash",
            tool_summary="git status",
        )
        assert "own/pyafk" in result
        assert "Bash" in result
        assert "git status" in result
        assert "✓" in result

    def test_denied_message(self):
        result = format_resolved_message(
            approved=False,
            project_id="own/pyafk",
            tool_name="Edit",
            tool_summary="/path/to/file.py",
        )
        assert "✗" in result
        assert "Edit" in result

    def test_with_rule_label(self):
        result = format_resolved_message(
            approved=True,
            project_id="own/pyafk",
            tool_name="Bash",
            tool_summary="npm test",
            rule_label="Any npm",
        )
        assert "📝" in result
        assert "Any npm" in result
