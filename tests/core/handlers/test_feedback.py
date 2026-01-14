"""Tests for feedback handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from owl.core.handlers.base import CallbackContext
from owl.core.handlers.feedback import DenyWithMessageHandler


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.get_request = AsyncMock()
    storage.set_pending_feedback = AsyncMock()
    return storage


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.answer_callback = AsyncMock()
    notifier.edit_message = AsyncMock()
    notifier.send_feedback_prompt = AsyncMock(return_value=12345)
    return notifier


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.id = "req123"
    request.tool_name = "Bash"
    return request


@pytest.mark.asyncio
async def test_deny_msg_prompts_feedback(mock_storage, mock_notifier, mock_request):
    """Test DenyWithMessageHandler prompts for feedback."""
    mock_storage.get_request.return_value = mock_request

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = DenyWithMessageHandler()
    await handler.handle(ctx)

    mock_notifier.send_feedback_prompt.assert_called_once_with("Bash")
    mock_storage.set_pending_feedback.assert_called_once_with(12345, "req123")
    mock_notifier.answer_callback.assert_called_with("cb456", "Reply with feedback")


@pytest.mark.asyncio
async def test_deny_msg_handles_missing_request(mock_storage, mock_notifier):
    """Test DenyWithMessageHandler handles missing request."""
    mock_storage.get_request.return_value = None

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = DenyWithMessageHandler()
    await handler.handle(ctx)

    mock_notifier.answer_callback.assert_called_with("cb456", "Request not found")
    mock_notifier.edit_message.assert_called()
