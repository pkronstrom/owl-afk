"""CLI entry point."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import questionary
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

    hooks_installed, hooks_mode = _check_hooks_installed()
    if hooks_installed:
        parts.append(f"[green]{hooks_mode}[/green]")

    console.print(f"[dim]Status:[/dim] {' | '.join(parts)}")
    console.print()


# =============================================================================
# Interactive menus
# =============================================================================


def interactive_menu():
    """Main interactive menu."""
    pyafk_dir = get_pyafk_dir()

    # Check for first run
    if not _config_exists():
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
        rules_data = _get_rules(pyafk_dir)

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
    rule_id = _add_rule(pyafk_dir, full_pattern, action)
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
            _remove_rule(pyafk_dir, rule_id)
            console.print("[green]Rule deleted.[/green]")
            questionary.press_any_key_to_continue(style=custom_style).ask()

    elif choice == "toggle":
        new_action = "deny" if action == "approve" else "approve"
        _remove_rule(pyafk_dir, rule_id)
        _add_rule(pyafk_dir, pattern, new_action)
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
            _remove_rule(pyafk_dir, rule_id)
            _add_rule(pyafk_dir, full_pattern, action)
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

    # Auto-discover toggleable settings from Config
    toggles = cfg.get_toggles()
    max_name_len = max(len(attr) for attr, _, _ in toggles)

    choices = [
        questionary.Choice(
            f"{attr:<{max_name_len}}  {desc}",
            value=attr,
            checked=enabled,
        )
        for attr, desc, enabled in toggles
    ]

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
    for attr, _, was_enabled in toggles:
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
            _do_captain_hook_install()


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
                _do_telegram_test(config)

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
        _do_standalone_install(pyafk_dir)
    else:
        _do_captain_hook_install()

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
                    _do_telegram_test(config)

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


# =============================================================================
# Helper functions
# =============================================================================


def _config_exists():
    """Check if config exists (first run check)."""
    pyafk_dir = get_pyafk_dir()
    config_file = pyafk_dir / "config.json"
    return config_file.exists()


def _get_rules(pyafk_dir):
    """Get all rules from database."""

    async def _list():
        from pyafk.core.rules import RulesEngine
        from pyafk.core.storage import Storage

        config = Config(pyafk_dir)
        storage = Storage(config.db_path)
        await storage.connect()
        try:
            engine = RulesEngine(storage)
            return await engine.list_rules()
        finally:
            await storage.close()

    return asyncio.run(_list())


def _add_rule(pyafk_dir, pattern, action):
    """Add a rule to database."""

    async def _add():
        from pyafk.core.rules import RulesEngine
        from pyafk.core.storage import Storage

        config = Config(pyafk_dir)
        storage = Storage(config.db_path)
        await storage.connect()
        try:
            engine = RulesEngine(storage)
            return await engine.add_rule(pattern, action, 0, created_via="cli")
        finally:
            await storage.close()

    return asyncio.run(_add())


def _remove_rule(pyafk_dir, rule_id):
    """Remove a rule from database."""

    async def _remove():
        from pyafk.core.rules import RulesEngine
        from pyafk.core.storage import Storage

        config = Config(pyafk_dir)
        storage = Storage(config.db_path)
        await storage.connect()
        try:
            engine = RulesEngine(storage)
            return await engine.remove_rule(rule_id)
        finally:
            await storage.close()

    return asyncio.run(_remove())


def _do_telegram_test(config):
    """Send a test Telegram message."""

    async def _send():
        from pyafk.notifiers.telegram import TelegramNotifier

        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        return await notifier._api_request(
            "sendMessage",
            data={
                "chat_id": config.telegram_chat_id,
                "text": "pyafk test message - Telegram is configured correctly!",
            },
        )

    result = asyncio.run(_send())

    if result.get("ok"):
        console.print("[green]Test message sent![/green]")
    else:
        error = result.get("error", result.get("description", "Unknown error"))
        console.print(f"[red]Failed:[/red] {error}")


def _do_standalone_install(pyafk_dir):
    """Perform standalone installation."""
    settings_path = _get_claude_settings_path()

    console.print("[bold]Installing standalone hooks...[/bold]")

    settings = _load_claude_settings(settings_path)
    existing_hooks = settings.get("hooks", {})

    pyafk_hooks = _get_pyafk_hooks()

    new_hooks = existing_hooks.copy()
    for hook_type, hook_entries in pyafk_hooks.items():
        if hook_type not in new_hooks:
            new_hooks[hook_type] = []
        new_hooks[hook_type] = [
            h for h in new_hooks[hook_type] if not _is_pyafk_hook(h)
        ]
        new_hooks[hook_type].extend(hook_entries)

    settings["hooks"] = new_hooks

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    _save_claude_settings(settings_path, settings)

    for hook_type in pyafk_hooks:
        console.print(f"  [green]✓[/green] {hook_type}")

    console.print()
    console.print(f"[dim]Settings: {settings_path}[/dim]")


def _do_captain_hook_install():
    """Perform captain-hook installation."""
    console.print("[bold]Installing captain-hook hooks...[/bold]")

    for event in HOOK_EVENTS:
        event_dir = CAPTAIN_HOOK_DIR / event
        event_dir.mkdir(parents=True, exist_ok=True)

        hook_config = HOOK_CONFIG[event]
        hook_type = hook_config["type"]
        description = hook_config["description"]
        wrapper_name = f"pyafk-{event}.sh"
        wrapper_path = event_dir / wrapper_name

        wrapper_content = f"""#!/usr/bin/env bash
