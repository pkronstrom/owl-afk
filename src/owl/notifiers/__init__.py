"""Notification adapters.

This package provides:
- Notifier: Base ABC for any notifier implementation
- TelegramCallbackNotifier: Protocol for Telegram-specific callback handling
- TelegramNotifier: Full Telegram Bot API implementation
- ConsoleNotifier: Simple console notifier for testing
"""

from owl.notifiers.base import Notifier, TelegramCallbackNotifier
from owl.notifiers.console import ConsoleNotifier
from owl.notifiers.telegram import TelegramNotifier

__all__ = ["Notifier", "TelegramCallbackNotifier", "ConsoleNotifier", "TelegramNotifier"]
