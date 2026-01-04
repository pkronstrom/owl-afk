"""Tests for Telegram notifier."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from pyafk.notifiers.telegram import TelegramNotifier, format_approval_message


def test_format_approval_message():
    """Format message for Telegram."""
    msg = format_approval_message(
        request_id="req-123",
        session_id="session-456",
        tool_name="Bash",
        tool_input='{"command": "git status"}',
        description="Check git status",
        context="User wants to see changes",
        timeout=3600,
        timeout_action="deny",
        project_path="/home/user/myproject",
    )

    assert "[Bash]" in msg
    assert "git status" in msg
    assert "myproject" in msg  # project dir name


def test_format_approval_message_truncates_long_input():
    """Long tool input should be truncated."""
    long_input = json.dumps({"command": "x" * 1000})
    msg = format_approval_message(
        request_id="req-123",
        session_id="s",
        tool_name="Bash",
        tool_input=long_input,
    )

    assert len(msg) < 2000


@pytest.mark.asyncio
async def test_telegram_notifier_send():
    """TelegramNotifier should send via API."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        msg_id = await notifier.send_approval_request(
            request_id="req-123",
            session_id="session-456",
            tool_name="Bash",
            tool_input='{"command": "ls"}',
        )

        assert msg_id == 42
        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert "sendMessage" in call_args[0][0]


@pytest.mark.asyncio
async def test_telegram_notifier_inline_keyboard():
    """Should include inline keyboard with buttons."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        await notifier.send_approval_request(
            request_id="req-123",
            session_id="session-456",
            tool_name="Bash",
            tool_input="{}",
        )

        call_kwargs = mock_api.call_args[1]
        data = call_kwargs.get("data", {})

        assert "reply_markup" in data
        markup = json.loads(data["reply_markup"])
        assert "inline_keyboard" in markup
