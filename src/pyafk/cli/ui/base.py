"""Base protocol for menu UI."""

from typing import Optional, Protocol


class MenuUI(Protocol):
    """Protocol for menu implementations.

    Allows swapping menu backends if needed.
    """

    def select(
        self,
        options: list[str],
        title: str = "",
    ) -> Optional[int]:
        """Show selection menu, return selected index or None if cancelled."""
        ...

    def confirm(self, message: str) -> bool:
        """Show yes/no confirmation, return True for yes."""
        ...

    def input(self, prompt: str, default: str = "") -> Optional[str]:
        """Get text input, return value or None if cancelled."""
        ...
