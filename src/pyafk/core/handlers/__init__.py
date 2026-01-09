"""Callback handlers for Telegram interactions.

This module provides:
- CallbackContext: Data passed to handlers
- CallbackHandler: Protocol for handler implementations
- ApproveHandler, DenyHandler: Approval/denial handlers
"""

from pyafk.core.handlers.approval import ApproveHandler, DenyHandler
from pyafk.core.handlers.base import CallbackContext, CallbackHandler

__all__ = [
    "CallbackContext",
    "CallbackHandler",
    "ApproveHandler",
    "DenyHandler",
]
