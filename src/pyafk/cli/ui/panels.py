"""Live panel utilities for scrolling lists."""

from typing import TypeVar

from rich.console import Console

T = TypeVar("T")

# Refresh rate for live panels (Hz)
LIVE_REFRESH_RATE = 20

console = Console()


def calculate_visible_range(
    cursor: int,
    total_items: int,
    max_visible: int,
    scroll_offset: int = 0,
) -> tuple[int, int, int]:
    """Calculate visible window for scrolling list.

    Args:
        cursor: Current cursor position
        total_items: Total number of items
        max_visible: Maximum items that fit on screen
        scroll_offset: Current scroll offset

    Returns:
        Tuple of (start_idx, end_idx, new_scroll_offset)
    """
    if total_items <= max_visible:
        return 0, total_items, 0

    # Adjust scroll to keep cursor visible
    if cursor < scroll_offset:
        scroll_offset = cursor
    elif cursor >= scroll_offset + max_visible:
        scroll_offset = cursor - max_visible + 1

    start = scroll_offset
    end = min(start + max_visible, total_items)

    return start, end, scroll_offset


def format_scroll_indicator(hidden_above: int, hidden_below: int) -> tuple[str, str]:
    """Format scroll indicators.

    Returns:
        Tuple of (top_indicator, bottom_indicator)
    """
    top = f"↑ {hidden_above} more" if hidden_above > 0 else ""
    bottom = f"↓ {hidden_below} more" if hidden_below > 0 else ""
    return top, bottom


def clear_screen() -> None:
    """Clear terminal screen and hide cursor."""
    print("\033[?25l", end="", flush=True)  # Hide cursor
    console.clear()


def reset_cursor() -> None:
    """Move cursor to home position without clearing.

    This allows overwriting content in place, avoiding flicker.
    Cursor should already be hidden by clear_screen().
    """
    # \033[H = move to home (row 1, col 1)
    print("\033[H", end="", flush=True)


def show_cursor() -> None:
    """Show the cursor (call after rendering)."""
    print("\033[?25h", end="", flush=True)


def get_terminal_size() -> tuple[int, int]:
    """Get terminal width and height."""
    return console.size.width, console.size.height