# Description: {description}
# Deps: pyafk
exec pyafk hook {hook_type}
"""
        wrapper_path.write_text(wrapper_content)
        wrapper_path.chmod(0o755)
        console.print(f"  [green]✓[/green] {event}/{wrapper_name}")

    # Enable hooks via captain-hook CLI
    console.print()
    console.print("Enabling hooks...")
    hook_names = [f"{event}/pyafk-{event}" for event in HOOK_EVENTS]
    try:
        subprocess.run(
            ["captain-hook", "enable"] + hook_names,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["captain-hook", "toggle"],
            check=True,
            capture_output=True,
        )
        console.print("[green]Done![/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[yellow]Warning:[/yellow] Failed to auto-enable: {e}")
        console.print("Run [cyan]captain-hook toggle[/cyan] to enable pyafk hooks.")
    except FileNotFoundError:
        console.print("[yellow]Warning:[/yellow] captain-hook CLI not found")
        console.print("Run [cyan]captain-hook toggle[/cyan] to enable pyafk hooks.")


def _get_claude_settings_path() -> Path:
    """Get path to Claude settings.json."""
    return Path.home() / ".claude" / "settings.json"


def _load_claude_settings(settings_path: Path) -> dict:
    """Load Claude settings from file."""
    if settings_path.exists():
        try:
            return json.loads(settings_path.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_claude_settings(settings_path: Path, settings: dict):
    """Save Claude settings to file."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2))


def _get_pyafk_hooks() -> dict:
    """Get the hook configuration for pyafk."""
    return {
        "PreToolUse": [
            {
                "matcher": "Bash|Edit|Write|MultiEdit|WebFetch|Skill|mcp__.*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook PreToolUse",
                        "timeout": 3600,
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "Bash|Edit|Write|MultiEdit|WebFetch|Skill|mcp__.*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook PostToolUse",
                    }
                ],
            }
        ],
        "PermissionRequest": [
            {
                "matcher": "Bash|Edit|Write|MultiEdit|WebFetch|Skill|mcp__.*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook PermissionRequest",
                        "timeout": 3600,
                    }
                ],
            }
        ],
        "SubagentStop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook SubagentStop",
                        "timeout": 3600,
                    }
                ],
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook Stop",
                    }
                ],
            }
        ],
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook SessionStart",
                    }
                ],
            }
        ],
        "PreCompact": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook PreCompact",
                    }
                ],
            }
        ],
        "SessionEnd": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook SessionEnd",
                    }
                ],
            }
        ],
    }


