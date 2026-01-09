"""Core modules for pyafk.

This package provides:
- ApprovalManager: Main API for approval requests
- Storage: SQLite storage layer
- RulesEngine: Pattern matching and rules
- TelegramPoller: Long-polling for Telegram callbacks
- Command parsing utilities
"""

from pyafk.core.manager import ApprovalManager
from pyafk.core.rules import RulesEngine
from pyafk.core.storage import Storage

__all__ = [
    "ApprovalManager",
    "RulesEngine",
    "Storage",
]
