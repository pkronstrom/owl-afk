"""Tests for batch approval handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pyafk.core.handlers.base import CallbackContext
from pyafk.core.handlers.batch import ApproveAllHandler


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.get_pending_requests = AsyncMock()
    storage.get_session = AsyncMock()
    storage.resolve_request = AsyncMock()
    return storage


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.answer_callback = AsyncMock()
    notifier.edit_message = AsyncMock()
    return notifier


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.project_path = "/home/user/project"
    return session


@pytest.fixture
def mock_requests():
    """Create mock pending requests."""
    req1 = MagicMock()
    req1.id = "req1"
    req1.session_id = "sess123"
    req1.tool_name = "Bash"
    req1.tool_input = '{"command": "git status"}'
    req1.telegram_msg_id = 100

    req2 = MagicMock()
    req2.id = "req2"
    req2.session_id = "sess123"
    req2.tool_name = "Bash"
    req2.tool_input = '{"command": "git diff"}'
    req2.telegram_msg_id = 101

    req3 = MagicMock()
    req3.id = "req3"
    req3.session_id = "sess456"  # Different session
    req3.tool_name = "Edit"
    req3.tool_input = '{"file_path": "/path/file.py"}'
    req3.telegram_msg_id = 102

    return [req1, req2, req3]


@pytest.mark.asyncio
async def test_approve_all_approves_matching_requests(
    mock_storage, mock_notifier, mock_session, mock_requests
):
    """Test ApproveAllHandler approves requests matching session and tool."""
    mock_storage.get_pending_requests.return_value = mock_requests
    mock_storage.get_session.return_value = mock_session

    ctx = CallbackContext(
        target_id="sess123:Bash",  # session_id:tool_name
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    with patch("pyafk.core.rules.RulesEngine") as mock_engine_class:
        mock_engine = AsyncMock()
        mock_engine_class.return_value = mock_engine

        handler = ApproveAllHandler()
        await handler.handle(ctx)

        # Should approve req1 and req2 (matching session and tool)
        assert mock_storage.resolve_request.call_count == 2
        # Should add rule for Bash
        mock_engine.add_rule.assert_called_once()


@pytest.mark.asyncio
async def test_approve_all_no_tool_filter(
    mock_storage, mock_notifier, mock_session, mock_requests
):
    """Test ApproveAllHandler without tool filter approves all session requests."""
    mock_storage.get_pending_requests.return_value = mock_requests
    mock_storage.get_session.return_value = mock_session

    ctx = CallbackContext(
        target_id="sess123",  # Just session_id, no tool filter
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = ApproveAllHandler()
    await handler.handle(ctx)

    # Should approve req1 and req2 (matching session, any tool)
    assert mock_storage.resolve_request.call_count == 2
    # Should not add rule (no specific tool)
    mock_notifier.answer_callback.assert_called()


@pytest.mark.asyncio
async def test_approve_all_handles_empty_results(mock_storage, mock_notifier):
    """Test ApproveAllHandler handles no matching requests."""
    mock_storage.get_pending_requests.return_value = []

    ctx = CallbackContext(
        target_id="sess999:Bash",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = ApproveAllHandler()
    await handler.handle(ctx)

    # Should still answer callback
    mock_notifier.answer_callback.assert_called()