def _is_pyafk_hook(hook_entry: dict) -> bool:
    """Check if a hook entry belongs to pyafk."""
    command = hook_entry.get("command", "")
    if "pyafk hook" in command:
        return True
    for hook in hook_entry.get("hooks", []):
        if "pyafk hook" in hook.get("command", ""):
            return True
    return False


def _check_hooks_installed() -> tuple[bool, str]:
    """Check if pyafk hooks are installed."""
    settings_path = _get_claude_settings_path()
    if settings_path and settings_path.exists():
        settings = _load_claude_settings(settings_path)
        hooks = settings.get("hooks", {})
        for hook_entries in hooks.values():
            for entry in hook_entries:
                if _is_pyafk_hook(entry):
                    return True, "standalone"

    captain_hook_dir = Path.home() / ".config" / "captain-hook" / "hooks"
    if (captain_hook_dir / "pre_tool_use" / "pyafk-pre_tool_use.sh").exists():
        return True, "captain-hook"

    return False, "none"


# Captain-hook integration
CAPTAIN_HOOK_DIR = Path.home() / ".config" / "captain-hook" / "hooks"
HOOK_CONFIG = {
    "pre_tool_use": {
        "type": "PreToolUse",
        "description": "Remote approval for tool calls via Telegram",
    },
    "post_tool_use": {
        "type": "PostToolUse",
        "description": "Deliver queued Telegram messages after tool execution",
    },
    "stop": {
        "type": "Stop",
        "description": "Notify on session stop via Telegram",
    },
    "subagent_stop": {
        "type": "SubagentStop",
        "description": "Notify when subagents complete via Telegram",
    },
}
HOOK_EVENTS = list(HOOK_CONFIG.keys())


# =============================================================================
# CLI command handlers
# =============================================================================


def cmd_status(args):
    """Show current status."""
    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)
    mode = config.get_mode()

    print(f"Mode: {mode}")
    print(f"Debug: {'on' if config.debug else 'off'}")
    print(f"Config dir: {pyafk_dir}")

    if config.telegram_bot_token and config.telegram_chat_id:
        print("Telegram: configured")
    else:
        print("Telegram: not configured")

    from pyafk.daemon import get_daemon_pid, is_daemon_running

    if is_daemon_running(pyafk_dir):
        pid = get_daemon_pid(pyafk_dir)
        print(f"Daemon: running (pid {pid})")
    else:
        print("Daemon: not running")

    hooks_installed, hooks_mode = _check_hooks_installed()
    if hooks_installed:
        print(f"Hooks: {hooks_mode}")
    else:
        print("Hooks: not installed")


def cmd_on(args):
    """Enable pyafk."""
    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)

    hooks_installed, hooks_mode = _check_hooks_installed()
    if not hooks_installed:
        print("Warning: No pyafk hooks installed!")
        print("Install hooks with: pyafk install")
        print()

    config.set_mode("on")

    mode_info = f"via {hooks_mode}" if hooks_installed else "no hooks"

    if config.telegram_bot_token and config.telegram_chat_id:
        if not config.daemon_enabled:
            print(f"pyafk enabled ({mode_info}, inline polling)")
        else:
            from pyafk.daemon import is_daemon_running, start_daemon

            if is_daemon_running(pyafk_dir):
                print(f"pyafk enabled ({mode_info}, daemon already running)")
            elif start_daemon(pyafk_dir):
                print(f"pyafk enabled ({mode_info}, daemon started)")
            else:
                print(f"pyafk enabled ({mode_info}, daemon failed to start)")
    else:
        print(f"pyafk enabled ({mode_info}, no Telegram configured)")


