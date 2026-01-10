"""Tests for handler dispatcher."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pyafk.core.handlers.dispatcher import HandlerDispatcher
from pyafk.core.handlers.registry import HandlerRegistry


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


@pytest.mark.asyncio
async def test_dispatcher_routes_approve(mock_storage, mock_notifier):
    """Test dispatcher routes approve action correctly."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    # Mock the handler via registry
    mock_handler = MagicMock()
    mock_handler.handle = AsyncMock()

    with patch.object(HandlerRegistry, "create", return_value=mock_handler):
        await dispatcher.dispatch("approve:req123", "cb456", 789, "original text")

    mock_handler.handle.assert_called_once()
    ctx = mock_handler.handle.call_args[0][0]
    assert ctx.target_id == "req123"
    assert ctx.callback_id == "cb456"
    assert ctx.message_id == 789


@pytest.mark.asyncio
async def test_dispatcher_routes_deny(mock_storage, mock_notifier):
    """Test dispatcher routes deny action correctly."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    mock_handler = MagicMock()
    mock_handler.handle = AsyncMock()

    with patch.object(HandlerRegistry, "create", return_value=mock_handler):
        await dispatcher.dispatch("deny:req123", "cb456", 789, "")

    mock_handler.handle.assert_called_once()
    ctx = mock_handler.handle.call_args[0][0]
    assert ctx.target_id == "req123"


@pytest.mark.asyncio
async def test_dispatcher_handles_unknown_action(mock_storage, mock_notifier):
    """Test dispatcher handles unknown actions gracefully."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    # Should not raise - unknown action returns None from registry
    await dispatcher.dispatch("unknown_action:req123", "cb456", 789, "")


@pytest.mark.asyncio
async def test_dispatcher_handles_invalid_format(mock_storage, mock_notifier):
    """Test dispatcher handles invalid callback data format."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    # No colon separator - should not raise
    await dispatcher.dispatch("invaliddata", "cb456", 789, "")


@pytest.mark.asyncio
async def test_dispatcher_parses_compound_target(mock_storage, mock_notifier):
    """Test dispatcher parses compound target IDs like session_id:tool_name."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    mock_handler = MagicMock()
    mock_handler.handle = AsyncMock()

    with patch.object(HandlerRegistry, "create", return_value=mock_handler):
        await dispatcher.dispatch("approve_all:sess123:Bash", "cb456", 789, "")

    ctx = mock_handler.handle.call_args[0][0]
    # Should capture everything after action: as target_id
    assert ctx.target_id == "sess123:Bash"


@pytest.mark.asyncio
async def test_dispatcher_register_handler(mock_storage, mock_notifier):
    """Test dispatcher can register new handlers at runtime."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    # Create a mock handler class
    class MockHandler:
        def __init__(self):
            self.handle = AsyncMock()

    # Register the handler class
    dispatcher.register("custom_action", MockHandler)

    # Now dispatch should create and call the handler
    await dispatcher.dispatch("custom_action:test123", "cb456", 789, "")

    # Verify a handler was registered
    assert "custom_action" in HandlerRegistry._handlers

    # Clean up
    del HandlerRegistry._handlers["custom_action"]


@pytest.mark.asyncio
async def test_dispatcher_passes_original_text(mock_storage, mock_notifier):
    """Test dispatcher passes original text to handler."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    mock_handler = MagicMock()
    mock_handler.handle = AsyncMock()

    with patch.object(HandlerRegistry, "create", return_value=mock_handler):
        await dispatcher.dispatch(
            "approve:req123", "cb456", 789, "Original message text"
        )

    ctx = mock_handler.handle.call_args[0][0]
    assert ctx.original_text == "Original message text"


@pytest.mark.asyncio
async def test_dispatcher_uses_registered_handlers(mock_storage, mock_notifier):
    """Test dispatcher uses actual registered handlers from registry."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    # Verify standard handlers are registered
    assert HandlerRegistry.get("approve") is not None
    assert HandlerRegistry.get("deny") is not None
    assert HandlerRegistry.get("add_rule") is not None
    assert HandlerRegistry.get("chain_approve") is not None
