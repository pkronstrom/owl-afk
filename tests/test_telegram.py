"""Tests for Telegram notifier."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from owl.notifiers.telegram import TelegramNotifier, format_approval_message


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
    assert "user/myproject" in msg  # last 2 path components


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


@pytest.mark.asyncio
async def test_telegram_chain_approval_request():
    """Should send chain approval request with stacked commands."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 99}}

        msg_id = await notifier.send_chain_approval_request(
            request_id="req-456",
            session_id="session-789",
            commands=["cd ~/projects", "npm test", "git commit -m 'test'"],
            project_path="/home/user/myproject",
            description="Run tests and commit",
        )

        assert msg_id == 99
        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert "sendMessage" in call_args[0][0]

        # Check message content
        data = call_args[1]["data"]
        text = data["text"]
        assert "Command chain approval:" in text
        assert "cd ~/projects" in text
        assert "npm test" in text
        assert "git commit" in text
        assert "→" in text  # First command marker

        # Check keyboard
        markup = json.loads(data["reply_markup"])
        assert "inline_keyboard" in markup
        keyboard = markup["inline_keyboard"]
        # Should have buttons for first command
        assert any("chain_approve:req-456:0" in str(row) for row in keyboard)


@pytest.mark.asyncio
async def test_telegram_update_chain_progress():
    """Should update chain progress with markers."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True}

        await notifier.update_chain_progress(
            message_id=99,
            request_id="req-456",
            session_id="session-789",
            commands=["cd ~/projects", "npm test", "git commit -m 'test'"],
            current_idx=1,
            approved_indices=[0],
            project_path="/home/user/myproject",
        )

        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert "editMessageText" in call_args[0][0]

        # Check message content
        data = call_args[1]["data"]
        text = data["text"]
        assert "✓" in text  # First command approved
        assert "→" in text  # Current command marker
        assert "cd ~/projects" in text
        assert "npm test" in text

        # Check keyboard for current command
        markup = json.loads(data["reply_markup"])
        keyboard = markup["inline_keyboard"]
        assert any("chain_approve:req-456:1" in str(row) for row in keyboard)


@pytest.mark.asyncio
async def test_telegram_chain_final_approve():
    """Should show final approval button when all commands approved."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True}

        await notifier.update_chain_progress(
            message_id=99,
            request_id="req-456",
            session_id="session-789",
            commands=["cd ~/projects", "npm test"],
            current_idx=1,
            approved_indices=[0, 1],
            final_approve=True,
        )

        data = mock_api.call_args[1]["data"]
        markup = json.loads(data["reply_markup"])
        keyboard = markup["inline_keyboard"]
        # Should have "Approve All" button
        assert any("chain_approve_all" in str(row) for row in keyboard)


@pytest.mark.asyncio
async def test_telegram_chain_denied():
    """Should show denied state with no keyboard."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True}

        await notifier.update_chain_progress(
            message_id=99,
            request_id="req-456",
            session_id="session-789",
            commands=["cd ~/projects", "npm test"],
            current_idx=1,
            approved_indices=[0],
            denied=True,
        )

        data = mock_api.call_args[1]["data"]
        markup = json.loads(data["reply_markup"])
        # Should have empty keyboard
        assert markup["inline_keyboard"] == []


@pytest.mark.asyncio
async def test_chain_approval_empty_commands_raises():
    """Should raise ValueError for empty commands list."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with pytest.raises(ValueError, match="empty commands"):
        await notifier.send_chain_approval_request(
            request_id="req-123",
            session_id="session-456",
            commands=[],
        )


@pytest.mark.asyncio
async def test_update_chain_progress_invalid_index_raises():
    """Should raise ValueError for invalid current_idx."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    commands = ["cmd1", "cmd2", "cmd3"]

    # Test negative index
    with pytest.raises(ValueError, match="out of bounds"):
        await notifier.update_chain_progress(
            message_id=99,
            request_id="req-456",
            session_id="session-789",
            commands=commands,
            current_idx=-1,
            approved_indices=[],
        )

    # Test index too large
    with pytest.raises(ValueError, match="out of bounds"):
        await notifier.update_chain_progress(
            message_id=99,
            request_id="req-456",
            session_id="session-789",
            commands=commands,
            current_idx=3,
            approved_indices=[],
        )


@pytest.mark.asyncio
async def test_chain_approval_large_command_list():
    """Should handle large command lists without exceeding message limit."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    # Create 100 commands to trigger truncation
    large_commands = [f"command_{i}" for i in range(100)]

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 99}}

        msg_id = await notifier.send_chain_approval_request(
            request_id="req-456",
            session_id="session-789",
            commands=large_commands,
        )

        assert msg_id == 99
        data = mock_api.call_args[1]["data"]
        text = data["text"]

        # Message should not exceed Telegram limit
        assert len(text) < 4096

        # Should show truncation indicator if truncated
        # (may or may not truncate depending on command length)


@pytest.mark.asyncio
async def test_update_chain_progress_large_command_list():
    """Should handle large command lists in updates without exceeding message limit."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    # Create 100 commands to trigger truncation
    large_commands = [f"command_{i}" for i in range(100)]

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True}

        await notifier.update_chain_progress(
            message_id=99,
            request_id="req-456",
            session_id="session-789",
            commands=large_commands,
            current_idx=50,
            approved_indices=list(range(50)),
        )

        data = mock_api.call_args[1]["data"]
        text = data["text"]

        # Message should not exceed Telegram limit
        assert len(text) < 4096


@pytest.mark.asyncio
async def test_chain_approval_with_compound_title():
    """Should display custom title for compound commands (for/while/if)."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        # Send with compound command title
        msg_id = await notifier.send_chain_approval_request(
            request_id="req-compound",
            session_id="session-123",
            commands=["rm $f", "echo done"],
            chain_title="For: for f in *.log",
        )

        assert msg_id == 42
        data = mock_api.call_args[1]["data"]
        text = data["text"]

        # Should show the compound title instead of "Command chain approval:"
        assert "For: for f in *.log" in text
        assert "Command chain approval:" not in text
        # Should still show the inner commands
        assert "rm $f" in text
        assert "echo done" in text


@pytest.mark.asyncio
async def test_chain_approval_without_title_shows_default():
    """Should show default title when no chain_title is provided."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 43}}

        # Send without compound command title
        msg_id = await notifier.send_chain_approval_request(
            request_id="req-chain",
            session_id="session-456",
            commands=["git add .", "git commit -m 'test'"],
        )

        assert msg_id == 43
        data = mock_api.call_args[1]["data"]
        text = data["text"]

        # Should show the default chain title
        assert "Command chain approval:" in text
        # Should show the commands
        assert "git add ." in text
        assert "git commit" in text