def cmd_off(args):
    """Disable pyafk."""
    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)
    config.set_mode("off")

    async def cleanup():
        from pyafk.core.storage import Storage
        from pyafk.notifiers.telegram import TelegramNotifier

        if not config.telegram_bot_token or not config.telegram_chat_id:
            return 0

        storage = Storage(pyafk_dir / "pyafk.db")
        await storage.connect()

        try:
            notifier = TelegramNotifier(
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
            )

            pending = await storage.get_pending_requests()
            for request in pending:
                if request.telegram_msg_id:
                    try:
                        await notifier.edit_message(
                            request.telegram_msg_id,
                            "⏸️ pyafk off - retry when enabled",
                        )
                    except Exception:
                        pass
                await storage.resolve_request(
                    request_id=request.id,
                    status="denied",
                    resolved_by="pyafk_off",
                    denial_reason="pyafk disabled - retry when enabled",
                )

            pending_stops = await storage.get_all_pending_stops()
            for stop in pending_stops:
                if stop.get("telegram_msg_id"):
                    try:
                        await notifier.edit_message(
                            stop["telegram_msg_id"],
                            "⏸️ pyafk off - session ended",
                        )
                    except Exception:
                        pass
                await storage.resolve_stop(stop["session_id"], "ok")

            return len(pending) + len(pending_stops)
        finally:
            await storage.close()

    cleaned = asyncio.run(cleanup())

    from pyafk.daemon import is_daemon_running

    if is_daemon_running(pyafk_dir):
        msg = f"pyafk off ({cleaned} pending rejected, use /afk on in Telegram)"
    else:
        msg = f"pyafk off ({cleaned} pending rejected, use 'pyafk on' to start)"
    print(msg)


def cmd_install(args):
    """Install pyafk hooks."""
    pyafk_dir = get_pyafk_dir()
    pyafk_dir.mkdir(parents=True, exist_ok=True)
    _do_standalone_install(pyafk_dir)


def cmd_uninstall(args):
    """Uninstall pyafk hooks."""
    settings_path = _get_claude_settings_path()

    settings = _load_claude_settings(settings_path)
    hooks = settings.get("hooks", {})

    hook_types_to_clean = list(_get_pyafk_hooks().keys())
    hooks_removed = False
    for hook_type in hook_types_to_clean:
        if hook_type in hooks:
            original_count = len(hooks[hook_type])
            hooks[hook_type] = [h for h in hooks[hook_type] if not _is_pyafk_hook(h)]
            if len(hooks[hook_type]) < original_count:
                hooks_removed = True
            if not hooks[hook_type]:
                del hooks[hook_type]

    if hooks:
        settings["hooks"] = hooks
    elif "hooks" in settings:
        del settings["hooks"]

    if hooks_removed:
        _save_claude_settings(settings_path, settings)
        print("Removed pyafk hooks from Claude settings.")
    else:
        print("No pyafk hooks found in Claude settings.")


def cmd_reset(args):
    """Reset pyafk - clear database and rules."""
    pyafk_dir = get_pyafk_dir()
    db_path = pyafk_dir / "pyafk.db"

    if not db_path.exists():
        print("Nothing to reset - database doesn't exist.")
        return

    # Show what will be deleted
    db_size = db_path.stat().st_size
    print("This will delete:")
    print(f"  - Database: {db_size / 1024:.1f} KB")
    print("  - All pending requests")
    print("  - All auto-approve rules")
    print("  - All session history")
    print()
    print("Config (Telegram credentials) will be kept.")
    print()

    if not args.force:
        try:
            confirm = input("Proceed with reset? [y/N] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return
        if confirm not in ("y", "yes"):
            print("Cancelled.")
            return

    db_path.unlink()
    print("Reset complete.")


def cmd_hook(args):
    """Internal hook handler."""
    from pyafk.fast_path import FastPathResult, check_fast_path
    from pyafk.hooks.handler import handle_hook

    pyafk_dir = get_pyafk_dir()

    result = check_fast_path()
    if result == FastPathResult.APPROVE:
        print(json.dumps({"decision": "approve"}))
        return
    elif result == FastPathResult.DENY:
        print(json.dumps({"decision": "deny"}))
        return
    elif result == FastPathResult.FALLBACK:
        print(json.dumps({}))
        return

    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input"}))
        sys.exit(1)

    response = asyncio.run(handle_hook(args.hook_type, hook_input, pyafk_dir))
    print(json.dumps(response))


def cmd_debug_on(args):
    """Enable debug logging."""
    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)
    config.set_debug(True)
    print("Debug mode enabled")


