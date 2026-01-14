"""owl - Remote approval system for Claude Code."""

from importlib.metadata import version

__version__ = version("owl-afk")

from owl.core.manager import ApprovalManager
from owl.notifiers import ConsoleNotifier, Notifier, TelegramNotifier

__all__ = [
    "ApprovalManager",
    "Notifier",
    "ConsoleNotifier",
    "TelegramNotifier",
]
