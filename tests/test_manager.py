"""Tests for ApprovalManager."""

import pytest

from pyafk.core.manager import ApprovalManager


@pytest.mark.asyncio
async def test_manager_auto_approve_by_rule(mock_pyafk_dir):
    """Manager should auto-approve based on rules."""
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    await manager.rules.add_rule("Bash(git *)", "approve")

    result = await manager.request_approval(
        session_id="session-123",
        tool_name="Bash",
        tool_input='{"command": "git status"}',
    )

    assert result == "approve"
    await manager.close()


@pytest.mark.asyncio
async def test_manager_auto_deny_by_rule(mock_pyafk_dir):
    """Manager should auto-deny based on rules."""
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    await manager.rules.add_rule("Bash(rm *)", "deny")

    result = await manager.request_approval(
        session_id="session-123",
        tool_name="Bash",
        tool_input='{"command": "rm -rf /"}',
    )

    assert result == "deny"
    await manager.close()


@pytest.mark.asyncio
async def test_manager_timeout_action(mock_pyafk_dir):
    """Manager should apply timeout action when no response."""
    manager = ApprovalManager(
        pyafk_dir=mock_pyafk_dir,
        timeout=0.1,
        timeout_action="deny",
    )
    await manager.initialize()

    from pyafk.notifiers.console import ConsoleNotifier
    manager.notifier = ConsoleNotifier()

    result = await manager.request_approval(
        session_id="session-123",
        tool_name="Bash",
        tool_input='{"command": "ls"}',
    )

    assert result == "deny"
    await manager.close()


@pytest.mark.asyncio
async def test_manager_tracks_session(mock_pyafk_dir):
    """Manager should track session heartbeat."""
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    await manager.rules.add_rule("Read(*)", "approve")

    await manager.request_approval(
        session_id="session-123",
        tool_name="Read",
        tool_input='{"file_path": "/test.txt"}',
        project_path="/home/user/project",
    )

    session = await manager.storage.get_session("session-123")
    assert session is not None
    assert session.project_path == "/home/user/project"

    await manager.close()
