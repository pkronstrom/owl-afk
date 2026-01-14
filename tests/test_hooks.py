"""Tests for Claude Code hook handlers."""

import pytest

from owl.hooks.pretool import handle_pretool_use


@pytest.mark.asyncio
async def test_pretool_approve_by_rule(mock_owl_dir):
    """PreToolUse should auto-approve by rule."""
    (mock_owl_dir / "mode").write_text("on")

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "session_id": "session-123",
    }

    from owl.core.manager import ApprovalManager

    manager = ApprovalManager(owl_dir=mock_owl_dir)
    await manager.initialize()
    await manager.rules.add_rule("Bash(git *)", "approve")
    await manager.close()

    result = await handle_pretool_use(hook_input, mock_owl_dir)

    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


@pytest.mark.asyncio
async def test_pretool_off_mode_fallback(mock_owl_dir):
    """PreToolUse should return empty dict (fallback to CLI) when mode is off."""
    (mock_owl_dir / "mode").write_text("off")

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /"},
        "session_id": "session-123",
    }

    result = await handle_pretool_use(hook_input, mock_owl_dir)

    # When mode is off, hook returns empty dict to fall back to Claude's CLI approval
    assert result == {}


@pytest.mark.asyncio
async def test_pretool_extracts_context(mock_owl_dir):
    """PreToolUse should extract context from hook input."""
    (mock_owl_dir / "mode").write_text("on")

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "ls", "description": "List files"},
        "session_id": "session-123",
        "tool_context": "User wants to see directory contents",
    }

    from owl.core.manager import ApprovalManager

    manager = ApprovalManager(owl_dir=mock_owl_dir)
    await manager.initialize()
    await manager.rules.add_rule("Bash(*)", "approve")
    await manager.close()

    result = await handle_pretool_use(hook_input, mock_owl_dir)

    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
