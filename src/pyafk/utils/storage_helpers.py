"""Storage helper utilities."""

from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from pyafk.core.storage import Storage
from pyafk.utils.config import Config

T = TypeVar("T")


async def with_storage(
    pyafk_dir: Path,
    operation: Callable[[Storage], Awaitable[T]],
) -> T:
    """Execute an async operation with a managed storage connection.

    This helper handles connection lifecycle, ensuring the storage is properly
    closed even if the operation raises an exception.

    Args:
        pyafk_dir: Path to pyafk config directory
        operation: Async function that takes a Storage instance

    Returns:
        Result of the operation

    Example:
        async def get_rules(storage):
            engine = RulesEngine(storage)
            return await engine.list_rules()

        rules = await with_storage(pyafk_dir, get_rules)
    """
    config = Config(pyafk_dir)
    storage = Storage(config.db_path)
    await storage.connect()
    try:
        return await operation(storage)
    finally:
        await storage.close()
