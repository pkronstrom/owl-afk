"""Notification adapters."""

from pyafk.notifiers.base import Notifier
from pyafk.notifiers.console import ConsoleNotifier

__all__ = ["Notifier", "ConsoleNotifier"]
