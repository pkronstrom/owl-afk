"""Interactive menu flows."""

from rich.panel import Panel

from owl.cli.ui.menu import RichTerminalMenu
from owl.cli.ui.panels import clear_screen, console, reset_cursor, show_cursor
from owl.utils.config import Config, get_owl_dir


def _print_header() -> None:
    """Print application header with status."""
    from owl.cli.install import check_hooks_installed

    owl_dir = get_owl_dir()
    config = Config(owl_dir)
    mode = config.get_mode()

    # Build status parts
    parts = []
    parts.append(f"[{'green' if mode == 'on' else 'yellow'}]{mode}[/]")

    if config.telegram_bot_token and config.telegram_chat_id:
        parts.append("[green]tg[/green]")
    else:
        parts.append("[dim]tg[/dim]")

    hooks_installed, hooks_mode = check_hooks_installed()
    if hooks_installed:
        parts.append(f"[green]{hooks_mode}[/green]")

    status_line = " | ".join(parts)

    console.print(
        Panel(
            f"[bold cyan]owl[/bold cyan] {status_line}",
            border_style="cyan",
            width=min(80, console.width),
        )
    )


def interactive_menu() -> None:
    """Main interactive menu."""
    from owl.cli.commands import cmd_install, cmd_off, cmd_on, cmd_uninstall
    from owl.cli.install import check_hooks_installed
    from owl.cli.helpers import config_exists

    menu = RichTerminalMenu()
    owl_dir = get_owl_dir()

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

        config = Config(owl_dir)
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

        options.append("Load Preset")
        actions.append("preset")

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
        elif action == "preset":
            _preset_menu()
        elif action == "install":
            clear_screen()
            cmd_install(None)
            input("\nPress Enter to continue...")
        elif action == "uninstall":
            clear_screen()
            cmd_uninstall(None)
            break

    # Clear screen on exit
    clear_screen()


def _preset_menu() -> None:
    """Load a rule preset from the interactive menu."""
    import asyncio

    from owl.core.presets import list_presets, load_preset
    from owl.core.storage import Storage

    clear_screen()
    console.print("[bold]Load Rule Preset[/bold]\n")
    console.print(
        "Presets auto-approve common operations at different trust levels.\n"
        "Rules are added alongside your existing rules (never removed).\n"
    )

    presets = list_presets()
    options = [f"{p['name']:<15} {p['description']}" for p in presets]

    menu = RichTerminalMenu()
    choice = menu.select(options, title="Select a preset:")
    if choice is None:
        return

    preset = presets[choice]
    owl_dir = get_owl_dir()
    db_path = owl_dir / "owl.db"

    async def _load():
        async with Storage(db_path) as storage:
            return await load_preset(storage, preset["name"])

    added, skipped = asyncio.run(_load())
    console.print(f"\n[green]Added {added} rules[/green]", end="")
    if skipped:
        console.print(f" [dim]({skipped} already existed)[/dim]")
    else:
        console.print()
    input("\nPress Enter to continue...")


