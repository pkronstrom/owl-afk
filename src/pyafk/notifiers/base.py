"""Base notifier interface."""

from abc import ABC, abstractmethod
from typing import Optional


class Notifier(ABC):
    """Abstract base class for notification adapters."""

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
    ):
        """Send a status update (optional)."""
        pass

    async def edit_message(
        self,
        message_id: int,
        new_text: str,
    ):
        """Edit a previously sent message (optional)."""
        pass
