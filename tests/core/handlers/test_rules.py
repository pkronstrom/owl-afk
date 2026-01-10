"""Tests for rule handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from pyafk.core.handlers.base import CallbackContext
from pyafk.core.handlers.rules import (
    CancelRuleHandler,
)


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.get_request = AsyncMock()
    storage.get_session = AsyncMock()
    storage.resolve_request = AsyncMock()
    return storage


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.answer_callback = AsyncMock()
    notifier.edit_message = AsyncMock()
    notifier.restore_approval_keyboard = AsyncMock()
    notifier.edit_message_with_rule_keyboard = AsyncMock()
    return notifier


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.id = "req123"
    request.session_id = "sess456"
    request.tool_name = "Bash"
    request.tool_input = '{"command": "git status"}'
    return request


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.project_path = "/home/user/project"
    return session


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


# AddRuleMenuHandler tests


@pytest.mark.asyncio
async def test_add_rule_menu_shows_patterns(
    mock_storage, mock_notifier, mock_request, mock_session
):
    """Test AddRuleMenuHandler shows pattern options."""
    from pyafk.core.handlers.rules import AddRuleMenuHandler

    mock_storage.get_request.return_value = mock_request
    mock_storage.get_session.return_value = mock_session

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
        original_text="Original message",
    )

    handler = AddRuleMenuHandler()
    await handler.handle(ctx)

    mock_notifier.answer_callback.assert_called_with("cb456", "Choose pattern")
    mock_notifier.edit_message_with_rule_keyboard.assert_called_once()


@pytest.mark.asyncio
async def test_add_rule_menu_handles_missing_request(mock_storage, mock_notifier):
    """Test AddRuleMenuHandler handles missing request."""
    from pyafk.core.handlers.rules import AddRuleMenuHandler

    mock_storage.get_request.return_value = None

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = AddRuleMenuHandler()
    await handler.handle(ctx)

    mock_notifier.answer_callback.assert_called_with("cb456", "Request not found")


# AddRulePatternHandler tests


@pytest.mark.asyncio
async def test_add_rule_pattern_creates_rule(
    mock_storage, mock_notifier, mock_request, mock_session
):
    """Test AddRulePatternHandler creates rule and approves request."""
    from unittest.mock import patch
    from pyafk.core.handlers.rules import AddRulePatternHandler

    mock_storage.get_request.return_value = mock_request
    mock_storage.get_session.return_value = mock_session
    # Return the original request in pending list so it gets auto-approved
    mock_storage.get_pending_requests.return_value = [mock_request]

    ctx = CallbackContext(
        target_id="req123:0",  # request_id:pattern_index
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    with patch("pyafk.core.rules.RulesEngine") as mock_engine_class:
        mock_engine = AsyncMock()
        mock_engine_class.return_value = mock_engine
        # Make the engine say the request matches the new rule
        mock_engine.check.return_value = "approve"

        handler = AddRulePatternHandler()
        await handler.handle(ctx)

        # Verify rule was added
        mock_engine.add_rule.assert_called_once()
        # Verify request was auto-approved through the pending request loop
        mock_storage.resolve_request.assert_called_with(
            request_id="req123",
            status="approved",
            resolved_by="user:add_rule:auto",
        )
        mock_notifier.answer_callback.assert_called_with("cb456", "Always rule added")


@pytest.mark.asyncio
async def test_add_rule_pattern_handles_invalid_format(mock_storage, mock_notifier):
    """Test AddRulePatternHandler handles invalid target_id format."""
    from pyafk.core.handlers.rules import AddRulePatternHandler

    ctx = CallbackContext(
        target_id="invalid_no_colon",  # Missing pattern index
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = AddRulePatternHandler()
    await handler.handle(ctx)

    mock_notifier.answer_callback.assert_called_with("cb456", "Invalid format")
