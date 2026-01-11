"""Interactive menus for CLI."""

import questionary
from rich.panel import Panel

from pyafk.cli.helpers import (
    add_rule,
    config_exists,
    do_telegram_test,
    get_rules,
    remove_rule,
)
from pyafk.cli.install import (
    CAPTAIN_HOOK_DIR,
    do_captain_hook_install,
    do_standalone_install,
)
from pyafk.cli.ui import (
    clear_screen,
    console,
    custom_style,
    print_header,
    print_status_inline,
)
from pyafk.utils.config import Config, get_pyafk_dir


def interactive_menu():
    """Main interactive menu."""
    from pyafk.cli.commands import (
        cmd_install,
        cmd_off,
        cmd_on,
        cmd_status,
        cmd_uninstall,
    )

    # Check for first run
    if not config_exists():
        answer = questionary.confirm(
            "First time setup - run wizard?",
            default=True,
            style=custom_style,
        ).ask()
        if answer is None:
            return
        if answer:
            run_wizard()
            return

    while True:
        clear_screen()
        print_header()
        print_status_inline()

        choice = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("Status       Show detailed status", value="status"),
                questionary.Choice("Turn on      Enable pyafk", value="on"),
                questionary.Choice("Turn off     Disable pyafk", value="off"),
                questionary.Separator("─────────"),
                questionary.Choice(
                    "Rules        Manage auto-approve rules", value="rules"
                ),
                questionary.Choice(
                    "Telegram     Configure Telegram bot", value="telegram"
                ),
                questionary.Choice("Config       Debug mode, daemon", value="config"),
                questionary.Separator("─────────"),
                questionary.Choice(
                    "Install      Install hooks (standalone)", value="install"
                ),
                questionary.Choice("Uninstall    Remove hooks", value="uninstall"),
                questionary.Separator("─────────"),
                questionary.Choice("Exit", value="exit"),
            ],
            style=custom_style,
            instruction="(Ctrl+C exit)",
        ).ask()

        if choice is None or choice == "exit":
            break

        if choice == "status":
            clear_screen()
            cmd_status(None)
            questionary.press_any_key_to_continue(style=custom_style).ask()
        elif choice == "on":
            cmd_on(None)
        elif choice == "off":
            cmd_off(None)
        elif choice == "rules":
            interactive_rules()
        elif choice == "telegram":
            interactive_telegram()
        elif choice == "config":
            interactive_config()
        elif choice == "install":
            clear_screen()
            cmd_install(None)
            questionary.press_any_key_to_continue(style=custom_style).ask()
        elif choice == "uninstall":
            clear_screen()
            cmd_uninstall(None)
            break


def interactive_rules():
    """Interactive rules management."""
    pyafk_dir = get_pyafk_dir()

    while True:
        clear_screen()
        console.print("[bold]Auto-approve Rules[/bold]")
        console.print("─" * 50)
        console.print()

        # Get current rules
        rules_data = get_rules(pyafk_dir)

        if not rules_data:
            console.print("[dim]No rules defined.[/dim]")
            console.print()

        # Build choices
        choices = []

        # Sort rules by tool name, then pattern
        def sort_key(rule):
            pattern = rule["pattern"]
            if "(" in pattern:
                tool = pattern.split("(")[0]
                rest = pattern.split("(", 1)[1]
            else:
                tool = pattern
                rest = ""
            return (tool.lower(), rest.lower())

        sorted_rules = sorted(rules_data, key=sort_key)

        for rule in sorted_rules:
            action_icon = "✓" if rule["action"] == "approve" else "✗"
            label = f"{action_icon} {rule['pattern']:<40} {rule['action']}"
            choices.append(
                questionary.Choice(
                    label, value=("edit", rule["id"], rule["pattern"], rule["action"])
                )
            )

        if choices:
            choices.append(questionary.Separator("─────────"))

        choices.extend(
            [
                questionary.Choice("Add rule", value="add"),
                questionary.Choice("Back", value="back"),
            ]
        )

        console.print()
        choice = questionary.select(
            "Select rule to edit, or add new:",
            choices=choices,
            style=custom_style,
            instruction="(Enter select • Ctrl+C back)",
        ).ask()

        if choice is None or choice == "back":
            break

        if choice == "add":
            _add_rule_wizard(pyafk_dir)
        elif isinstance(choice, tuple) and choice[0] == "edit":
            _, rule_id, pattern, action = choice
            _edit_rule_menu(pyafk_dir, rule_id, pattern, action)


