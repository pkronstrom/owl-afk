"""Notification adapters.

This package provides:
- Notifier: Base ABC for any notifier implementation
- TelegramCallbackNotifier: Protocol for Telegram-specific callback handling
- TelegramNotifier: Full Telegram Bot API implementation
- ConsoleNotifier: Simple console notifier for testing
"""

from pyafk.notifiers.base import Notifier, TelegramCallbackNotifier
from pyafk.notifiers.console import ConsoleNotifier
from pyafk.notifiers.telegram import TelegramNotifier

__all__ = ["Notifier", "TelegramCallbackNotifier", "ConsoleNotifier", "TelegramNotifier"]
