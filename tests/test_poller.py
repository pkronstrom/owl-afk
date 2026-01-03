"""Tests for Telegram poller with locking."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pyafk.core.poller import Poller, PollLock


@pytest.mark.asyncio
async def test_poll_lock_acquire(mock_pyafk_dir):
    """PollLock should acquire and release."""
    lock = PollLock(mock_pyafk_dir / "poll.lock")

    acquired = await lock.acquire()
    assert acquired is True

    await lock.release()


@pytest.mark.asyncio
async def test_poll_lock_exclusive(mock_pyafk_dir):
    """Only one process can hold the lock."""
    lock1 = PollLock(mock_pyafk_dir / "poll.lock")
    lock2 = PollLock(mock_pyafk_dir / "poll.lock")

    acquired1 = await lock1.acquire()
    assert acquired1 is True

    acquired2 = await lock2.acquire(timeout=0.1)
    assert acquired2 is False

    await lock1.release()

    acquired2 = await lock2.acquire()
    assert acquired2 is True
    await lock2.release()


@pytest.mark.asyncio
async def test_poller_processes_callback(mock_pyafk_dir):
    """Poller should process callback queries."""
    from pyafk.core.storage import Storage
    from pyafk.notifiers.telegram import TelegramNotifier

    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        request_id = await storage.create_request(
            session_id="session-123",
            tool_name="Bash",
            tool_input="{}",
        )

        notifier = MagicMock(spec=TelegramNotifier)
        notifier.get_updates = AsyncMock(return_value=[
            {
                "update_id": 1,
                "callback_query": {
                    "id": "cb-1",
                    "data": f"approve:{request_id}",
                },
            }
        ])
        notifier.answer_callback = AsyncMock()
        notifier.edit_message = AsyncMock()

        poller = Poller(storage, notifier, mock_pyafk_dir)

        await poller.process_updates_once()

        request = await storage.get_request(request_id)
        assert request.status == "approved"
