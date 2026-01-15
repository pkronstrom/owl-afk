"""CLI command handlers."""

import asyncio
import json
import sys

from owl.cli.helpers import add_rule, do_telegram_test, get_rules, remove_rule
from owl.cli.install import (
    HAWK_HOOKS_DIR,
    HOOK_EVENTS,
    check_hooks_installed,
    do_hawk_hooks_install,
    do_standalone_install,
    get_owl_hooks,
    is_owl_hook,
    load_claude_settings,
    get_claude_settings_path,
    save_claude_settings,
)
from owl.utils.config import Config, get_owl_dir


def cmd_status(args):
    """Show current status."""
    from owl.cli.ui import console

    owl_dir = get_owl_dir()
    config = Config(owl_dir)
    mode = config.get_mode()

    # Mode with color
    mode_color = "green" if mode == "on" else "yellow"
    if mode == "on" and config.enabled_projects:
        console.print(
            f"[bold]Mode:[/bold] [{mode_color}]{mode}[/{mode_color}] [dim](filtered)[/dim]"
        )
        for project in config.enabled_projects:
            console.print(f"  [cyan]{project}[/cyan]")
    else:
        console.print(f"[bold]Mode:[/bold] [{mode_color}]{mode}[/{mode_color}]")

    # Debug
    debug_color = "green" if config.debug else "dim"
    console.print(
        f"[bold]Debug:[/bold] [{debug_color}]{'on' if config.debug else 'off'}[/{debug_color}]"
    )

    # Config dir
    console.print(f"[bold]Config:[/bold] [dim]{owl_dir}[/dim]")

    # Telegram
    if config.telegram_bot_token and config.telegram_chat_id:
        console.print("[bold]Telegram:[/bold] [green]configured[/green]")
    else:
        console.print("[bold]Telegram:[/bold] [yellow]not configured[/yellow]")

    # Hooks
    hooks_installed, hooks_mode = check_hooks_installed()
    if hooks_installed:
        console.print(f"[bold]Hooks:[/bold] [green]{hooks_mode}[/green]")
    else:
        console.print("[bold]Hooks:[/bold] [yellow]not installed[/yellow]")


def cmd_on(project: str | None):
    """Enable owl."""
    from pathlib import Path

    from owl.cli.ui import console

    owl_dir = get_owl_dir()
    config = Config(owl_dir)

    hooks_installed, hooks_mode = check_hooks_installed()
    if not hooks_installed:
        console.print("[yellow]Warning: No owl hooks installed![/yellow]")
        console.print("[dim]Install hooks with: owl install[/dim]")
        console.print()

    if project is not None:
        # Project specified: add to enabled list
        if project == ".":
            # Use current directory
            project = str(Path.cwd())
        config.add_enabled_project(project)
        config.set_mode("on")
        console.print(f"[green]✓ owl enabled[/green] for [cyan]{project}[/cyan]")
        if len(config.enabled_projects) > 1:
            console.print(
                f"[dim]Enabled projects: {', '.join(config.enabled_projects)}[/dim]"
            )
    else:
        # Global on: clear project filter
        config.clear_enabled_projects()
        config.set_mode("on")

        mode_info = f"via {hooks_mode}" if hooks_installed else "no hooks"

        if config.telegram_bot_token and config.telegram_chat_id:
            console.print(f"[green]✓ owl enabled[/green] [dim]({mode_info})[/dim]")
        else:
            console.print(
                f"[yellow]⚠ owl enabled[/yellow] [dim]({mode_info}, no Telegram configured)[/dim]"
            )


def cmd_off(project: str | None):
    """Disable owl."""
    from pathlib import Path

    from owl.cli.ui import console

    owl_dir = get_owl_dir()
    config = Config(owl_dir)

    if project is not None:
        # Project specified: remove from enabled list
        if project == ".":
            project = str(Path.cwd())

        if config.remove_enabled_project(project):
            console.print(
                f"[yellow]⏸ owl disabled[/yellow] for [cyan]{project}[/cyan]"
            )
            if config.enabled_projects:
                console.print(
                    f"[dim]Still enabled for: {', '.join(config.enabled_projects)}[/dim]"
                )
            else:
                # List is empty, auto-off
                config.set_mode("off")
                console.print("[dim]No projects enabled, mode set to off[/dim]")
        else:
            console.print(f"[yellow]Project not in enabled list:[/yellow] {project}")
        return

    # Global off
    config.set_mode("off")

    async def cleanup():
        from owl.core.storage import Storage
        from owl.notifiers.telegram import TelegramNotifier

        if not config.telegram_bot_token or not config.telegram_chat_id:
            return 0

        storage = Storage(owl_dir / "owl.db")
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
                            "⏸️ owl off - please retry command",
                        )
                    except Exception as e:
                        # Message edit may fail if message was deleted or too old
                        from owl.utils.debug import debug

                        debug("cmd", f"Failed to edit message: {e}")
                await storage.resolve_request(
                    request_id=request.id,
                    status="denied",
                    resolved_by="owl_off",
                    denial_reason="owl disabled - please retry your command",
                )

            pending_stops = await storage.get_all_pending_stops()
            for stop in pending_stops:
                if stop.get("telegram_msg_id"):
                    try:
                        await notifier.edit_message(
                            stop["telegram_msg_id"],
                            "⏸️ owl off - session ended",
                        )
                    except Exception as e:
                        # Message edit may fail if message was deleted or too old
                        from owl.utils.debug import debug

                        debug("cmd", f"Failed to edit stop message: {e}")
                await storage.resolve_stop(stop["session_id"], "ok")

            return len(pending) + len(pending_stops)
        finally:
            await storage.close()

    cleaned = asyncio.run(cleanup())

    from owl.cli.ui import console

    console.print(
        f"[yellow]⏸ owl off[/yellow] [dim]({cleaned} pending rejected)[/dim]"
    )