def cmd_debug_off(args):
    """Disable debug logging."""
    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)
    config.set_debug(False)
    print("Debug mode disabled")


def cmd_rules_list(args):
    """List all rules."""
    pyafk_dir = get_pyafk_dir()
    rules_data = _get_rules(pyafk_dir)

    if not rules_data:
        print("No rules defined.")
        return

    for rule in rules_data:
        print(f"[{rule['id']}] {rule['pattern']} -> {rule['action']}")


def cmd_rules_add(args):
    """Add a new rule."""
    pyafk_dir = get_pyafk_dir()
    rule_id = _add_rule(pyafk_dir, args.pattern, args.action)
    print(f"Added rule [{rule_id}]: {args.pattern} -> {args.action}")


def cmd_rules_remove(args):
    """Remove a rule by ID."""
    pyafk_dir = get_pyafk_dir()
    removed = _remove_rule(pyafk_dir, args.rule_id)
    if removed:
        print(f"Removed rule [{args.rule_id}]")
    else:
        print(f"Rule [{args.rule_id}] not found")


def cmd_telegram_test(args):
    """Send a test message."""
    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)

    if not config.telegram_bot_token or not config.telegram_chat_id:
        print("Telegram not configured. Run 'pyafk telegram setup' first.")
        return

    _do_telegram_test(config)


def cmd_captain_hook_install(args):
    """Install pyafk hooks for captain-hook."""
    if not CAPTAIN_HOOK_DIR.exists():
        print(f"Error: captain-hook not found at {CAPTAIN_HOOK_DIR}")
        print("Run 'captain-hook' first to initialize.")
        sys.exit(1)

    _do_captain_hook_install()


def cmd_captain_hook_uninstall(args):
    """Remove pyafk hooks from captain-hook."""
    removed = False

    for event in HOOK_EVENTS:
        wrapper_name = f"pyafk-{event}.sh"
        wrapper_path = CAPTAIN_HOOK_DIR / event / wrapper_name
        if wrapper_path.exists():
            wrapper_path.unlink()
            print(f"Removed: {event}/{wrapper_name}")
            removed = True

    if removed:
        print()
        print("Done! Run 'captain-hook toggle' to update runners.")
    else:
        print("No pyafk hooks found in captain-hook.")


def cmd_env_list(args):
    """List all env var overrides."""
    config = Config(get_pyafk_dir())
    env_vars = config.list_env()

    if not env_vars:
        print("No env var overrides set.")
        return

    for key, value in sorted(env_vars.items()):
        print(f"{key}={value}")


def cmd_env_set(args):
    """Set an env var override."""
    config = Config(get_pyafk_dir())
    config.set_env(args.key, args.value)
    print(f"Set {args.key}={args.value}")


def cmd_env_unset(args):
    """Unset an env var override."""
    config = Config(get_pyafk_dir())
    if config.unset_env(args.key):
        print(f"Unset {args.key}")
    else:
        print(f"{args.key} not found")


