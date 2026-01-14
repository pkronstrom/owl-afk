"""Helper functions for CLI - database operations, telegram, config checks."""

import asyncio
from pathlib import Path

from owl.cli.ui import console
from owl.utils.config import Config, get_owl_dir


def config_exists():
    """Check if config exists (first run check)."""
    owl_dir = get_owl_dir()
    config_file = owl_dir / "config.json"
    return config_file.exists()


def get_rules(owl_dir: Path):
    """Get all rules from database."""
    from owl.core.rules import RulesEngine
    from owl.utils.storage_helpers import with_storage

    async def operation(storage):
        engine = RulesEngine(storage)
        return await engine.list_rules()

    return asyncio.run(with_storage(owl_dir, operation))


def add_rule(owl_dir: Path, pattern: str, action: str):
    """Add a rule to database."""
    from owl.core.rules import RulesEngine
    from owl.utils.storage_helpers import with_storage

    async def operation(storage):
        engine = RulesEngine(storage)
        return await engine.add_rule(pattern, action, 0, created_via="cli")

    return asyncio.run(with_storage(owl_dir, operation))


def remove_rule(owl_dir: Path, rule_id: int):
    """Remove a rule from database."""
    from owl.core.rules import RulesEngine
    from owl.utils.storage_helpers import with_storage

    async def operation(storage):
        engine = RulesEngine(storage)
        return await engine.remove_rule(rule_id)

    return asyncio.run(with_storage(owl_dir, operation))


def do_telegram_test(config: Config):
    """Send a test Telegram message."""

    async def _send():
        from owl.notifiers.telegram import TelegramNotifier

        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        return await notifier._api_request(
            "sendMessage",
            data={
                "chat_id": config.telegram_chat_id,
                "text": "owl test message - Telegram is configured correctly!",
            },
        )

    result = asyncio.run(_send())

    if result.get("ok"):
        console.print("[green]Test message sent![/green]")
    else:
        error = result.get("error", result.get("description", "Unknown error"))
        console.print(f"[red]Failed:[/red] {error}")
