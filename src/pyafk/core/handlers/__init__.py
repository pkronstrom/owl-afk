"""Callback handlers for Telegram interactions.

This module provides:
- CallbackContext: Data passed to handlers
- CallbackHandler: Protocol for handler implementations
- HandlerDispatcher: Routes callbacks to appropriate handlers
- ApproveHandler, DenyHandler: Approval/denial handlers
"""

from pyafk.core.handlers.approval import ApproveHandler, DenyHandler
from pyafk.core.handlers.base import CallbackContext, CallbackHandler
from pyafk.core.handlers.dispatcher import HandlerDispatcher

__all__ = [
    "CallbackContext",
    "CallbackHandler",
    "HandlerDispatcher",
    "ApproveHandler",
    "DenyHandler",
]
