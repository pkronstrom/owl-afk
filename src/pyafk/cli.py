"""CLI entry point."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import click

from pyafk.utils.config import Config, get_pyafk_dir


@click.group()
@click.pass_context
def main(ctx):
    """pyafk - Remote approval system for Claude Code."""
    ctx.ensure_object(dict)
    ctx.obj["pyafk_dir"] = get_pyafk_dir()


@main.command()
@click.pass_context
def status(ctx):
    """Show current status."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    mode = config.get_mode()

    click.echo(f"Mode: {mode}")
    click.echo(f"Debug: {'on' if config.debug else 'off'}")
    click.echo(f"Config dir: {pyafk_dir}")

    # Telegram status
    if config.telegram_bot_token and config.telegram_chat_id:
        click.echo("Telegram: configured")
    else:
        click.echo("Telegram: not configured")

    # Daemon status
    from pyafk.daemon import get_daemon_pid, is_daemon_running

    if is_daemon_running(pyafk_dir):
        pid = get_daemon_pid(pyafk_dir)
        click.echo(f"Daemon: running (pid {pid})")
    else:
        click.echo("Daemon: not running")


@main.command("on")
@click.pass_context
def on_command(ctx):
    """Enable pyafk and start background daemon."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    config.set_mode("on")

    # Start daemon if Telegram is configured
    if config.telegram_bot_token and config.telegram_chat_id:
        from pyafk.daemon import is_daemon_running, start_daemon

        if is_daemon_running(pyafk_dir):
            click.echo("pyafk enabled (daemon already running)")
        elif start_daemon(pyafk_dir):
            click.echo("pyafk enabled (daemon started)")
        else:
            click.echo("pyafk enabled (daemon failed to start)")
    else:
        click.echo("pyafk enabled (no Telegram configured)")


@main.command("off")
@click.pass_context
def off_command(ctx):
    """Disable pyafk and clean up pending messages (daemon keeps running for /afk on)."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    config.set_mode("off")

    # Keep daemon running so /afk on works from Telegram
    # Pending requests stay pending - can still approve via Telegram after /afk on
    from pyafk.daemon import is_daemon_running

    if is_daemon_running(pyafk_dir):
        click.echo("pyafk off (daemon still running, use /afk on in Telegram to re-enable)")
    else:
        click.echo("pyafk off (daemon not running, use 'pyafk on' to start)")


@main.command("disable")
@click.pass_context
def disable_command(ctx):
    """Fully disable pyafk - stop daemon and set mode off."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    config.set_mode("off")

    # Stop daemon
    from pyafk.daemon import is_daemon_running, stop_daemon

    daemon_stopped = False
    if is_daemon_running(pyafk_dir):
        daemon_stopped = stop_daemon(pyafk_dir)

    # Clean up pending Telegram messages
    async def cleanup():
        from pyafk.core.storage import Storage
        from pyafk.notifiers.telegram import TelegramNotifier

        if not config.telegram_bot_token or not config.telegram_chat_id:
            return 0

        storage = Storage(pyafk_dir / "pyafk.db")
        await storage.connect()

        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        # Get and clean up pending requests - fallback to CLI
        pending = await storage.get_pending_requests()
        for request in pending:
            if request.telegram_msg_id:
                await notifier.edit_message(
                    request.telegram_msg_id,
                    "⏸️ pyafk disabled - falling back to CLI",
                )
            await storage.resolve_request(
                request_id=request.id,
                status="fallback",
                resolved_by="pyafk_disable",
            )

        await storage.close()
        return len(pending)

    cleaned = asyncio.run(cleanup())
    daemon_msg = ", daemon stopped" if daemon_stopped else ""
    click.echo(f"pyafk disabled ({cleaned} pending requests -> CLI fallback{daemon_msg})")


@main.group()
def debug():
    """Debug mode commands."""
    pass


@debug.command("on")
@click.pass_context
def debug_on(ctx):
    """Enable debug logging."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    config.set_debug(True)
    click.echo("Debug mode enabled")


