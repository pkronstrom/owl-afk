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
    """Interactive config editor with toggles and text fields."""
    import readchar

    pyafk_dir = get_pyafk_dir()

    while True:
        config = Config(pyafk_dir)

        clear_screen()
        console.print("[bold]Config[/bold]\n")

        # Build items list: (label, type, key, value)
        items: list[tuple[str, str, str, any]] = []

        # Add toggles
        for attr, desc in Config.TOGGLES.items():
            value = getattr(config, attr, False)
            items.append((f"{attr:<24} {desc}", "bool", attr, value))

        # Add text fields
        token_display = (
            "**********" + config.telegram_bot_token[-4:]
            if config.telegram_bot_token and len(config.telegram_bot_token) > 4
            else config.telegram_bot_token or "(not set)"
        )
        items.append(
            (
                f"{'telegram_bot_token':<24} {token_display}",
                "text",
                "telegram_bot_token",
                config.telegram_bot_token or "",
            )
        )

        chat_display = config.telegram_chat_id or "(not set)"
        items.append(
            (
                f"{'telegram_chat_id':<24} {chat_display}",
                "text",
                "telegram_chat_id",
                config.telegram_chat_id or "",
            )
        )

        editor_display = config.editor or "$EDITOR"
        items.append(
            (f"{'editor':<24} {editor_display}", "text", "editor", config.editor or "")
        )

        cursor = 0
        status_msg = ""

        while True:
            # Render
            clear_screen()
            console.print("[bold]Config[/bold]\n")

            for i, (label, item_type, key, value) in enumerate(items):
                prefix = "> " if i == cursor else "  "

                if item_type == "bool":
                    checkbox = "[x]" if value else "[ ]"
                    console.print(f"{prefix}{checkbox} {label}")
                else:
                    console.print(f"{prefix}    {label}")

            console.print()
            if status_msg:
                console.print(f"[green]✓ {status_msg}[/green]")
            console.print()
            console.print("[dim]↑↓ navigate • Space/Enter toggle/edit • q back[/dim]")

            # Handle input
            key = readchar.readkey()
            status_msg = ""

            if key in (readchar.key.UP, "k"):
                cursor = max(0, cursor - 1)
            elif key in (readchar.key.DOWN, "j"):
                cursor = min(len(items) - 1, cursor + 1)
            elif key in ("q", readchar.key.CTRL_C):
                return
            elif key in (" ", readchar.key.ENTER, "e"):
                label, item_type, attr, value = items[cursor]

                if item_type == "bool":
                    # Toggle boolean
                    new_value = not value
                    config.set_toggle(attr, new_value)
                    items[cursor] = (label, item_type, attr, new_value)
                    status_msg = f"{attr} = {new_value}"
                else:
                    # Edit text field
                    menu = RichTerminalMenu()
                    new_value = menu.input(f"Enter {attr}:", default=value)
                    if new_value is not None:
                        setattr(config, attr, new_value)
                        config.save()
                        status_msg = f"{attr} updated"
                        break  # Refresh outer loop to update display


def run_wizard() -> None:
    """First-time setup wizard - placeholder."""
    console.print("[yellow]Wizard not yet implemented[/yellow]")
    input("\nPress Enter to continue...")
