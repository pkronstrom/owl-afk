"""Tests for storage request lookup."""

import pytest
from owl.core.storage import Storage


@pytest.fixture
async def storage(tmp_path):
    db_path = tmp_path / "test.db"
    s = Storage(db_path)
    await s.connect()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_get_latest_resolved_request(storage):
    """Should return the most recently resolved request for a session."""
    req1 = await storage.create_request("sess1", "Bash", '{"command": "ls"}')
    req2 = await storage.create_request("sess1", "Bash", '{"command": "pwd"}')
    await storage.set_telegram_msg_id(req1, 100)
    await storage.set_telegram_msg_id(req2, 200)
    await storage.resolve_request(req1, "approved", "telegram")
    await storage.resolve_request(req2, "approved", "telegram")

    result = await storage.get_latest_resolved_request("sess1")
    assert result is not None
    assert result.id == req2
    assert result.telegram_msg_id == 200


@pytest.mark.asyncio
async def test_get_latest_resolved_request_no_results(storage):
    """Should return None when no resolved requests exist."""
    result = await storage.get_latest_resolved_request("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_latest_resolved_request_ignores_pending(storage):
    """Should not return pending (unresolved) requests."""
    req1 = await storage.create_request("sess1", "Bash", '{"command": "ls"}')
    await storage.set_telegram_msg_id(req1, 100)
    # Don't resolve it
    result = await storage.get_latest_resolved_request("sess1")
    assert result is None