def _add_rule_wizard(pyafk_dir):
    """Wizard for adding a new rule."""
    clear_screen()
    console.print("[bold]Add Rule[/bold]")
    console.print("─" * 50)
    console.print()

    # Tool type definitions
    tool_types = [
        ("Bash", "Shell commands"),
        ("Edit", "File edits"),
        ("Write", "File creation"),
        ("Read", "File reading"),
        ("Skill", "Skill execution"),
        ("WebFetch", "Web requests"),
        ("WebSearch", "Web searches"),
        ("Task", "Sub-agents"),
        ("mcp__*", "MCP tools (match all)"),
        ("(custom)", "Enter tool name"),
    ]

    tool_choices = [
        questionary.Choice(f"{tool:<12} {desc}", value=tool)
        for tool, desc in tool_types
    ]

    tool = questionary.select(
        "Select tool type:",
        choices=tool_choices,
        style=custom_style,
    ).ask()

    if tool is None:
        return

    # Handle custom tool name
    if tool == "(custom)":
        tool = questionary.text(
            "Enter tool name:",
            style=custom_style,
        ).ask()
        if not tool:
            return

    # Pattern examples per tool
    pattern_examples = {
        "Bash": "git *, npm run *, python *.py",
        "Edit": "*.py, /src/*.ts, *config*",
        "Write": "*.py, /tmp/*, *test*",
        "Read": "*.md, /docs/*",
        "Skill": "*",
        "WebFetch": "https://github.com/*, *api*",
        "WebSearch": "*",
        "Task": "*",
        "mcp__*": "(pattern applies to all MCP tools)",
    }

    examples = pattern_examples.get(tool, "*")
    console.print()
    console.print("[dim]Wildcards: * matches anything, ? matches single char[/dim]")
    console.print(f"[dim]Examples: {examples}[/dim]")
    console.print()

    pattern_arg = questionary.text(
        f"Pattern for {tool}:",
        style=custom_style,
    ).ask()

    if pattern_arg is None:
        return

    # Build full pattern
    if pattern_arg:
        full_pattern = f"{tool}({pattern_arg})"
    else:
        full_pattern = f"{tool}(*)"

    # Choose action
    console.print()
    action = questionary.select(
        "Action:",
        choices=[
            questionary.Choice(
                "Approve    Auto-approve matching calls", value="approve"
            ),
            questionary.Choice("Deny       Auto-deny matching calls", value="deny"),
        ],
        style=custom_style,
    ).ask()

    if action is None:
        return

    # Add the rule
    add_rule(pyafk_dir, full_pattern, action)
    console.print()
    console.print(f"[green]Added:[/green] {full_pattern} -> {action}")
    questionary.press_any_key_to_continue(style=custom_style).ask()


def _edit_rule_menu(pyafk_dir, rule_id, pattern, action):
    """Menu for editing/deleting a rule."""
    clear_screen()
    console.print("[bold]Edit Rule[/bold]")
    console.print("─" * 50)
    console.print()
    console.print(f"Pattern: [cyan]{pattern}[/cyan]")
    console.print(f"Action:  [{'green' if action == 'approve' else 'red'}]{action}[/]")
    console.print()

    choice = questionary.select(
        "What would you like to do?",
        choices=[
            questionary.Choice("Edit pattern", value="edit"),
            questionary.Choice("Toggle action", value="toggle"),
            questionary.Choice("Delete rule", value="delete"),
            questionary.Separator("─────────"),
            questionary.Choice("Back", value="back"),
        ],
        style=custom_style,
    ).ask()

    if choice is None or choice == "back":
        return

    if choice == "delete":
        confirm = questionary.confirm(
            f"Delete rule '{pattern}'?",
            default=False,
            style=custom_style,
        ).ask()
        if confirm:
            remove_rule(pyafk_dir, rule_id)
            console.print("[green]Rule deleted.[/green]")
            questionary.press_any_key_to_continue(style=custom_style).ask()

    elif choice == "toggle":
        new_action = "deny" if action == "approve" else "approve"
        remove_rule(pyafk_dir, rule_id)
        add_rule(pyafk_dir, pattern, new_action)
        console.print(f"[green]Changed to:[/green] {pattern} -> {new_action}")
        questionary.press_any_key_to_continue(style=custom_style).ask()

    elif choice == "edit":
        # Parse existing pattern
        if "(" in pattern:
            old_tool = pattern.split("(")[0]
            old_arg = pattern.split("(", 1)[1].rstrip(")")
        else:
            old_tool = pattern
            old_arg = ""

        new_pattern = questionary.text(
            f"New pattern for {old_tool}:",
            default=old_arg,
            style=custom_style,
        ).ask()

        if new_pattern is not None:
            full_pattern = (
                f"{old_tool}({new_pattern})" if new_pattern else f"{old_tool}(*)"
            )
            remove_rule(pyafk_dir, rule_id)
            add_rule(pyafk_dir, full_pattern, action)
            console.print(f"[green]Updated:[/green] {full_pattern} -> {action}")
            questionary.press_any_key_to_continue(style=custom_style).ask()