def interactive_rules() -> None:
    """Interactive rules management with live panel."""
    import readchar

    from owl.cli.helpers import add_rule, get_rules, remove_rule
    from owl.cli.ui.panels import (
        calculate_visible_range,
        format_scroll_indicator,
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

    owl_dir = get_owl_dir()
    menu = RichTerminalMenu()

    cursor = 0
    scroll_offset = 0
    status_msg = ""
    pending_delete = False  # For inline delete confirmation

    # Fixed panel dimensions
    PANEL_WIDTH = 80
    PANEL_HEIGHT = 15  # Fixed number of content lines

    def build_panel(rules) -> Panel:
        nonlocal cursor, scroll_offset, pending_delete

        lines = []

        if not rules:
            lines.append("[dim]No rules defined.[/dim]")
            lines.append("")
            lines.append("[dim]Press 'a' to add a rule[/dim]")
        else:
            # Calculate visible range for rules area (leave room for status + legend)
            max_visible = PANEL_HEIGHT - 4  # Reserve lines for status and legend

            start, end, scroll_offset = calculate_visible_range(
                cursor, len(rules), max_visible, scroll_offset
            )

            # Top scroll indicator
            top_ind, _ = format_scroll_indicator(start, len(rules) - end)
            if top_ind:
                lines.append(f"[dim]{top_ind}[/dim]")
            else:
                lines.append("")  # Keep consistent height

            # Visible rules
            for i in range(start, end):
                rule = rules[i]
                prefix = "> " if i == cursor else "  "
                is_approve = rule["action"] == "approve"
                icon = "✓" if is_approve else "✗"
                pattern = rule["pattern"]
                # Colorblind-friendly: blue for approve, orange for deny
                color = "blue" if is_approve else "dark_orange"

                if i == cursor:
                    lines.append(
                        f"[bold {color}]{prefix}{icon} {pattern}[/bold {color}]"
                    )
                else:
                    lines.append(f"[{color}]{prefix}{icon} {pattern}[/{color}]")

            # Bottom scroll indicator
            _, bottom_ind = format_scroll_indicator(start, len(rules) - end)
            if bottom_ind:
                lines.append(f"[dim]{bottom_ind}[/dim]")
            else:
                lines.append("")  # Keep consistent height

        # Pad to fixed height (before status and legend)
        while len(lines) < PANEL_HEIGHT - 2:
            lines.append("")

        # Status line (always present, may be empty)
        if pending_delete and rules and cursor < len(rules):
            rule = rules[cursor]
            lines.append(f"[yellow]Delete '{rule['pattern']}'? (y/n)[/yellow]")
        elif status_msg:
            lines.append(f"[blue]✓ {status_msg}[/blue]")
        else:
            lines.append("")  # Empty status line

        # Legend inside panel
        lines.append("[dim]↑↓/jk nav • Space toggle • e edit • a add • d del • q[/dim]")

        return Panel(
            "\n".join(lines),
            title="Rules",
            border_style="cyan",
            width=PANEL_WIDTH,
        )

    first_render = True
    while True:
        # Fetch and sort rules once per iteration
        rules = sort_rules(get_rules(owl_dir))

        if first_render:
            clear_screen()
            first_render = False
        else:
            reset_cursor()
        console.print(build_panel(rules))

        key = readchar.readkey()
        status_msg = ""

        if key in (readchar.key.UP, "k"):
            cursor = max(0, cursor - 1)
        elif key in (readchar.key.DOWN, "j"):
            cursor = min(max(0, len(rules) - 1), cursor + 1)
        elif key in ("q", readchar.key.CTRL_C):
            show_cursor()
            return
        elif key == " " and rules:
            # Toggle action
            rule = rules[cursor]
            new_action = "deny" if rule["action"] == "approve" else "approve"
            remove_rule(owl_dir, rule["id"])
            add_rule(owl_dir, rule["pattern"], new_action)
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
                remove_rule(owl_dir, rule["id"])
                add_rule(owl_dir, full_pattern, rule["action"])
                status_msg = f"Updated: {full_pattern}"
        elif key == "a":
            # Add new rule
            if _add_rule_form(owl_dir):
                status_msg = "Rule added"
        elif key == "d" and rules and not pending_delete:
            # Start delete confirmation
            pending_delete = True
        elif key == "y" and pending_delete and rules:
            # Confirm delete
            rule = rules[cursor]
            remove_rule(owl_dir, rule["id"])
            cursor = max(0, min(cursor, len(rules) - 2))
            status_msg = "Rule deleted"
            pending_delete = False
        elif pending_delete:
            # Any other key cancels delete
            pending_delete = False


def _add_rule_form(owl_dir) -> bool:
    """Add rule form. Returns True if rule was added."""
    import readchar

    from owl.cli.helpers import add_rule

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

    first_render = True
    while True:
        if first_render:
            clear_screen()
            first_render = False
        else:
            reset_cursor()

        console.print("[bold]Add Rule[/bold]\n")

        # Tool row
        tool_prefix = "> " if cursor == 0 else "  "
        console.print(f"{tool_prefix}Tool:     {tool_options[tool_idx]:<15}")

        # Pattern row
        pattern_prefix = "> " if cursor == 1 else "  "
        console.print(f"{pattern_prefix}Pattern:  {pattern:<15}")

        # Action row
        action_prefix = "> " if cursor == 2 else "  "
        # Colorblind-friendly: blue for approve, orange for deny
        action_icon = (
            "[blue]✓[/blue]" if action_approve else "[dark_orange]✗[/dark_orange]"
        )
        action_text = "approve" if action_approve else "deny"
        console.print(f"{action_prefix}Action:   {action_icon} {action_text:<10}")

        console.print()
        console.print(
            "[dim]↑↓ navigate • Space cycle/toggle • Enter edit pattern • s save • q cancel[/dim]"
        )
        # Pad to ensure consistent height
        console.print()
        console.print()

        key = readchar.readkey()

        if key in (readchar.key.UP, "k"):
            cursor = max(0, cursor - 1)
        elif key in (readchar.key.DOWN, "j"):
            cursor = min(2, cursor + 1)
        elif key in ("q", readchar.key.CTRL_C):
            show_cursor()
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
            add_rule(owl_dir, full_pattern, action)
            show_cursor()
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

    owl_dir = get_owl_dir()
    cursor = 1  # Start at first item after header
    status_msg = ""

    # Fixed panel dimensions
    PANEL_WIDTH = 80
    PANEL_HEIGHT = 19  # Room for 3 sections + spacers + items + status + legend

    # Which toggles belong to which section
    GENERAL_TOGGLES = ["debug", "auto_approve_notify", "tool_results"]
    HOOK_TOGGLES = ["stop_hook", "subagent_hook", "notification_hook"]

    def build_items(config):
        """Build items list from config."""
        items = []

        # General settings
        items.append(("General", "", "header", None))
        for attr in GENERAL_TOGGLES:
            if attr in Config.TOGGLES:
                desc = Config.TOGGLES[attr]
                value = getattr(config, attr, False)
                items.append((attr, desc, "bool", value))
        items.append(("", "", "spacer", None))

        # Hook settings with note
        items.append(("Hooks", "[dim]changes apply immediately[/dim]", "header", None))
        for attr in HOOK_TOGGLES:
            if attr in Config.TOGGLES:
                desc = Config.TOGGLES[attr]
                value = getattr(config, attr, False)
                items.append((attr, desc, "bool", value))
        items.append(("", "", "spacer", None))

        # Telegram credentials
        items.append(("Telegram", "", "header", None))

        # Add text fields
        token_display = (
            "**********" + config.telegram_bot_token[-4:]
            if config.telegram_bot_token and len(config.telegram_bot_token) > 4
            else "(not set)"
        )
        items.append(
            (
                "telegram_bot_token",
                token_display,
                "text",
                config.telegram_bot_token or "",
            )
        )

        chat_display = config.telegram_chat_id or "(not set)"
        items.append(
            ("telegram_chat_id", chat_display, "text", config.telegram_chat_id or "")
        )

        editor_display = config.editor or "$EDITOR"
        items.append(("editor", editor_display, "text", config.editor or ""))

        return items

    def build_panel(items):
        """Build fixed-size config panel."""
        lines = []

        for i, (attr, desc, item_type, value) in enumerate(items):
            if item_type == "header":
                # Section header (not selectable), align desc with item descriptions
                if desc:
                    # 4 chars for prefix+icon, 24 for attr name = 28 total padding
                    lines.append(f"[bold]{attr:<28}[/bold] {desc}")
                else:
                    lines.append(f"[bold]{attr}[/bold]")
                continue
            if item_type == "spacer":
                lines.append("")
                continue

            prefix = "> " if i == cursor else "  "

            if item_type == "bool":
                # Colorblind-friendly: blue for on
                icon = "[blue]✓[/blue]" if value else "[dim]·[/dim]"
                lines.append(f"{prefix}{icon} {attr:<24} [dim]{desc}[/dim]")
            else:
                icon = "[cyan]✎[/cyan]"  # Pencil for editable text
                lines.append(f"{prefix}{icon} {attr:<24} [yellow]{desc}[/yellow]")

        # Pad to fixed height
        while len(lines) < PANEL_HEIGHT - 2:
            lines.append("")

        # Status line (reserved space, or empty for spacing)
        if status_msg:
            lines.append(f"[blue]✓ {status_msg}[/blue]")
        else:
            lines.append("")

        # Legend
        lines.append("[dim]↑↓ nav • Space/Enter toggle/edit • q back[/dim]")

        return Panel(
            "\n".join(lines),
            title="Config",
            border_style="cyan",
            width=PANEL_WIDTH,
        )

    first_render = True
    while True:
        config = Config(owl_dir)
        items = build_items(config)

        if first_render:
            clear_screen()
            first_render = False
        else:
            reset_cursor()
        console.print(build_panel(items))

        # Handle input
        key = readchar.readkey()
        old_status = status_msg
        status_msg = ""

        if key in (readchar.key.UP, "k"):
            # Skip headers and spacers when moving up
            new_cursor = cursor - 1
            while new_cursor >= 0 and items[new_cursor][2] in ("header", "spacer"):
                new_cursor -= 1
            if new_cursor >= 0:
                cursor = new_cursor
        elif key in (readchar.key.DOWN, "j"):
            # Skip headers and spacers when moving down
            new_cursor = cursor + 1
            while new_cursor < len(items) and items[new_cursor][2] in (
                "header",
                "spacer",
            ):
                new_cursor += 1
            if new_cursor < len(items):
                cursor = new_cursor
        elif key in ("q", readchar.key.CTRL_C):
            show_cursor()
            return
        elif key in (" ", readchar.key.ENTER, "e"):
            attr, desc, item_type, value = items[cursor]
            if item_type in ("header", "spacer"):
                continue  # Skip non-interactive items

            if item_type == "bool":
                # Toggle boolean
                new_value = not value
                config.set_toggle(attr, new_value)
                status_msg = f"{attr} = {new_value}"
            else:
                # Edit text field
                menu = RichTerminalMenu()
                new_value = menu.input(f"Enter {attr}:", default=value)
                if new_value is not None:
                    setattr(config, attr, new_value)
                    config.save()
                    status_msg = f"{attr} updated"
                # Reset after returning from editor to fix cursor visibility
                first_render = True


def run_wizard() -> None:
    """First-time setup wizard."""
    from owl.cli.helpers import do_telegram_test
    from owl.cli.install import (
        HAWK_HOOKS_DIR,
        HAWK_V2_REGISTRY,
        do_hawk_hooks_install,
        do_hawk_v2_install,
        do_standalone_install,
    )

    menu = RichTerminalMenu()
    owl_dir = get_owl_dir()
    owl_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Welcome
    clear_screen()
    console.print(
        Panel(
            "[bold cyan]owl Setup[/bold cyan]\n\n"
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

    hawk_v2 = HAWK_V2_REGISTRY.exists()
    hawk_available = hawk_v2 or HAWK_HOOKS_DIR.exists()

    options = ["Standalone         Write to ~/.claude/settings.json"]
    if hawk_available:
        options.append("Hawk-hooks         Use hook manager")
    else:
        options.append("[dim]Hawk-hooks         (not installed)[/dim]")

    console.print("[dim]Enter select • q cancel[/dim]\n")
    choice = menu.select(options)

    if choice is None:
        return

    if choice == 0:
        do_standalone_install(owl_dir)
    elif choice == 1 and hawk_available:
        if hawk_v2:
            do_hawk_v2_install()
        else:
            do_hawk_hooks_install()

    console.print()

    # Step 3: Telegram setup
    clear_screen()
    console.print("[bold]Telegram Setup[/bold]\n")
    console.print("1. Create a bot: [cyan]https://telegram.me/BotFather[/cyan]")
    console.print("2. Get chat ID:  [cyan]https://t.me/getmyid_bot[/cyan]\n")

    config = Config(owl_dir)

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

    # Step 5: Enable owl
    console.print()
    if menu.confirm("Enable owl now?", default=True):
        config.set_mode("on")
        console.print("[green]owl enabled![/green]")

    # Ensure config is saved
    config.save()

    # Step 6: Rule presets
    console.print()
    console.print("[bold]Rule Presets[/bold]\n")
    console.print(
        "Presets auto-approve common operations so you don't have to\n"
        "approve every read, search, or git status from your phone.\n"
    )

    from owl.core.presets import list_presets, load_preset
    from owl.core.storage import Storage

    presets = list_presets()
    # Reorder: standard first (recommended for most users)
    options = [
        f"standard        {presets[1]['description']} (recommended)",
        f"cautious        {presets[0]['description']}",
        f"permissive      {presets[2]['description']}",
        "skip            I'll add rules manually",
    ]
    # Map option index back to preset name
    option_to_name = ["standard", "cautious", "permissive", None]

    choice = menu.select(options, title="Select a starting preset:")
    preset_name = option_to_name[choice] if choice is not None else None

    if preset_name:
        import asyncio

        db_path = owl_dir / "owl.db"

        async def _load():
            async with Storage(db_path) as storage:
                return await load_preset(storage, preset_name)

        added, _ = asyncio.run(_load())
        console.print(f"[green]Loaded '{preset_name}' preset ({added} rules)[/green]")

    # Step 7: Done
    console.print()
    console.print(
        Panel(
            "[bold green]Setup complete![/bold green]\n\n"
            f"[dim]Config:[/dim] {owl_dir}\n\n"
            "[dim]Run[/dim] [cyan]owl[/cyan] [dim]to manage[/dim]",
            border_style="green",
        )
    )
    input("\nPress Enter to continue...")
