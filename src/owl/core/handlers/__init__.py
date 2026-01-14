"""Callback handlers for Telegram interactions.

This module provides:
- CallbackContext: Data passed to handlers
- CallbackHandler: Protocol for handler implementations
- HandlerDispatcher: Routes callbacks to appropriate handlers
- Various handler classes for different callback actions
"""

from owl.core.handlers.approval import ApproveHandler, DenyHandler
from owl.core.handlers.base import CallbackContext, CallbackHandler
from owl.core.handlers.dispatcher import HandlerDispatcher
from owl.core.handlers.feedback import DenyWithMessageHandler
from owl.core.handlers.stop import StopCommentHandler, StopOkHandler
from owl.core.handlers.subagent import SubagentContinueHandler, SubagentOkHandler

__all__ = [
    "CallbackContext",
    "CallbackHandler",
    "HandlerDispatcher",
    "ApproveHandler",
    "DenyHandler",
    "DenyWithMessageHandler",
    "SubagentOkHandler",
    "SubagentContinueHandler",
    "StopOkHandler",
    "StopCommentHandler",
]
