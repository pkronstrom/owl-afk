"""Storage helper utilities."""

from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from owl.core.storage import Storage
from owl.utils.config import Config

T = TypeVar("T")


async def with_storage(
    owl_dir: Path,
    operation: Callable[[Storage], Awaitable[T]],
) -> T:
    """Execute an async operation with a managed storage connection.

    This helper handles connection lifecycle, ensuring the storage is properly
    closed even if the operation raises an exception.

    Args:
        owl_dir: Path to owl config directory
        operation: Async function that takes a Storage instance

    Returns:
        Result of the operation

    Example:
        async def get_rules(storage):
            engine = RulesEngine(storage)
            return await engine.list_rules()

        rules = await with_storage(owl_dir, get_rules)
    """
    config = Config(owl_dir)
    storage = Storage(config.db_path)
    await storage.connect()
    try:
        return await operation(storage)
    finally:
        await storage.close()
