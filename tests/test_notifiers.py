"""Tests for notifier interface."""

import pytest

from pyafk.notifiers.base import Notifier
from pyafk.notifiers.console import ConsoleNotifier


def test_console_notifier_is_notifier():
    """ConsoleNotifier should implement Notifier."""
    notifier = ConsoleNotifier()
    assert isinstance(notifier, Notifier)


@pytest.mark.asyncio
async def test_console_notifier_send(capsys):
    """ConsoleNotifier should print to stdout."""
    notifier = ConsoleNotifier()

    msg_id = await notifier.send_approval_request(
        request_id="req-123",
        session_id="session-456",
        tool_name="Bash",
        tool_input='{"command": "ls"}',
        context="List files",
        description="Running ls command",
    )

    captured = capsys.readouterr()
    assert "[Bash]" in captured.out
    assert msg_id is not None


@pytest.mark.asyncio
async def test_console_notifier_auto_approve():
    """ConsoleNotifier in auto mode should return approve."""
    notifier = ConsoleNotifier(auto_response="approve")

    response = await notifier.wait_for_response("req-123", timeout=1)
    assert response == "approve"