def interactive_config():
    """Interactive config editor using checkbox toggles."""
    pyafk_dir = get_pyafk_dir()
    cfg = Config(pyafk_dir)

    clear_screen()
    console.print("[bold]Configuration[/bold]")
    console.print("─" * 50)
    console.print()

    # Group toggles by category
    toggle_groups = {
        "General": ["debug"],
        "Polling": ["daemon_enabled"],
        "Hooks": ["disable_stop_hook", "disable_subagent_hook"],
    }

    # Get current toggle states
    toggles = {attr: (desc, enabled) for attr, desc, enabled in cfg.get_toggles()}
    max_name_len = max(len(attr) for attr in toggles)

    # Build choices with section headers
    choices = []
    for section, attrs in toggle_groups.items():
        choices.append(questionary.Separator(f"── {section} ──"))
        for attr in attrs:
            if attr in toggles:
                desc, enabled = toggles[attr]
                choices.append(
                    questionary.Choice(
                        f"{attr:<{max_name_len}}  {desc}",
                        value=attr,
                        checked=enabled,
                    )
                )

    console.print()
    selected = questionary.checkbox(
        "Toggle settings:",
        choices=choices,
        style=custom_style,
        instruction="(Space toggle • Enter save • Ctrl+C cancel)",
    ).ask()

    if selected is None:
        return

    # Apply changes for each toggle
    for attr, (_, was_enabled) in toggles.items():
        now_enabled = attr in selected
        if now_enabled != was_enabled:
            cfg.set_toggle(attr, now_enabled)

    # Offer captain-hook install
    console.print()
    if CAPTAIN_HOOK_DIR.exists():
        install_captain = questionary.confirm(
            "Install/update pyafk hooks in captain-hook?",
            default=False,
            style=custom_style,
        ).ask()
        if install_captain:
            do_captain_hook_install()


def interactive_telegram():
    """Interactive Telegram setup."""
    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)

    while True:
        clear_screen()
        console.print("[bold]Telegram Setup[/bold]")
        console.print("─" * 50)
        console.print()

        # Show current status
        if config.telegram_bot_token and config.telegram_chat_id:
            console.print("[green]Status: Configured[/green]")
            token_preview = (
                config.telegram_bot_token[:10] + "..."
                if len(config.telegram_bot_token) > 10
                else config.telegram_bot_token
            )
            console.print(f"  Token:   {token_preview}")
            console.print(f"  Chat ID: {config.telegram_chat_id}")
        else:
            console.print("[yellow]Status: Not configured[/yellow]")

        console.print()
        console.print("[dim]1. Create a bot: https://telegram.me/BotFather[/dim]")
        console.print("[dim]2. Get chat ID:  https://t.me/getmyid_bot[/dim]")
        console.print()

        choices = [
            questionary.Choice("Set bot token", value="token"),
            questionary.Choice("Set chat ID", value="chat_id"),
            questionary.Choice("Test connection", value="test"),
            questionary.Separator("─────────"),
            questionary.Choice("Back", value="back"),
        ]

        choice = questionary.select(
            "Select option:",
            choices=choices,
            style=custom_style,
        ).ask()

        if choice is None or choice == "back":
            break

        if choice == "token":
            token = questionary.text(
                "Bot token:",
                default=config.telegram_bot_token or "",
                style=custom_style,
            ).ask()
            if token:
                config.telegram_bot_token = token
                config.save()
                console.print("[green]Token saved.[/green]")

        elif choice == "chat_id":
            chat_id = questionary.text(
                "Chat ID:",
                default=config.telegram_chat_id or "",
                style=custom_style,
            ).ask()
            if chat_id:
                config.telegram_chat_id = chat_id
                config.save()
                console.print("[green]Chat ID saved.[/green]")

        elif choice == "test":
            if not config.telegram_bot_token or not config.telegram_chat_id:
                console.print("[yellow]Configure token and chat ID first.[/yellow]")
            else:
                do_telegram_test(config)

            questionary.press_any_key_to_continue(style=custom_style).ask()


