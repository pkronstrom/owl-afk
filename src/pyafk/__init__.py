"""pyafk - Remote approval system for Claude Code."""

from importlib.metadata import version

__version__ = version("pyafk")

from pyafk.core.manager import ApprovalManager
from pyafk.notifiers import ConsoleNotifier, Notifier, TelegramNotifier

__all__ = [
    "ApprovalManager",
    "Notifier",
    "ConsoleNotifier",
    "TelegramNotifier",
]
