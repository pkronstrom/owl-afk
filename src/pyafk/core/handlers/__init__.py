"""Callback handlers for Telegram interactions.

This module provides:
- CallbackContext: Data passed to handlers
- CallbackHandler: Protocol for handler implementations
- HandlerDispatcher: Routes callbacks to appropriate handlers
- Various handler classes for different callback actions
"""

from pyafk.core.handlers.approval import ApproveHandler, DenyHandler
from pyafk.core.handlers.base import CallbackContext, CallbackHandler
from pyafk.core.handlers.dispatcher import HandlerDispatcher
from pyafk.core.handlers.feedback import DenyWithMessageHandler
from pyafk.core.handlers.stop import StopCommentHandler, StopOkHandler
from pyafk.core.handlers.subagent import SubagentContinueHandler, SubagentOkHandler

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
