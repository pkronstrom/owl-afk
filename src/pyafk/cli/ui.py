"""UI utilities for CLI - console, styles, screen helpers."""

import os

from questionary import Style
from rich.console import Console
from rich.panel import Panel

from pyafk.utils.config import Config, get_pyafk_dir

console = Console()

# Custom style for questionary
custom_style = Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "fg:white bold"),
        ("answer", "fg:cyan"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("separator", "fg:gray"),
        ("instruction", "fg:gray"),
    ]
)


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def section_header(title: str, width: int = 40):
    """Print a dim section header like ── General ──"""
    padding = (width - len(title) - 4) // 2
    left = "─" * padding
    right = "─" * (width - len(title) - 4 - padding)
    console.print(f"[dim]{left} {title} {right}[/dim]")


def print_header():
    """Print the application header."""
    console.print(
        Panel(
            "[bold cyan]pyafk[/bold cyan]\n[dim]Remote approval for Claude Code[/dim]",
            border_style="cyan",
        )
    )
    console.print()


def print_status_inline():
    """Print compact status info."""
    from pyafk.cli.install import check_hooks_installed

    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)
    mode = config.get_mode()

    # Build status parts
    parts = []
    parts.append(f"[{'green' if mode == 'on' else 'yellow'}]{mode}[/]")

    if config.telegram_bot_token and config.telegram_chat_id:
        parts.append("[green]tg[/green]")
    else:
        parts.append("[dim]tg[/dim]")

    from pyafk.daemon import is_daemon_running

    if is_daemon_running(pyafk_dir):
        parts.append("[green]daemon[/green]")

    hooks_installed, hooks_mode = check_hooks_installed()
    if hooks_installed:
        parts.append(f"[green]{hooks_mode}[/green]")

    console.print(f"[dim]Status:[/dim] {' | '.join(parts)}")
    console.print()