# =============================================================================
# Main entry point
# =============================================================================


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="pyafk - Remote approval system for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command")

    # status
    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.set_defaults(func=cmd_status)

    # on
    on_parser = subparsers.add_parser("on", help="Enable pyafk")
    on_parser.set_defaults(func=cmd_on)

    # off
    off_parser = subparsers.add_parser("off", help="Disable pyafk")
    off_parser.set_defaults(func=cmd_off)

    # install
    install_parser = subparsers.add_parser(
        "install", help="Install pyafk hooks (standalone)"
    )
    install_parser.set_defaults(func=cmd_install)

    # uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall pyafk hooks")
    uninstall_parser.set_defaults(func=cmd_uninstall)

    # reset
    reset_parser = subparsers.add_parser("reset", help="Reset database and rules")
    reset_parser.add_argument("--force", action="store_true", help="Skip confirmation")
    reset_parser.set_defaults(func=cmd_reset)

    # hook (internal)
    hook_parser = subparsers.add_parser("hook", help="Internal hook handler")
    hook_parser.add_argument("hook_type", help="Hook type (PreToolUse, etc.)")
    hook_parser.set_defaults(func=cmd_hook)

    # debug
    debug_parser = subparsers.add_parser("debug", help="Debug mode commands")
    debug_subparsers = debug_parser.add_subparsers(dest="debug_command")

    debug_on_parser = debug_subparsers.add_parser("on", help="Enable debug logging")
    debug_on_parser.set_defaults(func=cmd_debug_on)

    debug_off_parser = debug_subparsers.add_parser("off", help="Disable debug logging")
    debug_off_parser.set_defaults(func=cmd_debug_off)

    # rules
    rules_parser = subparsers.add_parser("rules", help="Manage auto-approve rules")
    rules_subparsers = rules_parser.add_subparsers(dest="rules_command")

    rules_list_parser = rules_subparsers.add_parser("list", help="List all rules")
    rules_list_parser.set_defaults(func=cmd_rules_list)

    rules_add_parser = rules_subparsers.add_parser("add", help="Add a new rule")
    rules_add_parser.add_argument("pattern", help="Pattern to match")
    rules_add_parser.add_argument(
        "--action",
        choices=["approve", "deny"],
        default="approve",
        help="Action (default: approve)",
    )
    rules_add_parser.set_defaults(func=cmd_rules_add)

    rules_remove_parser = rules_subparsers.add_parser("remove", help="Remove a rule")
    rules_remove_parser.add_argument("rule_id", type=int, help="Rule ID to remove")
    rules_remove_parser.set_defaults(func=cmd_rules_remove)

    # telegram
    telegram_parser = subparsers.add_parser("telegram", help="Telegram configuration")
    telegram_subparsers = telegram_parser.add_subparsers(dest="telegram_command")

    telegram_test_parser = telegram_subparsers.add_parser(
        "test", help="Send a test message"
    )
    telegram_test_parser.set_defaults(func=cmd_telegram_test)

    # env - environment variable overrides
    env_parser = subparsers.add_parser("env", help="Manage env var overrides")
    env_subparsers = env_parser.add_subparsers(dest="env_command")

    env_list_parser = env_subparsers.add_parser("list", help="List env var overrides")
    env_list_parser.set_defaults(func=cmd_env_list)

    env_set_parser = env_subparsers.add_parser("set", help="Set an env var override")
    env_set_parser.add_argument("key", help="Variable name (e.g., DISABLE_STOP_HOOK)")
    env_set_parser.add_argument("value", help="Value (e.g., true)")
    env_set_parser.set_defaults(func=cmd_env_set)

    env_unset_parser = env_subparsers.add_parser(
        "unset", help="Remove an env var override"
    )
    env_unset_parser.add_argument("key", help="Variable name to remove")
    env_unset_parser.set_defaults(func=cmd_env_unset)

    # captain-hook
    captain_parser = subparsers.add_parser(
        "captain-hook", help="Captain-hook integration"
    )
    captain_subparsers = captain_parser.add_subparsers(dest="captain_command")

    captain_install_parser = captain_subparsers.add_parser(
        "install", help="Install pyafk hooks for captain-hook"
    )
    captain_install_parser.set_defaults(func=cmd_captain_hook_install)

    captain_uninstall_parser = captain_subparsers.add_parser(
        "uninstall", help="Remove pyafk hooks from captain-hook"
    )
    captain_uninstall_parser.set_defaults(func=cmd_captain_hook_uninstall)

    args = parser.parse_args()

    if args.command is None:
        # No command - run interactive mode
        interactive_menu()
    elif hasattr(args, "func"):
        args.func(args)
    else:
        # Subcommand group without specific command - show help
        parser.parse_args([args.command, "--help"])


if __name__ == "__main__":
    main()
