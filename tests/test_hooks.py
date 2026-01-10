"""Tests for Claude Code hook handlers."""

import pytest

from pyafk.hooks.pretool import handle_pretool_use


@pytest.mark.asyncio
async def test_pretool_approve_by_rule(mock_pyafk_dir):
    """PreToolUse should auto-approve by rule."""
    (mock_pyafk_dir / "mode").write_text("on")

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "session_id": "session-123",
    }

    from pyafk.core.manager import ApprovalManager

    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()
    await manager.rules.add_rule("Bash(git *)", "approve")
    await manager.close()

    result = await handle_pretool_use(hook_input, mock_pyafk_dir)

    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


@pytest.mark.asyncio
async def test_pretool_off_mode_fallback(mock_pyafk_dir):
    """PreToolUse should return empty dict (fallback to CLI) when mode is off."""
    (mock_pyafk_dir / "mode").write_text("off")

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /"},
        "session_id": "session-123",
    }

    result = await handle_pretool_use(hook_input, mock_pyafk_dir)

    # When mode is off, hook returns empty dict to fall back to Claude's CLI approval
    assert result == {}


@pytest.mark.asyncio
async def test_pretool_extracts_context(mock_pyafk_dir):
    """PreToolUse should extract context from hook input."""
    (mock_pyafk_dir / "mode").write_text("on")

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "ls", "description": "List files"},
        "session_id": "session-123",
        "tool_context": "User wants to see directory contents",
    }

    from pyafk.core.manager import ApprovalManager

    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()
    await manager.rules.add_rule("Bash(*)", "approve")
    await manager.close()

    result = await handle_pretool_use(hook_input, mock_pyafk_dir)

    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
