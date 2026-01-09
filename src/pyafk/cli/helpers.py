"""Helper functions for CLI - database operations, telegram, config checks."""

import asyncio
from pathlib import Path

from pyafk.cli.ui import console
from pyafk.utils.config import Config, get_pyafk_dir


def config_exists():
    """Check if config exists (first run check)."""
    pyafk_dir = get_pyafk_dir()
    config_file = pyafk_dir / "config.json"
    return config_file.exists()


def get_rules(pyafk_dir: Path):
    """Get all rules from database."""
    from pyafk.core.rules import RulesEngine
    from pyafk.utils.storage_helpers import with_storage

    async def operation(storage):
        engine = RulesEngine(storage)
        return await engine.list_rules()

    return asyncio.run(with_storage(pyafk_dir, operation))


def add_rule(pyafk_dir: Path, pattern: str, action: str):
    """Add a rule to database."""
    from pyafk.core.rules import RulesEngine
    from pyafk.utils.storage_helpers import with_storage

    async def operation(storage):
        engine = RulesEngine(storage)
        return await engine.add_rule(pattern, action, 0, created_via="cli")

    return asyncio.run(with_storage(pyafk_dir, operation))


def remove_rule(pyafk_dir: Path, rule_id: int):
    """Remove a rule from database."""
    from pyafk.core.rules import RulesEngine
    from pyafk.utils.storage_helpers import with_storage

    async def operation(storage):
        engine = RulesEngine(storage)
        return await engine.remove_rule(rule_id)

    return asyncio.run(with_storage(pyafk_dir, operation))


def do_telegram_test(config: Config):
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
