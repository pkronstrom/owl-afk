"""Interactive menu flows."""

from rich.panel import Panel

from pyafk.cli.ui.menu import RichTerminalMenu
from pyafk.cli.ui.panels import clear_screen, console
from pyafk.utils.config import Config, get_pyafk_dir


def _print_header() -> None:
    """Print application header with status."""
    from pyafk.cli.install import check_hooks_installed
    from pyafk.daemon import is_daemon_running

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

    if is_daemon_running(pyafk_dir):
        parts.append("[green]daemon[/green]")

    hooks_installed, hooks_mode = check_hooks_installed()
    if hooks_installed:
        parts.append(f"[green]{hooks_mode}[/green]")

    status_line = " | ".join(parts)

    console.print(
        Panel(
            "[bold cyan]pyafk[/bold cyan]\n"
            "[dim]Remote approval for Claude Code[/dim]\n\n"
            f"Status: {status_line}",
            border_style="cyan",
        )
    )


def interactive_menu() -> None:
    """Main interactive menu."""
    from pyafk.cli.commands import cmd_install, cmd_off, cmd_on, cmd_uninstall
    from pyafk.cli.install import check_hooks_installed
    from pyafk.cli.helpers import config_exists

    menu = RichTerminalMenu()
    pyafk_dir = get_pyafk_dir()

    # Check for first run
    if not config_exists():
        clear_screen()
        console.print("[bold]First time setup[/bold]\n")
        if menu.confirm("Run setup wizard?", default=True):
            run_wizard()
        return

    while True:
        clear_screen()
        _print_header()
        console.print()

        config = Config(pyafk_dir)
        mode = config.get_mode()
        hooks_installed, _ = check_hooks_installed()

        # Build dynamic menu options
        options = []
        actions = []

        # Toggle on/off
        if mode == "on":
            options.append("Turn off")
            actions.append("off")
        else:
            options.append("Turn on")
            actions.append("on")

        options.append("Manage Rules")
        actions.append("rules")

        options.append("Config")
        actions.append("config")

        # Install/Uninstall (conditional)
        if not hooks_installed:
            options.append("Install hooks")
            actions.append("install")
        else:
            options.append("Uninstall hooks")
            actions.append("uninstall")

        options.append("─────────")
        actions.append(None)

        options.append("Exit")
        actions.append("exit")

        # Show legend
        console.print("[dim]↑↓ navigate • Enter select • q quit[/dim]\n")

        choice_idx = menu.select(options)

        if choice_idx is None:
            break

        action = actions[choice_idx]

        if action is None:  # Separator
            continue
        elif action == "exit":
            break
        elif action == "on":
            cmd_on(None)
        elif action == "off":
            cmd_off(None)
        elif action == "rules":
            interactive_rules()
        elif action == "config":
            interactive_config()
        elif action == "install":
            clear_screen()
            cmd_install(None)
            input("\nPress Enter to continue...")
        elif action == "uninstall":
            clear_screen()
            cmd_uninstall(None)
            break


def interactive_rules() -> None:
    """Interactive rules management - placeholder."""
    console.print("[yellow]Rules menu not yet implemented[/yellow]")
    input("\nPress Enter to continue...")


def interactive_config() -> None:
    """Interactive config editor - placeholder."""
    console.print("[yellow]Config menu not yet implemented[/yellow]")
    input("\nPress Enter to continue...")


def run_wizard() -> None:
    """First-time setup wizard - placeholder."""
    console.print("[yellow]Wizard not yet implemented[/yellow]")
    input("\nPress Enter to continue...")
