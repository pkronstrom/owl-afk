"""Tests for storage helper utilities."""

import pytest

from pyafk.utils.storage_helpers import with_storage


@pytest.mark.asyncio
async def test_with_storage_executes_operation(tmp_path):
    """Test that with_storage executes the operation and returns result."""
    from pyafk.core.storage import Storage

    async def operation(storage: Storage) -> str:
        return "test_result"

    result = await with_storage(tmp_path, operation)
    assert result == "test_result"


@pytest.mark.asyncio
async def test_with_storage_closes_connection(tmp_path):
    """Test that storage connection is closed after operation."""
    from pyafk.core.storage import Storage

    storage_ref = None

    async def operation(storage: Storage) -> None:
        nonlocal storage_ref
        storage_ref = storage
        return None

    await with_storage(tmp_path, operation)
    # Connection should be closed
    assert storage_ref._conn is None


@pytest.mark.asyncio
async def test_with_storage_closes_on_exception(tmp_path):
    """Test that storage is closed even if operation raises."""
    from pyafk.core.storage import Storage

    storage_ref = None

    async def failing_operation(storage: Storage) -> None:
        nonlocal storage_ref
        storage_ref = storage
        raise ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        await with_storage(tmp_path, failing_operation)

    # Connection should still be closed
    assert storage_ref._conn is None
