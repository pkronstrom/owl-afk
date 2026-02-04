"""Tests for auto-approve rules engine."""

import pytest

from owl.core.rules import (
    RulesEngine,
    format_tool_call,
    matches_pattern,
    normalize_command_for_matching,
)


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


def test_normalize_command_strips_quotes():
    """Quote normalization for consistent pattern matching."""
    # Single quotes
    assert normalize_command_for_matching("ssh host 'cmd arg'") == "ssh host cmd arg"
    # Double quotes
    assert normalize_command_for_matching('ssh host "cmd arg"') == "ssh host cmd arg"
    # Nested wrappers with quotes
    assert (
        normalize_command_for_matching("ssh aarni 'docker exec bouillon bash -c crontab'")
        == "ssh aarni docker exec bouillon bash -c crontab"
    )
    # No quotes - unchanged
    assert normalize_command_for_matching("git status") == "git status"


def test_normalize_command_preserves_apostrophes():
    """Apostrophes within words should be preserved (not treated as quotes)."""
    # Apostrophe in contraction
    assert normalize_command_for_matching("echo don't") == "echo don't"
    # Possessive
    assert normalize_command_for_matching("# Check a sell signal's score") == (
        "# Check a sell signal's score"
    )
    # Multiple apostrophes
    assert normalize_command_for_matching("echo it's John's file") == (
        "echo it's John's file"
    )
    # Apostrophe inside quotes should still be handled correctly
    assert normalize_command_for_matching("echo \"it's fine\"") == "echo it's fine"


def test_format_tool_call_normalizes_quotes():
    """format_tool_call strips quotes for consistent matching."""
    # Command with single quotes
    tool_input = '{"command": "ssh aarni \'docker exec bouillon bash\'"}'
    result = format_tool_call("Bash", tool_input)
    assert result == "Bash(ssh aarni docker exec bouillon bash)"
    assert "'" not in result  # No quotes in formatted output


@pytest.mark.asyncio
async def test_rules_engine_matches_quoted_commands(mock_owl_dir):
    """Rules match commands regardless of quoting style."""
    from owl.core.storage import Storage

    db_path = mock_owl_dir / "test.db"
    async with Storage(db_path) as storage:
        # Add rule without quotes (as pattern generator creates)
        await storage._conn.execute(
            "INSERT INTO auto_approve_rules (pattern, action, priority, created_at) VALUES (?, ?, ?, ?)",
            ("Bash(ssh aarni docker exec bouillon *)", "approve", 0, 0),
        )
        await storage._conn.commit()

        engine = RulesEngine(storage)

        # Command WITH quotes should still match
        result = await engine.check(
            "Bash", '{"command": "ssh aarni \'docker exec bouillon bash -c crontab\'"}'
        )
        assert result == "approve"
