"""Tests for approval handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from owl.core.handlers.base import CallbackContext
from owl.core.handlers.approval import ApproveHandler, DenyHandler


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.get_request = AsyncMock()
    storage.resolve_request = AsyncMock()
    storage.get_session = AsyncMock()
    storage.log_audit = AsyncMock()
    return storage


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.answer_callback = AsyncMock()
    notifier.edit_message = AsyncMock()
    return notifier


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.id = "req123"
    request.session_id = "sess456"
    request.tool_name = "Bash"
    request.tool_input = '{"command": "git status"}'
    request.telegram_msg_id = 789
    request.status = "pending"
    return request


@pytest.mark.asyncio
async def test_approve_handler_resolves_request(
    mock_storage, mock_notifier, mock_request
):
    """Test ApproveHandler resolves request as approved."""
    mock_storage.get_request.return_value = mock_request
    mock_storage.get_session.return_value = MagicMock(project_path="/test/project")

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = ApproveHandler()
    await handler.handle(ctx)

    mock_storage.resolve_request.assert_called_once()
    call_kwargs = mock_storage.resolve_request.call_args.kwargs
    assert call_kwargs["request_id"] == "req123"
    assert call_kwargs["status"] == "approved"


@pytest.mark.asyncio
async def test_deny_handler_resolves_request(mock_storage, mock_notifier, mock_request):
    """Test DenyHandler resolves request as denied."""
    mock_storage.get_request.return_value = mock_request
    mock_storage.get_session.return_value = MagicMock(project_path="/test/project")

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = DenyHandler()
    await handler.handle(ctx)

    mock_storage.resolve_request.assert_called_once()
    call_kwargs = mock_storage.resolve_request.call_args.kwargs
    assert call_kwargs["status"] == "denied"


@pytest.mark.asyncio
async def test_approve_handler_handles_missing_request(mock_storage, mock_notifier):
    """Test ApproveHandler handles missing request gracefully."""
    mock_storage.get_request.return_value = None

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = ApproveHandler()
    await handler.handle(ctx)  # Should not raise

    mock_notifier.answer_callback.assert_called()
    mock_notifier.edit_message.assert_called()


@pytest.mark.asyncio
async def test_approve_handler_answers_callback(
    mock_storage, mock_notifier, mock_request
):
    """Test ApproveHandler answers callback."""
    mock_storage.get_request.return_value = mock_request
    mock_storage.get_session.return_value = MagicMock(project_path="/test/project")

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = ApproveHandler()
    await handler.handle(ctx)

    # Handler no longer calls answer_callback (poller answers immediately)
    # Just verify it edited the message
    mock_notifier.edit_message.assert_called()


@pytest.mark.asyncio
async def test_deny_handler_answers_callback(mock_storage, mock_notifier, mock_request):
    """Test DenyHandler answers callback."""
    mock_storage.get_request.return_value = mock_request
    mock_storage.get_session.return_value = MagicMock(project_path="/test/project")

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = DenyHandler()
    await handler.handle(ctx)

    # Handler no longer calls answer_callback (poller answers immediately)
    # Just verify it edited the message
    mock_notifier.edit_message.assert_called()


@pytest.mark.asyncio
async def test_approve_handler_logs_audit(mock_storage, mock_notifier, mock_request):
    """Test ApproveHandler logs audit event."""
    mock_storage.get_request.return_value = mock_request
    mock_storage.get_session.return_value = MagicMock(project_path="/test/project")

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = ApproveHandler()
    await handler.handle(ctx)

    mock_storage.log_audit.assert_called_once()
    call_kwargs = mock_storage.log_audit.call_args.kwargs
    assert call_kwargs["event_type"] == "response"
    assert call_kwargs["details"]["action"] == "approve"