@debug.command("off")
@click.pass_context
def debug_off(ctx):
    """Disable debug logging."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    config.set_debug(False)
    click.echo("Debug mode disabled")


@main.group()
def rules():
    """Manage auto-approve rules."""
    pass


@rules.command("list")
@click.pass_context
def rules_list(ctx):
    """List all rules."""
    pyafk_dir = ctx.obj["pyafk_dir"]

    async def _list_rules():
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

    rules_data = asyncio.run(_list_rules())

    if not rules_data:
        click.echo("No rules defined.")
        return

    for rule in rules_data:
        click.echo(f"[{rule['id']}] {rule['pattern']} -> {rule['action']}")


@rules.command("add")
@click.argument("pattern")
@click.option("--approve", "action", flag_value="approve", default=True, help="Auto-approve matching tools")
@click.option("--deny", "action", flag_value="deny", help="Auto-deny matching tools")
@click.option("--priority", default=0, type=int, help="Rule priority (higher = checked first)")
@click.pass_context
def rules_add(ctx, pattern: str, action: str, priority: int):
    """Add a new rule."""
    pyafk_dir = ctx.obj["pyafk_dir"]

    async def _add_rule():
        from pyafk.core.rules import RulesEngine
        from pyafk.core.storage import Storage

        config = Config(pyafk_dir)
        storage = Storage(config.db_path)
        await storage.connect()
        try:
            engine = RulesEngine(storage)
            rule_id = await engine.add_rule(pattern, action, priority, created_via="cli")
            return rule_id
        finally:
            await storage.close()

    rule_id = asyncio.run(_add_rule())
    click.echo(f"Added rule [{rule_id}]: {pattern} -> {action}")


@rules.command("remove")
@click.argument("rule_id", type=int)
@click.pass_context
def rules_remove(ctx, rule_id: int):
    """Remove a rule by ID."""
    pyafk_dir = ctx.obj["pyafk_dir"]

    async def _remove_rule():
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

    removed = asyncio.run(_remove_rule())
    if removed:
        click.echo(f"Removed rule [{rule_id}]")
    else:
        click.echo(f"Rule [{rule_id}] not found")


@main.group()
def telegram():
    """Telegram configuration."""
    pass


@telegram.command("setup")
@click.pass_context
def telegram_setup(ctx):
    """Interactive Telegram setup."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)

    click.echo("Telegram Bot Setup")
    click.echo("==================")
    click.echo()
    click.echo("1. Create a bot via @BotFather on Telegram")
    click.echo("2. Copy the bot token")
    click.echo()

    bot_token = click.prompt("Bot token", default=config.telegram_bot_token or "")
    if not bot_token:
        click.echo("Setup cancelled.")
        return

    click.echo()
    click.echo("3. Start a chat with your bot")
    click.echo("4. Send a message to the bot")
    click.echo("5. Get your chat ID from the bot or use @userinfobot")
    click.echo()

    chat_id = click.prompt("Chat ID", default=config.telegram_chat_id or "")
    if not chat_id:
        click.echo("Setup cancelled.")
        return

    config.telegram_bot_token = bot_token
    config.telegram_chat_id = chat_id
    config.save()

    click.echo()
    click.echo("Telegram configured successfully!")
    click.echo("Run 'pyafk telegram test' to verify.")


