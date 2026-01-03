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
    click.echo(f"Config dir: {pyafk_dir}")

    # Telegram status
    if config.telegram_bot_token and config.telegram_chat_id:
        click.echo("Telegram: configured")
    else:
        click.echo("Telegram: not configured")


@main.command("on")
@click.pass_context
def on_command(ctx):
    """Enable pyafk."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    config.set_mode("on")
    click.echo("pyafk enabled")


@main.command("off")
@click.pass_context
def off_command(ctx):
    """Disable pyafk."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    config.set_mode("off")
    click.echo("pyafk disabled")


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


if __name__ == "__main__":
    main()
