"""Tests for subagent handlers."""

import pytest
from unittest.mock import AsyncMock

from owl.core.handlers.base import CallbackContext
from owl.core.handlers.subagent import SubagentOkHandler, SubagentContinueHandler


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.resolve_subagent = AsyncMock()
    storage.set_subagent_continue_prompt = AsyncMock()
    return storage


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.answer_callback = AsyncMock()
    notifier.edit_message = AsyncMock()
    notifier.send_continue_prompt = AsyncMock(return_value=12345)
    return notifier


@pytest.mark.asyncio
async def test_subagent_ok_resolves(mock_storage, mock_notifier):
    """Test SubagentOkHandler resolves subagent."""
    ctx = CallbackContext(
        target_id="subagent123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = SubagentOkHandler()
    await handler.handle(ctx)

    mock_storage.resolve_subagent.assert_called_once_with("subagent123", "ok")
    mock_notifier.answer_callback.assert_called_with("cb456", "OK")
    mock_notifier.edit_message.assert_called()


@pytest.mark.asyncio
async def test_subagent_continue_prompts(mock_storage, mock_notifier):
    """Test SubagentContinueHandler prompts for instructions."""
    ctx = CallbackContext(
        target_id="subagent123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = SubagentContinueHandler()
    await handler.handle(ctx)

    mock_notifier.send_continue_prompt.assert_called_once()
    mock_storage.set_subagent_continue_prompt.assert_called_once_with(
        "subagent123", 12345
    )
    mock_notifier.edit_message.assert_called()
