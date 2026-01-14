"""Tests for auto-approve rules engine."""

import pytest

from owl.core.rules import RulesEngine, matches_pattern


def test_matches_pattern_exact():
    """Exact tool name match."""
    assert matches_pattern("Read", "Read") is True
    assert matches_pattern("Read", "Write") is False


def test_matches_pattern_wildcard():
    """Wildcard patterns."""
    assert matches_pattern("Bash(git status)", "Bash(git *)") is True
    assert matches_pattern("Bash(rm -rf /)", "Bash(git *)") is False
    assert matches_pattern("Bash(anything)", "Bash(*)") is True


def test_matches_pattern_glob_path():
    """Path glob patterns."""
    assert matches_pattern("Read(/home/user/test.py)", "Read(*.py)") is True
    assert matches_pattern("Read(/home/user/test.js)", "Read(*.py)") is False


@pytest.mark.asyncio
async def test_rules_engine_no_rules(mock_owl_dir):
    """No rules means no auto-approve."""
    from owl.core.storage import Storage

    db_path = mock_owl_dir / "test.db"
    async with Storage(db_path) as storage:
        engine = RulesEngine(storage)

        result = await engine.check("Bash", '{"command": "ls"}')
        assert result is None  # No rule matched


@pytest.mark.asyncio
async def test_rules_engine_approve_rule(mock_owl_dir):
    """Matching approve rule."""
    from owl.core.storage import Storage

    db_path = mock_owl_dir / "test.db"
    async with Storage(db_path) as storage:
        await storage._conn.execute(
            "INSERT INTO auto_approve_rules (pattern, action, priority, created_at) VALUES (?, ?, ?, ?)",
            ("Bash(git *)", "approve", 0, 0),
        )
        await storage._conn.commit()

        engine = RulesEngine(storage)

        result = await engine.check("Bash", '{"command": "git status"}')
        assert result == "approve"


@pytest.mark.asyncio
async def test_rules_engine_deny_rule(mock_owl_dir):
    """Matching deny rule."""
    from owl.core.storage import Storage

    db_path = mock_owl_dir / "test.db"
    async with Storage(db_path) as storage:
        await storage._conn.execute(
            "INSERT INTO auto_approve_rules (pattern, action, priority, created_at) VALUES (?, ?, ?, ?)",
            ("Edit(*.prod.*)", "deny", 0, 0),
        )
        await storage._conn.commit()

        engine = RulesEngine(storage)

        result = await engine.check("Edit", '{"file_path": "/app/config.prod.json"}')
        assert result == "deny"


@pytest.mark.asyncio
async def test_rules_engine_priority(mock_owl_dir):
    """Higher priority rules win."""
    from owl.core.storage import Storage

    db_path = mock_owl_dir / "test.db"
    async with Storage(db_path) as storage:
        # Lower priority approve
        await storage._conn.execute(
            "INSERT INTO auto_approve_rules (pattern, action, priority, created_at) VALUES (?, ?, ?, ?)",
            ("Bash(*)", "approve", 0, 0),
        )
        # Higher priority deny
        await storage._conn.execute(
            "INSERT INTO auto_approve_rules (pattern, action, priority, created_at) VALUES (?, ?, ?, ?)",
            ("Bash(rm *)", "deny", 10, 0),
        )
        await storage._conn.commit()

        engine = RulesEngine(storage)

        # rm command should be denied (higher priority)
        result = await engine.check("Bash", '{"command": "rm -rf /"}')
        assert result == "deny"

        # ls command should be approved
        result = await engine.check("Bash", '{"command": "ls"}')
        assert result == "approve"