def cmd_install(args):
    """Install owl hooks."""
    owl_dir = get_owl_dir()
    owl_dir.mkdir(parents=True, exist_ok=True)
    do_standalone_install(owl_dir)


def cmd_uninstall(args):
    """Uninstall owl hooks."""
    settings_path = get_claude_settings_path()

    settings = load_claude_settings(settings_path)
    hooks = settings.get("hooks", {})

    hook_types_to_clean = list(get_owl_hooks().keys())
    hooks_removed = False
    for hook_type in hook_types_to_clean:
        if hook_type in hooks:
            original_count = len(hooks[hook_type])
            hooks[hook_type] = [h for h in hooks[hook_type] if not is_owl_hook(h)]
            if len(hooks[hook_type]) < original_count:
                hooks_removed = True
            if not hooks[hook_type]:
                del hooks[hook_type]

    if hooks:
        settings["hooks"] = hooks
    elif "hooks" in settings:
        del settings["hooks"]

    if hooks_removed:
        save_claude_settings(settings_path, settings)
        print("Removed owl hooks from Claude settings.")
    else:
        print("No owl hooks found in Claude settings.")


def cmd_reset(args):
    """Reset owl - clear database and rules."""
    owl_dir = get_owl_dir()
    db_path = owl_dir / "owl.db"

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
    from owl.fast_path import FastPathResult, check_fast_path
    from owl.hooks.handler import handle_hook

    owl_dir = get_owl_dir()

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

    response = asyncio.run(handle_hook(args.hook_type, hook_input, owl_dir))
    print(json.dumps(response))


def cmd_debug_on(args):
    """Enable debug logging."""
    owl_dir = get_owl_dir()
    config = Config(owl_dir)
    config.set_debug(True)
    print("Debug mode enabled")


def cmd_debug_off(args):
    """Disable debug logging."""
    owl_dir = get_owl_dir()
    config = Config(owl_dir)
    config.set_debug(False)
    print("Debug mode disabled")


def cmd_rules_list(args):
    """List all rules."""
    owl_dir = get_owl_dir()
    rules_data = get_rules(owl_dir)

    if not rules_data:
        print("No rules defined.")
        return

    for rule in rules_data:
        print(f"[{rule['id']}] {rule['pattern']} -> {rule['action']}")


def cmd_rules_add(args):
    """Add a new rule."""
    owl_dir = get_owl_dir()
    rule_id = add_rule(owl_dir, args.pattern, args.action)
    print(f"Added rule [{rule_id}]: {args.pattern} -> {args.action}")


def cmd_rules_remove(args):
    """Remove a rule by ID."""
    owl_dir = get_owl_dir()
    removed = remove_rule(owl_dir, args.rule_id)
    if removed:
        print(f"Removed rule [{args.rule_id}]")
    else:
        print(f"Rule [{args.rule_id}] not found")


def cmd_telegram_test(args):
    """Send a test message."""
    owl_dir = get_owl_dir()
    config = Config(owl_dir)

    if not config.telegram_bot_token or not config.telegram_chat_id:
        print("Telegram not configured. Run 'owl telegram setup' first.")
        return

    do_telegram_test(config)


def cmd_hawk_hooks_install(args):
    """Install owl hooks for hawk-hooks."""
    if not HAWK_HOOKS_DIR.exists():
        print(f"Error: hawk-hooks not found at {HAWK_HOOKS_DIR}")
        print("Run 'hawk-hooks' first to initialize.")
        sys.exit(1)

    do_hawk_hooks_install()


def cmd_hawk_hooks_uninstall(args):
    """Remove owl hooks from hawk-hooks."""
    removed = False

    for event in HOOK_EVENTS:
        wrapper_name = f"owl-{event}.sh"
        wrapper_path = HAWK_HOOKS_DIR / event / wrapper_name
        if wrapper_path.exists():
            wrapper_path.unlink()
            print(f"Removed: {event}/{wrapper_name}")
            removed = True

    if removed:
        print()
        print("Done! Run 'hawk-hooks toggle' to update runners.")
    else:
        print("No owl hooks found in hawk-hooks.")


def cmd_env_list(args):
    """List all env var overrides."""
    config = Config(get_owl_dir())
    env_vars = config.list_env()

    if not env_vars:
        print("No env var overrides set.")
        return

    for key, value in sorted(env_vars.items()):
        print(f"{key}={value}")


def cmd_env_set(args):
    """Set an env var override."""
    config = Config(get_owl_dir())
    config.set_env(args.key, args.value)
    print(f"Set {args.key}={args.value}")


def cmd_env_unset(args):
    """Unset an env var override."""
    config = Config(get_owl_dir())
    if config.unset_env(args.key):
        print(f"Unset {args.key}")
    else:
        print(f"{args.key} not found")