@telegram.command("test")
@click.pass_context
def telegram_test(ctx):
    """Send a test message."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)

    if not config.telegram_bot_token or not config.telegram_chat_id:
        click.echo("Telegram not configured. Run 'pyafk telegram setup' first.")
        return

    async def _send_test():
        from pyafk.notifiers.telegram import TelegramNotifier

        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        result = await notifier._api_request(
            "sendMessage",
            data={
                "chat_id": config.telegram_chat_id,
                "text": "pyafk test message - Telegram is configured correctly!",
            },
        )
        return result

    result = asyncio.run(_send_test())

    if result.get("ok"):
        click.echo("Test message sent successfully!")
    else:
        error = result.get("error", result.get("description", "Unknown error"))
        click.echo(f"Failed to send message: {error}")


@main.command("hook")
@click.argument("hook_type")
@click.pass_context
def hook(ctx, hook_type: str):
    """Internal hook handler (reads JSON from stdin)."""
    from pyafk.fast_path import FastPathResult, check_fast_path
    from pyafk.hooks.handler import handle_hook

    pyafk_dir = ctx.obj["pyafk_dir"]

    # Fast path check first
    result = check_fast_path()
    if result == FastPathResult.APPROVE:
        click.echo(json.dumps({"decision": "approve"}))
        return
    elif result == FastPathResult.DENY:
        click.echo(json.dumps({"decision": "deny"}))
        return
    elif result == FastPathResult.FALLBACK:
        # pyafk is off - reject with explanation
        click.echo(json.dumps({
            "decision": "block",
            "reason": "pyafk is currently disabled. Use /afk on in Telegram or run 'pyafk on' to enable remote approvals.",
        }))
        return

    # Read stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        click.echo(json.dumps({"error": "Invalid JSON input"}))
        ctx.exit(1)
        return

    # Run async handler
    response = asyncio.run(handle_hook(hook_type, hook_input, pyafk_dir))
    click.echo(json.dumps(response))


@main.command("reset")
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.pass_context
def reset_command(ctx, force):
    """Reset pyafk - clear database and rules."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    db_path = pyafk_dir / "pyafk.db"

    if not db_path.exists():
        click.echo("Nothing to reset - database doesn't exist.")
        return

    # Show what will be deleted
    db_size = db_path.stat().st_size
    click.echo(f"This will delete:")
    click.echo(f"  - Database: {db_size / 1024:.1f} KB")
    click.echo(f"  - All pending requests")
    click.echo(f"  - All auto-approve rules")
    click.echo(f"  - All session history")
    click.echo()
    click.echo("Config (Telegram credentials) will be kept.")
    click.echo()

    if not force:
        if not click.confirm("Proceed with reset?"):
            click.echo("Cancelled.")
            return

    db_path.unlink()
    click.echo("Reset complete.")


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
    # Check direct command
    command = hook_entry.get("command", "")
    if "pyafk hook" in command:
        return True
    # Check nested hooks array
    for hook in hook_entry.get("hooks", []):
        if "pyafk hook" in hook.get("command", ""):
            return True
    return False


