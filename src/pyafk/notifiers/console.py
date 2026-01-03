"""Console notifier for testing and local use."""

import asyncio
from typing import Optional

from pyafk.notifiers.base import Notifier


class ConsoleNotifier(Notifier):
    """Simple console-based notifier for testing."""

    def __init__(self, auto_response: Optional[str] = None):
        """Initialize console notifier.

        Args:
            auto_response: If set, automatically return this response
                          ("approve" or "deny") without waiting.
        """
        self.auto_response = auto_response
        self._message_counter = 0

    async def send_approval_request(
        self,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[int]:
        """Print approval request to console."""
        self._message_counter += 1

        print("\n" + "=" * 50)
        print(f"APPROVAL REQUEST [{request_id}]")
        print("=" * 50)
        print(f"Session: {session_id}")
        print(f"Tool: {tool_name}")
        if description:
            print(f"Description: {description}")
        if tool_input:
            print(f"Input: {tool_input[:200]}...")
        if context:
            print(f"Context: {context}")
        print("=" * 50 + "\n")

        return self._message_counter

    async def wait_for_response(
        self,
        request_id: str,
        timeout: int,
    ) -> Optional[str]:
        """Wait for response (or return auto_response)."""
        if self.auto_response:
            return self.auto_response

        await asyncio.sleep(timeout)
        return None

    async def send_status_update(
        self,
        session_id: str,
        status: str,
        details: Optional[dict] = None,
    ):
        """Print status update."""
        print(f"[STATUS] Session {session_id}: {status}")
        if details:
            print(f"  Details: {details}")
