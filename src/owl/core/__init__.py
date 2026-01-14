"""Core modules for owl.

This package provides:
- ApprovalManager: Main API for approval requests
- Storage: SQLite storage layer
- RulesEngine: Pattern matching and rules
- TelegramPoller: Long-polling for Telegram callbacks
- Command parsing utilities
"""

from owl.core.manager import ApprovalManager
from owl.core.rules import RulesEngine
from owl.core.storage import Storage

__all__ = [
    "ApprovalManager",
    "RulesEngine",
    "Storage",
]
