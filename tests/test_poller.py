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
        # Create session first
        await storage.upsert_session(session_id="session-123", project_path="/test/project")

        request_id = await storage.create_request(
            session_id="session-123",
            tool_name="Bash",
            tool_input="{}",
        )

        notifier = MagicMock(spec=TelegramNotifier)
        # Return the callback on get_updates
        notifier.get_updates = AsyncMock(return_value=[
            {
                "update_id": 1,
                "callback_query": {
                    "id": "cb-1",
                    "data": f"approve:{request_id}",
                    "message": {"message_id": 123},
                },
            }
        ])
        notifier.answer_callback = AsyncMock()
        notifier.edit_message = AsyncMock()

        poller = Poller(storage, notifier, mock_pyafk_dir)
        # Set initial offset so first call processes updates instead of skipping
        poller._offset = 0

        await poller.process_updates_once()

        request = await storage.get_request(request_id)
        assert request.status == "approved"


@pytest.mark.asyncio
async def test_chain_rules_all_allow(mock_pyafk_dir):
    """Chain should auto-approve if all commands match allow rules."""
    from pyafk.core.storage import Storage
    from pyafk.core.rules import RulesEngine
    from pyafk.notifiers.telegram import TelegramNotifier

    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        # Add allow rules for each command in the chain
        engine = RulesEngine(storage)
        await engine.add_rule("Bash(cd *)", "approve")
        await engine.add_rule("Bash(npm test)", "approve")
        await engine.add_rule("Bash(git log)", "approve")

        notifier = MagicMock(spec=TelegramNotifier)
        poller = Poller(storage, notifier, mock_pyafk_dir)

        # Test the chain rule check
        result = await poller._check_chain_rules("cd ~/p && npm test && git log")
        assert result == "approve"


@pytest.mark.asyncio
async def test_chain_rules_any_deny(mock_pyafk_dir):
    """Chain should auto-deny if any command matches deny rule."""
    from pyafk.core.storage import Storage
    from pyafk.core.rules import RulesEngine
    from pyafk.notifiers.telegram import TelegramNotifier

    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        # Add allow rules for some commands and deny for one
        engine = RulesEngine(storage)
        await engine.add_rule("Bash(cd *)", "approve")
        await engine.add_rule("Bash(rm *)", "deny")

        notifier = MagicMock(spec=TelegramNotifier)
        poller = Poller(storage, notifier, mock_pyafk_dir)

        # Test the chain rule check
        result = await poller._check_chain_rules("cd ~/p && rm -rf /")
        assert result == "deny"


@pytest.mark.asyncio
async def test_chain_rules_manual_approval_needed(mock_pyafk_dir):
    """Chain should return None if some commands don't match any rule."""
    from pyafk.core.storage import Storage
    from pyafk.core.rules import RulesEngine
    from pyafk.notifiers.telegram import TelegramNotifier

    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        # Add allow rule for only one command
        engine = RulesEngine(storage)
        await engine.add_rule("Bash(cd *)", "approve")

        notifier = MagicMock(spec=TelegramNotifier)
        poller = Poller(storage, notifier, mock_pyafk_dir)

        # Test the chain rule check - npm test has no rule
        result = await poller._check_chain_rules("cd ~/p && npm test")
        assert result is None


@pytest.mark.asyncio
async def test_chain_rules_single_command(mock_pyafk_dir):
    """Single command should work with chain rule check."""
    from pyafk.core.storage import Storage
    from pyafk.core.rules import RulesEngine
    from pyafk.notifiers.telegram import TelegramNotifier

    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        # Add allow rule
        engine = RulesEngine(storage)
        await engine.add_rule("Bash(git status)", "approve")

        notifier = MagicMock(spec=TelegramNotifier)
        poller = Poller(storage, notifier, mock_pyafk_dir)

        # Test single command
        result = await poller._check_chain_rules("git status")
        assert result == "approve"


@pytest.mark.asyncio
async def test_chain_rules_with_quotes(mock_pyafk_dir):
    """Chain rules should handle commands with quotes correctly."""
    from pyafk.core.storage import Storage
    from pyafk.core.rules import RulesEngine
    from pyafk.notifiers.telegram import TelegramNotifier

    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        engine = RulesEngine(storage)
        await engine.add_rule('Bash(git commit -m *)', "approve")

        notifier = MagicMock(spec=TelegramNotifier)
        poller = Poller(storage, notifier, mock_pyafk_dir)

        # Should match the wildcard pattern
        result = await poller._check_chain_rules('git commit -m "fix bug"')
        assert result == "approve"


@pytest.mark.asyncio
async def test_chain_approval_integration(mock_pyafk_dir):
    """Integration test: chain approval should work through ApprovalManager."""
    from pyafk.core.manager import ApprovalManager
    from pyafk.core.rules import RulesEngine
    from pyafk.core.storage import Storage
    from pyafk.notifiers.telegram import TelegramNotifier
    import json

    # Set up with real storage
    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        # Add rules for chain commands
        engine = RulesEngine(storage)
        await engine.add_rule("Bash(cd *)", "approve")
        await engine.add_rule("Bash(git status)", "approve")

        # Create a mock TelegramNotifier
        notifier = MagicMock(spec=TelegramNotifier)
        notifier.send_approval_request = AsyncMock(return_value=None)

        # Create ApprovalManager with mocked notifier
        manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
        await manager.initialize()

        # Replace the notifier with our mock
        manager.notifier = notifier

        # Set up the poller with the storage
        from pyafk.core.poller import Poller
        manager.poller = Poller(storage, notifier, mock_pyafk_dir)

        # Request approval for a chained command
        tool_input = json.dumps({"command": "cd ~/p && git status"})
        result, denial_reason = await manager.request_approval(
            session_id="test-session",
            tool_name="Bash",
            tool_input=tool_input,
        )

        # Should auto-approve without sending to Telegram
        assert result == "approve"
        assert denial_reason is None
        # Should not have sent approval request to Telegram
        notifier.send_approval_request.assert_not_called()

        await manager.close()
