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
            width=min(80, console.width),
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
    """Interactive rules management with live panel."""
    import readchar

    from pyafk.cli.helpers import add_rule, get_rules, remove_rule
    from pyafk.cli.ui.panels import (
        calculate_visible_range,
        format_scroll_indicator,
        get_terminal_size,
    )

    def sort_rules(rules_list):
        """Sort rules by tool name, then pattern."""

        def sort_key(rule):
            pattern = rule["pattern"]
            if "(" in pattern:
                tool = pattern.split("(")[0]
                rest = pattern.split("(", 1)[1]
            else:
                tool = pattern
                rest = ""
            return (tool.lower(), rest.lower())

        return sorted(rules_list, key=sort_key)

    pyafk_dir = get_pyafk_dir()
    menu = RichTerminalMenu()

    cursor = 0
    scroll_offset = 0
    status_msg = ""
    pending_delete = False  # For inline delete confirmation

    def build_panel(rules) -> Panel:
        nonlocal cursor, scroll_offset, pending_delete

        if not rules:
            return Panel(
                "[dim]No rules defined.[/dim]\n\n[dim]Press 'a' to add a rule[/dim]",
                title="Rules",
                border_style="cyan",
                width=min(80, console.width),
            )

        # Calculate visible range
        _, height = get_terminal_size()
        max_visible = max(5, height - 10)

        start, end, scroll_offset = calculate_visible_range(
            cursor, len(rules), max_visible, scroll_offset
        )

        # Build content
        lines = []

        # Top scroll indicator
        top_ind, _ = format_scroll_indicator(start, len(rules) - end)
        if top_ind:
            lines.append(f"[dim]{top_ind}[/dim]")
            lines.append("")

        # Visible rules
        for i in range(start, end):
            rule = rules[i]
            prefix = "> " if i == cursor else "  "
            icon = "[green]✓[/green]" if rule["action"] == "approve" else "[red]✗[/red]"
            pattern = rule["pattern"]

            if i == cursor:
                lines.append(f"[cyan]{prefix}{icon} {pattern}[/cyan]")
            else:
                lines.append(f"{prefix}{icon} {pattern}")

        # Bottom scroll indicator
        _, bottom_ind = format_scroll_indicator(start, len(rules) - end)
        if bottom_ind:
            lines.append("")
            lines.append(f"[dim]{bottom_ind}[/dim]")

        # Status message or delete confirmation
        if pending_delete and rules and cursor < len(rules):
            rule = rules[cursor]
            lines.append("")
            lines.append(f"[yellow]Delete '{rule['pattern']}'? (y/n)[/yellow]")
        elif status_msg:
            lines.append("")
            lines.append(f"[green]✓ {status_msg}[/green]")

        return Panel(
            "\n".join(lines),
            title="Rules",
            border_style="cyan",
            width=min(80, console.width),
        )

    while True:
        # Fetch and sort rules once per iteration
        rules = sort_rules(get_rules(pyafk_dir))

        clear_screen()
        console.print(build_panel(rules))
        console.print()
        console.print(
            "[dim]↑↓/jk navigate • Space toggle • Enter/e edit • a add • d delete • q back[/dim]"
        )

        key = readchar.readkey()
        status_msg = ""

        if key in (readchar.key.UP, "k"):
            cursor = max(0, cursor - 1)
        elif key in (readchar.key.DOWN, "j"):
            cursor = min(max(0, len(rules) - 1), cursor + 1)
        elif key in ("q", readchar.key.CTRL_C):
            return
        elif key == " " and rules:
            # Toggle action
            rule = rules[cursor]
            new_action = "deny" if rule["action"] == "approve" else "approve"
            remove_rule(pyafk_dir, rule["id"])
            add_rule(pyafk_dir, rule["pattern"], new_action)
            status_msg = f"Toggled to {new_action}"
        elif key in (readchar.key.ENTER, "e") and rules:
            # Edit pattern
            rule = rules[cursor]
            # Parse existing pattern
            if "(" in rule["pattern"]:
                old_tool = rule["pattern"].split("(")[0]
                old_arg = rule["pattern"].split("(", 1)[1].rstrip(")")
            else:
                old_tool = rule["pattern"]
                old_arg = ""

            new_pattern = menu.input(f"Pattern for {old_tool}:", default=old_arg)
            if new_pattern is not None:
                full_pattern = (
                    f"{old_tool}({new_pattern})" if new_pattern else f"{old_tool}(*)"
                )
                remove_rule(pyafk_dir, rule["id"])
                add_rule(pyafk_dir, full_pattern, rule["action"])
                status_msg = f"Updated: {full_pattern}"
        elif key == "a":
            # Add new rule
            if _add_rule_form(pyafk_dir):
                status_msg = "Rule added"
        elif key == "d" and rules and not pending_delete:
            # Start delete confirmation
            pending_delete = True
        elif key == "y" and pending_delete and rules:
            # Confirm delete
            rule = rules[cursor]
            remove_rule(pyafk_dir, rule["id"])
            cursor = max(0, min(cursor, len(rules) - 2))
            status_msg = "Rule deleted"
            pending_delete = False
        elif pending_delete:
            # Any other key cancels delete
            pending_delete = False