def run_wizard():
    """Run the first-time setup wizard."""
    clear_screen()
    console.print(
        Panel(
            "[bold cyan]pyafk[/bold cyan] - First-time setup\n"
            "[dim]Remote approval for Claude Code[/dim]",
            border_style="cyan",
        )
    )
    console.print()

    console.print("[bold]How it works:[/bold]")
    console.print("  1. pyafk intercepts Claude Code tool calls")
    console.print("  2. Sends approval requests to Telegram")
    console.print("  3. You approve/deny from your phone")
    console.print("  4. Use [cyan]pyafk on/off[/cyan] to enable/disable")
    console.print()

    pyafk_dir = get_pyafk_dir()
    pyafk_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Choose installation method
    captain_hook_available = CAPTAIN_HOOK_DIR.exists()

    choices = [
        questionary.Choice(
            "Standalone      (writes to ~/.claude/settings.json)",
            value="standalone",
        ),
    ]
    if captain_hook_available:
        choices.append(
            questionary.Choice(
                "Captain-hook    (uses captain-hook hook manager)",
                value="captain-hook",
            )
        )

    install_method = questionary.select(
        "Choose installation method:",
        choices=choices,
        style=custom_style,
        instruction="(Ctrl+C cancel)",
    ).ask()

    if install_method is None:
        return

    console.print()

    # Run installation
    if install_method == "standalone":
        do_standalone_install(pyafk_dir)
    else:
        do_captain_hook_install()

    console.print()

    # Step 2: Telegram setup
    console.print("[bold]Telegram Bot Setup[/bold]")
    console.print("─" * 40)
    console.print()
    console.print("  1. Create a bot: [cyan]https://telegram.me/BotFather[/cyan]")
    console.print("  2. Get your chat ID: [cyan]https://t.me/getmyid_bot[/cyan]")
    console.print()

    setup_telegram = questionary.confirm(
        "Configure Telegram now?",
        default=True,
        style=custom_style,
    ).ask()

    if setup_telegram:
        console.print()
        config = Config(pyafk_dir)

        bot_token = questionary.text(
            "Bot token:",
            style=custom_style,
        ).ask()

        if bot_token:
            config.telegram_bot_token = bot_token

            chat_id = questionary.text(
                "Chat ID:",
                style=custom_style,
            ).ask()

            if chat_id:
                config.telegram_chat_id = chat_id
                config.save()
                console.print()
                console.print("[green]Telegram configured![/green]")

                # Offer test
                if questionary.confirm(
                    "Send test message?", default=True, style=custom_style
                ).ask():
                    do_telegram_test(config)

    # Step 3: Enable pyafk
    console.print()
    enable_now = questionary.confirm(
        "Enable pyafk now?",
        default=True,
        style=custom_style,
    ).ask()

    if enable_now:
        config = Config(pyafk_dir)
        config.set_mode("on")
        console.print()
        console.print("[green]pyafk enabled![/green]")

    # Save config to mark setup as complete
    config = Config(pyafk_dir)
    config.save()

    console.print()
    console.print(
        Panel(
            "[bold green]Setup complete![/bold green]\n\n"
            f"[dim]Config:[/dim] {pyafk_dir}\n\n"
            "[dim]Run[/dim] [cyan]pyafk[/cyan] [dim]to manage[/dim]\n"
            "[dim]Run[/dim] [cyan]pyafk on/off[/cyan] [dim]to toggle[/dim]",
            border_style="green",
        )
    )
