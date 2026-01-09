"""Tests for rule handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from pyafk.core.handlers.base import CallbackContext
from pyafk.core.handlers.rules import CancelRuleHandler


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.get_request = AsyncMock()
    return storage


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.answer_callback = AsyncMock()
    notifier.edit_message = AsyncMock()
    notifier.restore_approval_keyboard = AsyncMock()
    return notifier


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.id = "req123"
    request.session_id = "sess456"
    request.tool_name = "Bash"
    request.tool_input = '{"command": "git status"}'
    return request


@pytest.mark.asyncio
async def test_cancel_rule_restores_keyboard(mock_storage, mock_notifier, mock_request):
    """Test CancelRuleHandler restores approval keyboard."""
    mock_storage.get_request.return_value = mock_request

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = CancelRuleHandler()
    await handler.handle(ctx)

    mock_notifier.answer_callback.assert_called_with("cb456", "Cancelled")
    mock_notifier.restore_approval_keyboard.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_rule_handles_missing_request(mock_storage, mock_notifier):
    """Test CancelRuleHandler handles missing request."""
    mock_storage.get_request.return_value = None

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = CancelRuleHandler()
    await handler.handle(ctx)

    mock_notifier.answer_callback.assert_called_with("cb456", "Request not found")
    mock_notifier.edit_message.assert_called()