def _add_rule_form(pyafk_dir) -> bool:
    """Add rule form. Returns True if rule was added."""
    import readchar

    from pyafk.cli.helpers import add_rule

    menu = RichTerminalMenu()

    tool_options = [
        "Bash",
        "Edit",
        "Write",
        "Read",
        "Skill",
        "WebFetch",
        "WebSearch",
        "Task",
        "mcp__*",
        "(custom)",
    ]

    # Form state
    tool_idx = 0
    pattern = "*"
    action_approve = True
    cursor = 0  # 0=tool, 1=pattern, 2=action

    while True:
        clear_screen()
        console.print("[bold]Add Rule[/bold]\n")

        # Tool row
        tool_prefix = "> " if cursor == 0 else "  "
        console.print(f"{tool_prefix}Tool:     {tool_options[tool_idx]}")

        # Pattern row
        pattern_prefix = "> " if cursor == 1 else "  "
        console.print(f"{pattern_prefix}Pattern:  {pattern}")

        # Action row
        action_prefix = "> " if cursor == 2 else "  "
        action_icon = "[green]✓[/green]" if action_approve else "[red]✗[/red]"
        action_text = "approve" if action_approve else "deny"
        console.print(f"{action_prefix}Action:   {action_icon} {action_text}")

        console.print()
        console.print(
            "[dim]↑↓ navigate • Space cycle/toggle • Enter edit pattern • s save • q cancel[/dim]"
        )

        key = readchar.readkey()

        if key in (readchar.key.UP, "k"):
            cursor = max(0, cursor - 1)
        elif key in (readchar.key.DOWN, "j"):
            cursor = min(2, cursor + 1)
        elif key in ("q", readchar.key.CTRL_C):
            return False
        elif key == "s":
            # Save
            tool = tool_options[tool_idx]
            if tool == "(custom)":
                tool = menu.input("Enter tool name:")
                if not tool:
                    continue

            full_pattern = f"{tool}({pattern})"
            action = "approve" if action_approve else "deny"
            add_rule(pyafk_dir, full_pattern, action)
            return True
        elif key == " ":
            if cursor == 0:
                # Cycle tool
                tool_idx = (tool_idx + 1) % len(tool_options)
            elif cursor == 2:
                # Toggle action
                action_approve = not action_approve
        elif key in (readchar.key.ENTER, "e"):
            if cursor == 0:
                # Cycle tool (same as space)
                tool_idx = (tool_idx + 1) % len(tool_options)
            elif cursor == 1:
                # Edit pattern
                new_pattern = menu.input("Pattern:", default=pattern)
                if new_pattern is not None:
                    pattern = new_pattern
            elif cursor == 2:
                # Toggle action
                action_approve = not action_approve


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
                    # Escape brackets for Rich markup
                    checkbox = "\\[x]" if value else "\\[ ]"
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
    """First-time setup wizard."""
    from pyafk.cli.helpers import do_telegram_test
    from pyafk.cli.install import (
        CAPTAIN_HOOK_DIR,
        do_captain_hook_install,
        do_standalone_install,
    )

    menu = RichTerminalMenu()
    pyafk_dir = get_pyafk_dir()
    pyafk_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Welcome
    clear_screen()
    console.print(
        Panel(
            "[bold cyan]pyafk Setup[/bold cyan]\n\n"
            "[dim]Remote approval for Claude Code[/dim]\n\n"
            "[bold]How it works:[/bold]\n"
            "1. Intercepts Claude tool calls\n"
            "2. Sends requests to Telegram\n"
            "3. You approve/deny from phone",
            border_style="cyan",
        )
    )
    console.print()
    console.print("[dim]Enter select • q exit[/dim]\n")

    choice = menu.select(["Continue", "Exit"])
    if choice is None or choice == 1:
        return

    # Step 2: Install hooks
    clear_screen()
    console.print("[bold]Install Hooks[/bold]\n")

    captain_available = CAPTAIN_HOOK_DIR.exists()

    options = ["Standalone         Write to ~/.claude/settings.json"]
    if captain_available:
        options.append("Captain-hook       Use hook manager")
    else:
        options.append("[dim]Captain-hook       (not installed)[/dim]")

    console.print("[dim]Enter select • q cancel[/dim]\n")
    choice = menu.select(options)

    if choice is None:
        return

    if choice == 0:
        do_standalone_install(pyafk_dir)
    elif choice == 1 and captain_available:
        do_captain_hook_install()

    console.print()

    # Step 3: Telegram setup
    clear_screen()
    console.print("[bold]Telegram Setup[/bold]\n")
    console.print("1. Create a bot: [cyan]https://telegram.me/BotFather[/cyan]")
    console.print("2. Get chat ID:  [cyan]https://t.me/getmyid_bot[/cyan]\n")

    config = Config(pyafk_dir)

    bot_token = menu.input("Bot token:", default=config.telegram_bot_token or "")
    if bot_token:
        config.telegram_bot_token = bot_token

    chat_id = menu.input("Chat ID:", default=config.telegram_chat_id or "")
    if chat_id:
        config.telegram_chat_id = chat_id

    if bot_token or chat_id:
        config.save()
        console.print("\n[green]Telegram configured![/green]")

        # Step 4: Test connection
        if menu.confirm("Send test message?", default=True):
            do_telegram_test(config)

    # Step 5: Enable pyafk
    console.print()
    if menu.confirm("Enable pyafk now?", default=True):
        config.set_mode("on")
        console.print("[green]pyafk enabled![/green]")

    # Ensure config is saved
    config.save()

    # Step 6: Done
    console.print()
    console.print(
        Panel(
            "[bold green]Setup complete![/bold green]\n\n"
            f"[dim]Config:[/dim] {pyafk_dir}\n\n"
            "[dim]Run[/dim] [cyan]pyafk[/cyan] [dim]to manage[/dim]",
            border_style="green",
        )
    )
    input("\nPress Enter to continue...")
