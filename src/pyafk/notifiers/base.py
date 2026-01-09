"""Base notifier interface.

This module defines two interfaces:

1. Notifier (ABC) - The minimal interface any notifier must implement.
   Used by ApprovalManager for basic approval flow.

2. TelegramCallbackNotifier (Protocol) - Extended interface for Telegram-specific
   callback handling. Used by callback handlers for interactive UI operations.

The separation allows the core approval flow to work with any notifier,
while handlers that need Telegram-specific features use the protocol.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, Protocol, runtime_checkable


class Notifier(ABC):
    """Abstract base class for notification adapters.

    This is the minimal interface for any notifier implementation.
    Subclasses must implement send_approval_request and wait_for_response.

    For Telegram-specific callback handling, see TelegramCallbackNotifier.
    """

    @abstractmethod
    async def send_approval_request(
        self,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
        project_path: Optional[str] = None,
    ) -> Optional[int]:
        """Send an approval request notification.

        Returns:
            Message ID if applicable (e.g., Telegram message ID)
        """
        pass

    @abstractmethod
    async def wait_for_response(
        self,
        request_id: str,
        timeout: int,
    ) -> Optional[str]:
        """Wait for user response.

        Returns:
            "approve", "deny", or None if timeout
        """
        pass

    async def send_status_update(
        self,
        session_id: str,
        status: str,
        details: Optional[dict] = None,
    ) -> None:
        """Send a status update (optional)."""
        pass

    async def edit_message(
        self,
        message_id: int,
        new_text: str,
    ) -> None:
        """Edit a previously sent message (optional)."""
        pass

    async def close(self) -> None:
        """Clean up resources (optional)."""
        pass


@runtime_checkable
class TelegramCallbackNotifier(Protocol):
    """Protocol for Telegram-specific callback handling.

    This protocol defines the extended interface used by callback handlers
    for interactive Telegram UI operations like inline keyboards, chain
    approvals, and feedback prompts.

    TelegramNotifier implements both Notifier (ABC) and this protocol.
    Handlers type-hint their notifier as TelegramCallbackNotifier when
    they need these Telegram-specific methods.
    """

    # Core callback method
    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Answer a Telegram callback query to dismiss loading state."""
        ...

    # Message operations
    async def edit_message(
        self,
        message_id: int,
        new_text: str,
        remove_keyboard: bool = True,
        parse_mode: Optional[str] = "HTML",
    ) -> None:
        """Edit a sent message with optional keyboard removal."""
        ...

    async def delete_message(self, message_id: int) -> None:
        """Delete a message."""
        ...

    async def send_message(self, text: str) -> Optional[int]:
        """Send a simple text message. Returns message ID if successful."""
        ...

    # Rule keyboard operations
    async def edit_message_with_rule_keyboard(
        self,
        message_id: int,
        original_text: str,
        request_id: str,
        patterns: list[tuple[str, str]],
        callback_prefix: str = "add_rule_pattern",
        cancel_callback: Optional[str] = None,
    ) -> None:
        """Edit message to show rule pattern options as inline keyboard."""
        ...

    async def restore_approval_keyboard(
        self,
        message_id: int,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        project_path: Optional[str] = None,
    ) -> None:
        """Restore the original approval message and keyboard."""
        ...

    # Feedback/continuation prompts
    async def send_feedback_prompt(self, tool_name: str) -> Optional[int]:
        """Send a message asking for denial feedback with force_reply."""
        ...

    async def send_continue_prompt(self) -> Optional[int]:
        """Send a message asking for continuation instructions."""
        ...

    # Chain approval operations
    async def update_chain_progress(
        self,
        message_id: int,
        request_id: str,
        session_id: str,
        commands: list[str],
        current_idx: int,
        approved_indices: list[int],
        project_path: Optional[str] = None,
        description: Optional[str] = None,
        final_approve: bool = False,
        denied: bool = False,
    ) -> None:
        """Update chain approval message with progress markers."""
        ...
