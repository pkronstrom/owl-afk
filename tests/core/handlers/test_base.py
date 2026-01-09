"""Tests for handler base classes."""


from pyafk.core.handlers.base import CallbackContext


def test_callback_context_has_required_fields():
    """Test CallbackContext has all required fields."""
    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=None,  # Would be Storage in real use
        notifier=None,  # Would be TelegramNotifier in real use
        original_text="test message",
    )
    assert ctx.target_id == "req123"
    assert ctx.callback_id == "cb456"
    assert ctx.message_id == 789
    assert ctx.original_text == "test message"


def test_callback_context_optional_fields():
    """Test CallbackContext optional fields have defaults."""
    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=None,
        storage=None,
        notifier=None,
    )
    assert ctx.original_text == ""
    assert ctx.message_id is None


def test_callback_handler_protocol():
    """Test CallbackHandler protocol can be implemented."""

    class TestHandler:
        async def handle(self, ctx: CallbackContext) -> None:
            pass

    handler = TestHandler()
    assert hasattr(handler, "handle")
    # Verify it's callable
    assert callable(handler.handle)
