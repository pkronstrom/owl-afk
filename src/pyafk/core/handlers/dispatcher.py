"""Handler dispatcher for routing callbacks to appropriate handlers."""

from typing import TYPE_CHECKING, Optional

from pyafk.core.handlers.approval import ApproveHandler, DenyHandler
from pyafk.core.handlers.base import CallbackContext, CallbackHandler
from pyafk.utils.debug import debug_callback

if TYPE_CHECKING:
    from pyafk.core.storage import Storage
    from pyafk.notifiers.base import TelegramCallbackNotifier


class HandlerDispatcher:
    """Routes callback data to appropriate handlers.

    This class replaces the large if-elif chain in poller.py's _handle_callback
    method with a dispatch table pattern. Each action type maps to a handler
    class that implements the CallbackHandler protocol.

    Attributes:
        storage: Database storage instance
        notifier: Notifier implementing TelegramCallbackNotifier protocol
        _handlers: Registry mapping action strings to handler instances

    Example:
        dispatcher = HandlerDispatcher(storage, notifier)
        await dispatcher.dispatch("approve:req123", "cb456", 789)
    """

    def __init__(
        self,
        storage: "Storage",
        notifier: "TelegramCallbackNotifier",
    ) -> None:
        self.storage = storage
        self.notifier = notifier

        # Import handlers here to avoid import issues
        from pyafk.core.handlers.batch import ApproveAllHandler
        from pyafk.core.handlers.chain import (
            ChainApproveAllHandler,
            ChainApproveEntireHandler,
            ChainApproveHandler,
            ChainCancelRuleHandler,
            ChainDenyHandler,
            ChainDenyMsgHandler,
            ChainRuleHandler,
            ChainRulePatternHandler,
        )
        from pyafk.core.handlers.feedback import DenyWithMessageHandler
        from pyafk.core.handlers.rules import (
            AddRuleMenuHandler,
            AddRulePatternHandler,
            CancelRuleHandler,
        )
        from pyafk.core.handlers.stop import StopCommentHandler, StopOkHandler
        from pyafk.core.handlers.subagent import (
            SubagentContinueHandler,
            SubagentOkHandler,
        )

        # Register handlers
        self._handlers: dict[str, CallbackHandler] = {
            "approve": ApproveHandler(),
            "deny": DenyHandler(),
            "deny_msg": DenyWithMessageHandler(),
            "subagent_ok": SubagentOkHandler(),
            "subagent_continue": SubagentContinueHandler(),
            "stop_ok": StopOkHandler(),
            "stop_comment": StopCommentHandler(),
            "add_rule": AddRuleMenuHandler(),
            "add_rule_pattern": AddRulePatternHandler(),
            "cancel_rule": CancelRuleHandler(),
            "approve_all": ApproveAllHandler(),
            # Chain handlers
            "chain_approve": ChainApproveHandler(),
            "chain_deny": ChainDenyHandler(),
            "chain_deny_msg": ChainDenyMsgHandler(),
            "chain_approve_all": ChainApproveAllHandler(),
            "chain_approve_entire": ChainApproveEntireHandler(),
            "chain_cancel_rule": ChainCancelRuleHandler(),
            "chain_rule": ChainRuleHandler(),
            "chain_rule_pattern": ChainRulePatternHandler(),
        }

    async def dispatch(
        self,
        callback_data: str,
        callback_id: str,
        message_id: Optional[int],
        original_text: str = "",
    ) -> None:
        """Dispatch callback to appropriate handler.

        Parses the callback_data to extract the action and target_id,
        then routes to the registered handler for that action.

        Args:
            callback_data: The callback_data from Telegram button (e.g., "approve:req123")
            callback_id: Telegram callback query ID
            message_id: Telegram message ID
            original_text: Original message text for restoration
        """
        if ":" not in callback_data:
            debug_callback("Invalid callback data format", data=callback_data)
            return

        # Split only on first colon to preserve compound target IDs
        action, target_id = callback_data.split(":", 1)
        debug_callback("Dispatching callback", action=action, target_id=target_id[:20])

        handler = self._handlers.get(action)
        if handler is None:
            debug_callback("No handler for action", action=action)
            return

        ctx = CallbackContext(
            target_id=target_id,
            callback_id=callback_id,
            message_id=message_id,
            storage=self.storage,
            notifier=self.notifier,
            original_text=original_text,
        )

        await handler.handle(ctx)

    def register(self, action: str, handler: CallbackHandler) -> None:
        """Register a handler for an action.

        Use this to add custom handlers or override default handlers.

        Args:
            action: The action string (e.g., "approve", "deny", "add_rule")
            handler: Handler instance implementing CallbackHandler protocol
        """
        self._handlers[action] = handler
