"""Tests for ApprovalManager."""

import pytest

from pyafk.core.manager import ApprovalManager


@pytest.mark.asyncio
async def test_manager_auto_approve_by_rule(mock_pyafk_dir):
    """Manager should auto-approve based on rules."""
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    await manager.rules.add_rule("Bash(git *)", "approve")

    result, _ = await manager.request_approval(
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

    result, _ = await manager.request_approval(
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

    result, _ = await manager.request_approval(
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


@pytest.mark.asyncio
async def test_auto_approve_notify_sends_message(mock_pyafk_dir):
    """Manager should send info message when auto_approve_notify is enabled."""
    from unittest.mock import AsyncMock

    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    # Enable auto_approve_notify
    manager._config.auto_approve_notify = True

    # Add auto-approve rule
    await manager.rules.add_rule("Bash(git *)", "approve")

    # Mock the notifier's send_info_message
    manager.notifier.send_info_message = AsyncMock()

    result, _ = await manager.request_approval(
        session_id="session-123",
        tool_name="Bash",
        tool_input='{"command": "git status"}',
        project_path="/home/user/project",
    )

    assert result == "approve"
    manager.notifier.send_info_message.assert_called_once()

    # Verify message content
    call_args = manager.notifier.send_info_message.call_args[0][0]
    assert "↻" in call_args  # Auto-approve icon
    assert "[Bash]" in call_args
    assert "git status" in call_args

    await manager.close()


@pytest.mark.asyncio
async def test_auto_approve_notify_disabled_no_message(mock_pyafk_dir):
    """Manager should not send message when auto_approve_notify is disabled."""
    from unittest.mock import AsyncMock

    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    # Ensure auto_approve_notify is disabled (default)
    assert manager._config.auto_approve_notify is False

    # Add auto-approve rule
    await manager.rules.add_rule("Bash(git *)", "approve")

    # Mock the notifier's send_info_message
    manager.notifier.send_info_message = AsyncMock()

    result, _ = await manager.request_approval(
        session_id="session-123",
        tool_name="Bash",
        tool_input='{"command": "git status"}',
    )

    assert result == "approve"
    manager.notifier.send_info_message.assert_not_called()

    await manager.close()


@pytest.mark.asyncio
async def test_auto_approve_notify_not_on_deny(mock_pyafk_dir):
    """Manager should not send notify message for auto-deny rules."""
    from unittest.mock import AsyncMock

    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    # Enable auto_approve_notify
    manager._config.auto_approve_notify = True

    # Add auto-DENY rule
    await manager.rules.add_rule("Bash(rm *)", "deny")

    # Mock the notifier's send_info_message
    manager.notifier.send_info_message = AsyncMock()

    result, _ = await manager.request_approval(
        session_id="session-123",
        tool_name="Bash",
        tool_input='{"command": "rm -rf /"}',
    )

    assert result == "deny"
    manager.notifier.send_info_message.assert_not_called()

    await manager.close()
