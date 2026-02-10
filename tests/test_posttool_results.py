"""Tests for PostToolUse tool result editing."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from owl.hooks.posttool import handle_posttool_use


@pytest.mark.asyncio
async def test_posttool_edits_message_with_result(tmp_path):
    """When tool_results is enabled, PostToolUse should edit the approval message."""
    owl_dir = tmp_path / ".config" / "owl"
    owl_dir.mkdir(parents=True)

    config_file = owl_dir / "config.json"
    config_file.write_text(json.dumps({
        "telegram_bot_token": "fake-token",
        "telegram_chat_id": "12345",
        "tool_results": True,
    }))
    (owl_dir / "mode").write_text("on")

    hook_input = {
        "session_id": "sess-1",
        "cwd": "/home/user/project",
        "tool_name": "Bash",
        "tool_input": {"command": "python train.py"},
        "tool_response": {"stdout": "Done!", "exit_code": 0},
    }

    with patch("owl.hooks.posttool.Storage") as MockStorage, \
         patch("owl.notifiers.telegram.TelegramNotifier") as MockTelegram:
        mock_storage = AsyncMock()
        MockStorage.return_value = mock_storage
        mock_storage.get_pending_messages.return_value = []

        mock_request = MagicMock()
        mock_request.id = "req-1"
        mock_request.telegram_msg_id = 999
        mock_request.tool_name = "Bash"
        mock_request.tool_input = '{"command": "python train.py"}'
        mock_request.status = "approved"
        mock_request.description = None
        mock_storage.get_latest_resolved_request.return_value = mock_request

        mock_tg = AsyncMock()
        MockTelegram.return_value = mock_tg
        mock_tg.edit_message.return_value = True

        await handle_posttool_use(hook_input, owl_dir=owl_dir)

        mock_tg.edit_message.assert_called_once()
        call_kwargs = mock_tg.edit_message.call_args.kwargs
        assert call_kwargs["message_id"] == 999
        assert "Done!" in call_kwargs["new_text"]
        assert "\u2713" in call_kwargs["new_text"]


@pytest.mark.asyncio
async def test_posttool_skips_results_when_disabled(tmp_path):
    """When tool_results is off, PostToolUse should not edit messages."""
    owl_dir = tmp_path / ".config" / "owl"
    owl_dir.mkdir(parents=True)

    config_file = owl_dir / "config.json"
    config_file.write_text(json.dumps({
        "telegram_bot_token": "fake-token",
        "telegram_chat_id": "12345",
        "tool_results": False,
    }))
    (owl_dir / "mode").write_text("on")

    hook_input = {
        "session_id": "sess-1",
        "cwd": "/home/user/project",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "tool_response": {"stdout": "file.txt", "exit_code": 0},
    }

    with patch("owl.hooks.posttool.Storage") as MockStorage:
        mock_storage = AsyncMock()
        MockStorage.return_value = mock_storage
        mock_storage.get_pending_messages.return_value = []

        await handle_posttool_use(hook_input, owl_dir=owl_dir)

        mock_storage.get_latest_resolved_request.assert_not_called()


@pytest.mark.asyncio
async def test_posttool_skips_unsupported_tools(tmp_path):
    """Should not try to edit for tools we don't show results for."""
    owl_dir = tmp_path / ".config" / "owl"
    owl_dir.mkdir(parents=True)

    config_file = owl_dir / "config.json"
    config_file.write_text(json.dumps({
        "telegram_bot_token": "fake-token",
        "telegram_chat_id": "12345",
        "tool_results": True,
    }))
    (owl_dir / "mode").write_text("on")

    hook_input = {
        "session_id": "sess-1",
        "cwd": "/home/user/project",
        "tool_name": "Read",
        "tool_input": {"file_path": "/some/file"},
        "tool_response": {"content": "file contents"},
    }

    with patch("owl.hooks.posttool.Storage") as MockStorage:
        mock_storage = AsyncMock()
        MockStorage.return_value = mock_storage
        mock_storage.get_pending_messages.return_value = []

        await handle_posttool_use(hook_input, owl_dir=owl_dir)

        mock_storage.get_latest_resolved_request.assert_not_called()
