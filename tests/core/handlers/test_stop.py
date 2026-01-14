"""Tests for stop handlers."""

import pytest
from unittest.mock import AsyncMock

from owl.core.handlers.base import CallbackContext
from owl.core.handlers.stop import StopOkHandler, StopCommentHandler


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.resolve_stop = AsyncMock()
    storage.set_stop_comment_prompt = AsyncMock()
    return storage


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.answer_callback = AsyncMock()
    notifier.edit_message = AsyncMock()
    notifier.send_continue_prompt = AsyncMock(return_value=12345)
    return notifier


@pytest.mark.asyncio
async def test_stop_ok_resolves(mock_storage, mock_notifier):
    """Test StopOkHandler resolves stop."""
    ctx = CallbackContext(
        target_id="session123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = StopOkHandler()
    await handler.handle(ctx)

    mock_storage.resolve_stop.assert_called_once_with("session123", "ok")
    mock_notifier.answer_callback.assert_called_with("cb456", "OK")
    mock_notifier.edit_message.assert_called()


@pytest.mark.asyncio
async def test_stop_comment_prompts(mock_storage, mock_notifier):
    """Test StopCommentHandler prompts for message."""
    ctx = CallbackContext(
        target_id="session123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = StopCommentHandler()
    await handler.handle(ctx)

    mock_notifier.send_continue_prompt.assert_called_once()
    mock_storage.set_stop_comment_prompt.assert_called_once_with("session123", 12345)
    mock_notifier.edit_message.assert_called()