@main.command("install")
@click.pass_context
def install_command(ctx):
    """Install pyafk hooks into Claude Code."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    settings_path = _get_claude_settings_path()

    click.echo("pyafk Installation")
    click.echo("==================")
    click.echo()

    # Ensure pyafk directory exists
    pyafk_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"pyafk directory: {pyafk_dir}")

    # Load existing settings
    settings = _load_claude_settings(settings_path)
    existing_hooks = settings.get("hooks", {})

    # Get pyafk hooks to install
    pyafk_hooks = _get_pyafk_hooks()

    # Merge hooks (add pyafk hooks, preserve others)
    new_hooks = existing_hooks.copy()
    for hook_type, hook_entries in pyafk_hooks.items():
        if hook_type not in new_hooks:
            new_hooks[hook_type] = []
        # Remove any existing pyafk hooks for this type
        new_hooks[hook_type] = [h for h in new_hooks[hook_type] if not _is_pyafk_hook(h)]
        # Add the new pyafk hooks
        new_hooks[hook_type].extend(hook_entries)

    settings["hooks"] = new_hooks

    click.echo()
    click.echo("Will configure the following hooks:")
    for hook_type in pyafk_hooks:
        click.echo(f"  - {hook_type}: pyafk hook {hook_type}")
    click.echo()
    click.echo(f"Settings file: {settings_path}")
    click.echo()

    if not click.confirm("Proceed with installation?"):
        click.echo("Installation cancelled.")
        return

    # Ensure claude dir exists
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Save settings
    _save_claude_settings(settings_path, settings)
    click.echo()
    click.echo("Installation complete!")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Run 'pyafk telegram setup' to configure notifications")
    click.echo("  2. Run 'pyafk on' to enable remote approvals")
    click.echo("  3. Start Claude Code and go AFK!")


@main.command("uninstall")
@click.pass_context
def uninstall_command(ctx):
    """Uninstall pyafk hooks from Claude Code."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    settings_path = _get_claude_settings_path()

    click.echo("pyafk Uninstallation")
    click.echo("====================")
    click.echo()

    # Remove hooks from Claude settings
    settings = _load_claude_settings(settings_path)
    hooks = settings.get("hooks", {})

    # Remove pyafk hooks - use same list as _get_pyafk_hooks()
    hook_types_to_clean = list(_get_pyafk_hooks().keys())
    hooks_removed = False
    for hook_type in hook_types_to_clean:
        if hook_type in hooks:
            original_count = len(hooks[hook_type])
            hooks[hook_type] = [h for h in hooks[hook_type] if not _is_pyafk_hook(h)]
            if len(hooks[hook_type]) < original_count:
                hooks_removed = True
            # Remove empty hook lists
            if not hooks[hook_type]:
                del hooks[hook_type]

    if hooks:
        settings["hooks"] = hooks
    elif "hooks" in settings:
        del settings["hooks"]

    if hooks_removed:
        _save_claude_settings(settings_path, settings)
        click.echo("Removed pyafk hooks from Claude settings.")
    else:
        click.echo("No pyafk hooks found in Claude settings.")

    click.echo()

    # Ask about data
    click.echo("What would you like to do with pyafk data?")
    click.echo(f"  Data directory: {pyafk_dir}")

    # Check what data exists
    config = Config(pyafk_dir)
    db_path = config.db_path
    db_size = 0
    rules_count = 0

    if db_path.exists():
        db_size = db_path.stat().st_size

        async def _count_rules():
            from pyafk.core.rules import RulesEngine
            from pyafk.core.storage import Storage

            storage = Storage(db_path)
            await storage.connect()
            try:
                engine = RulesEngine(storage)
                rules = await engine.list_rules()
                return len(rules)
            finally:
                await storage.close()

        try:
            rules_count = asyncio.run(_count_rules())
        except Exception:
            pass

    if db_size > 0 or pyafk_dir.exists():
        click.echo()
        click.echo("Data summary:")
        if db_size > 0:
            click.echo(f"  - Database: {db_size / 1024:.1f} KB")
            click.echo(f"  - Rules: {rules_count}")
        click.echo()

    choice = click.prompt(
        "[K]eep / [D]elete / [E]xport first",
        type=click.Choice(["k", "d", "e", "K", "D", "E"], case_sensitive=False),
        default="k",
    )
    choice = choice.lower()

    if choice == "k":
        click.echo("Data kept. You can remove it later with 'rm -rf ~/.pyafk'")
    elif choice == "e":
        # Export data
        export_path = Path.home() / "pyafk_export.json"
        try:
            export_data = {"config": {}, "rules": []}
            if config._config_file.exists():
                export_data["config"] = json.loads(config._config_file.read_text())

            async def _export_rules():
                from pyafk.core.rules import RulesEngine
                from pyafk.core.storage import Storage

                storage = Storage(db_path)
                await storage.connect()
                try:
                    engine = RulesEngine(storage)
                    return await engine.list_rules()
                finally:
                    await storage.close()

            if db_path.exists():
                export_data["rules"] = asyncio.run(_export_rules())

            export_path.write_text(json.dumps(export_data, indent=2))
            click.echo(f"Data exported to: {export_path}")
            click.echo("Data kept in place. Delete manually if desired.")
        except Exception as e:
            click.echo(f"Export failed: {e}")
            click.echo("Data kept in place.")
    elif choice == "d":
        click.echo()
        click.echo("The following will be deleted:")
        if pyafk_dir.exists():
            for item in pyafk_dir.iterdir():
                click.echo(f"  - {item}")

        if click.confirm("Are you sure you want to delete all pyafk data?"):
            import shutil

            if pyafk_dir.exists():
                shutil.rmtree(pyafk_dir)
            click.echo("Data deleted.")
        else:
            click.echo("Data kept.")

    click.echo()
    click.echo("Uninstallation complete.")


if __name__ == "__main__":
    main()
