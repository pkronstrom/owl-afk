"""CLI command handlers."""

import asyncio
import json
import sys

from pyafk.cli.helpers import add_rule, do_telegram_test, get_rules, remove_rule
from pyafk.cli.install import (
    CAPTAIN_HOOK_DIR,
    HOOK_EVENTS,
    check_hooks_installed,
    do_captain_hook_install,
    do_standalone_install,
    get_pyafk_hooks,
    is_pyafk_hook,
    load_claude_settings,
    get_claude_settings_path,
    save_claude_settings,
)
from pyafk.utils.config import Config, get_pyafk_dir


def cmd_status(args):
    """Show current status."""
    from pyafk.cli.ui import console

    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)
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
    console.print(f"[bold]Config:[/bold] [dim]{pyafk_dir}[/dim]")

    # Telegram
    if config.telegram_bot_token and config.telegram_chat_id:
        console.print("[bold]Telegram:[/bold] [green]configured[/green]")
    else:
        console.print("[bold]Telegram:[/bold] [yellow]not configured[/yellow]")

    from pyafk.daemon import get_daemon_pid, is_daemon_running

    # Daemon
    if is_daemon_running(pyafk_dir):
        pid = get_daemon_pid(pyafk_dir)
        console.print(
            f"[bold]Daemon:[/bold] [green]running[/green] [dim](pid {pid})[/dim]"
        )
    else:
        console.print("[bold]Daemon:[/bold] [dim]not running[/dim]")

    # Hooks
    hooks_installed, hooks_mode = check_hooks_installed()
    if hooks_installed:
        console.print(f"[bold]Hooks:[/bold] [green]{hooks_mode}[/green]")
    else:
        console.print("[bold]Hooks:[/bold] [yellow]not installed[/yellow]")


def cmd_on(project: str | None):
    """Enable pyafk."""
    from pathlib import Path

    from pyafk.cli.ui import console

    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)

    hooks_installed, hooks_mode = check_hooks_installed()
    if not hooks_installed:
        console.print("[yellow]Warning: No pyafk hooks installed![/yellow]")
        console.print("[dim]Install hooks with: pyafk install[/dim]")
        console.print()

    if project is not None:
        # Project specified: add to enabled list
        if project == ".":
            # Use current directory
            project = str(Path.cwd())
        config.add_enabled_project(project)
        config.set_mode("on")
        console.print(f"[green]✓ pyafk enabled[/green] for [cyan]{project}[/cyan]")
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
            if not config.daemon_enabled:
                console.print(
                    f"[green]✓ pyafk enabled[/green] [dim]({mode_info}, inline polling)[/dim]"
                )
            else:
                from pyafk.daemon import is_daemon_running, start_daemon

                if is_daemon_running(pyafk_dir):
                    console.print(
                        f"[green]✓ pyafk enabled[/green] [dim]({mode_info}, daemon already running)[/dim]"
                    )
                elif start_daemon(pyafk_dir):
                    console.print(
                        f"[green]✓ pyafk enabled[/green] [dim]({mode_info}, daemon started)[/dim]"
                    )
                else:
                    console.print(
                        f"[yellow]⚠ pyafk enabled[/yellow] [dim]({mode_info}, daemon failed to start)[/dim]"
                    )
        else:
            console.print(
                f"[yellow]⚠ pyafk enabled[/yellow] [dim]({mode_info}, no Telegram configured)[/dim]"
            )


def cmd_off(project: str | None):
    """Disable pyafk."""
    from pathlib import Path

    from pyafk.cli.ui import console

    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)

    if project is not None:
        # Project specified: remove from enabled list
        if project == ".":
            project = str(Path.cwd())

        if config.remove_enabled_project(project):
            console.print(
                f"[yellow]⏸ pyafk disabled[/yellow] for [cyan]{project}[/cyan]"
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
                            "⏸️ pyafk off - please retry command",
                        )
                    except Exception as e:
                        # Message edit may fail if message was deleted or too old
                        from pyafk.utils.debug import debug

                        debug("cmd", f"Failed to edit message: {e}")
                await storage.resolve_request(
                    request_id=request.id,
                    status="denied",
                    resolved_by="pyafk_off",
                    denial_reason="pyafk disabled - please retry your command",
                )

            pending_stops = await storage.get_all_pending_stops()
            for stop in pending_stops:
                if stop.get("telegram_msg_id"):
                    try:
                        await notifier.edit_message(
                            stop["telegram_msg_id"],
                            "⏸️ pyafk off - session ended",
                        )
                    except Exception as e:
                        # Message edit may fail if message was deleted or too old
                        from pyafk.utils.debug import debug

                        debug("cmd", f"Failed to edit stop message: {e}")
                await storage.resolve_stop(stop["session_id"], "ok")

            return len(pending) + len(pending_stops)
        finally:
            await storage.close()

    cleaned = asyncio.run(cleanup())

    from pyafk.cli.ui import console
    from pyafk.daemon import is_daemon_running

    if is_daemon_running(pyafk_dir):
        console.print(
            f"[yellow]⏸ pyafk off[/yellow] [dim]({cleaned} pending rejected, use /afk on in Telegram)[/dim]"
        )
    else:
        console.print(
            f"[yellow]⏸ pyafk off[/yellow] [dim]({cleaned} pending rejected, use 'pyafk on' to start)[/dim]"
        )


def cmd_install(args):
    """Install pyafk hooks."""
    pyafk_dir = get_pyafk_dir()
    pyafk_dir.mkdir(parents=True, exist_ok=True)
    do_standalone_install(pyafk_dir)


def cmd_uninstall(args):
    """Uninstall pyafk hooks."""
    settings_path = get_claude_settings_path()

    settings = load_claude_settings(settings_path)
    hooks = settings.get("hooks", {})

    hook_types_to_clean = list(get_pyafk_hooks().keys())
    hooks_removed = False
    for hook_type in hook_types_to_clean:
        if hook_type in hooks:
            original_count = len(hooks[hook_type])
            hooks[hook_type] = [h for h in hooks[hook_type] if not is_pyafk_hook(h)]
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
    rules_data = get_rules(pyafk_dir)

    if not rules_data:
        print("No rules defined.")
        return

    for rule in rules_data:
        print(f"[{rule['id']}] {rule['pattern']} -> {rule['action']}")


def cmd_rules_add(args):
    """Add a new rule."""
    pyafk_dir = get_pyafk_dir()
    rule_id = add_rule(pyafk_dir, args.pattern, args.action)
    print(f"Added rule [{rule_id}]: {args.pattern} -> {args.action}")


def cmd_rules_remove(args):
    """Remove a rule by ID."""
    pyafk_dir = get_pyafk_dir()
    removed = remove_rule(pyafk_dir, args.rule_id)
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

    do_telegram_test(config)


def cmd_captain_hook_install(args):
    """Install pyafk hooks for captain-hook."""
    if not CAPTAIN_HOOK_DIR.exists():
        print(f"Error: captain-hook not found at {CAPTAIN_HOOK_DIR}")
        print("Run 'captain-hook' first to initialize.")
        sys.exit(1)

    do_captain_hook_install()


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
