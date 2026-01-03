# pyafk Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python remote approval system for Claude Code with SQLite-backed state, Telegram notifications, and modular architecture.

**Architecture:** Hook-based system where Claude Code hooks call pyafk CLI, which uses SQLite WAL for concurrent state and a single-poller lock pattern for Telegram. Fast path exits in ~2ms when disabled.

**Tech Stack:** Python 3.10+, aiosqlite, httpx, click (CLI), pytest

---

## Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `src/pyafk/__init__.py`
- Create: `src/pyafk/__main__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pyafk"
version = "0.1.0"
description = "Remote approval system for Claude Code via Telegram"
readme = "README.md"
requires-python = ">=3.10"
license = "MIT"
authors = [{ name = "bembu" }]
dependencies = [
    "aiosqlite>=0.19.0",
    "httpx>=0.25.0",
    "click>=8.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
]

[project.scripts]
pyafk = "pyafk.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/pyafk"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 2: Create directory structure**

```bash
mkdir -p src/pyafk tests
```

**Step 3: Create src/pyafk/__init__.py**

```python
"""pyafk - Remote approval system for Claude Code."""

__version__ = "0.1.0"
```

**Step 4: Create src/pyafk/__main__.py**

```python
"""Allow running as python -m pyafk."""

from pyafk.cli import main

if __name__ == "__main__":
    main()
```

**Step 5: Create tests/__init__.py**

```python
"""pyafk tests."""
```

**Step 6: Create tests/conftest.py**

```python
"""Shared pytest fixtures."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def mock_pyafk_dir(temp_dir, monkeypatch):
    """Set up a mock ~/.pyafk directory."""
    pyafk_dir = temp_dir / ".pyafk"
    pyafk_dir.mkdir()
    monkeypatch.setenv("PYAFK_DIR", str(pyafk_dir))
    return pyafk_dir
```

**Step 7: Create minimal CLI placeholder**

Create `src/pyafk/cli.py`:

```python
"""CLI entry point."""

import click


@click.group()
def main():
    """pyafk - Remote approval system for Claude Code."""
    pass


@main.command()
def status():
    """Show current status."""
    click.echo("pyafk is not configured yet")


if __name__ == "__main__":
    main()
```

**Step 8: Verify setup**

```bash
pip install -e ".[dev]"
pyafk status
pytest --collect-only
```

Expected: CLI prints "pyafk is not configured yet", pytest finds conftest.py

**Step 9: Commit**

```bash
git add -A
git commit -m "feat: initial project setup with pyproject.toml and CLI skeleton"
```

---

## Task 2: Configuration Module

**Files:**
- Create: `src/pyafk/utils/__init__.py`
- Create: `src/pyafk/utils/config.py`
- Create: `tests/test_config.py`

**Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
"""Tests for configuration module."""

import json
from pathlib import Path

import pytest

from pyafk.utils.config import Config


def test_config_default_values(mock_pyafk_dir):
    """Config should have sensible defaults."""
    config = Config(mock_pyafk_dir)

    assert config.timeout_seconds == 3600
    assert config.timeout_action == "deny"
    assert config.telegram_bot_token is None
    assert config.telegram_chat_id is None


def test_config_loads_from_file(mock_pyafk_dir):
    """Config should load values from config.json."""
    config_file = mock_pyafk_dir / "config.json"
    config_file.write_text(json.dumps({
        "telegram_bot_token": "test-token",
        "telegram_chat_id": "12345",
        "timeout_seconds": 1800,
    }))

    config = Config(mock_pyafk_dir)

    assert config.telegram_bot_token == "test-token"
    assert config.telegram_chat_id == "12345"
    assert config.timeout_seconds == 1800


def test_config_save(mock_pyafk_dir):
    """Config should save changes to file."""
    config = Config(mock_pyafk_dir)
    config.telegram_bot_token = "new-token"
    config.save()

    config_file = mock_pyafk_dir / "config.json"
    data = json.loads(config_file.read_text())
    assert data["telegram_bot_token"] == "new-token"


def test_config_get_pyafk_dir_from_env(temp_dir, monkeypatch):
    """Config should use PYAFK_DIR env var if set."""
    custom_dir = temp_dir / "custom"
    custom_dir.mkdir()
    monkeypatch.setenv("PYAFK_DIR", str(custom_dir))

    from pyafk.utils.config import get_pyafk_dir
    assert get_pyafk_dir() == custom_dir


def test_config_default_pyafk_dir(monkeypatch):
    """Config should default to ~/.pyafk."""
    monkeypatch.delenv("PYAFK_DIR", raising=False)

    from pyafk.utils.config import get_pyafk_dir
    assert get_pyafk_dir() == Path.home() / ".pyafk"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'pyafk.utils'"

**Step 3: Create utils/__init__.py**

```python
"""Utility modules."""
```

**Step 4: Write implementation**

Create `src/pyafk/utils/config.py`:

```python
"""Configuration management."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def get_pyafk_dir() -> Path:
    """Get the pyafk data directory."""
    if env_dir := os.environ.get("PYAFK_DIR"):
        return Path(env_dir)
    return Path.home() / ".pyafk"


@dataclass
class Config:
    """Application configuration."""

    pyafk_dir: Path
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    timeout_seconds: int = 3600
    timeout_action: str = "deny"  # deny, approve, wait

    def __init__(self, pyafk_dir: Optional[Path] = None):
        """Load config from directory."""
        self.pyafk_dir = pyafk_dir or get_pyafk_dir()
        self._config_file = self.pyafk_dir / "config.json"
        self._load()

    def _load(self):
        """Load config from file."""
        # Set defaults
        self.telegram_bot_token = None
        self.telegram_chat_id = None
        self.timeout_seconds = 3600
        self.timeout_action = "deny"

        if self._config_file.exists():
            try:
                data = json.loads(self._config_file.read_text())
                self.telegram_bot_token = data.get("telegram_bot_token")
                self.telegram_chat_id = data.get("telegram_chat_id")
                self.timeout_seconds = data.get("timeout_seconds", 3600)
                self.timeout_action = data.get("timeout_action", "deny")
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        """Save config to file."""
        self.pyafk_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "telegram_bot_token": self.telegram_bot_token,
            "telegram_chat_id": self.telegram_chat_id,
            "timeout_seconds": self.timeout_seconds,
            "timeout_action": self.timeout_action,
        }
        self._config_file.write_text(json.dumps(data, indent=2))

    @property
    def db_path(self) -> Path:
        """Path to SQLite database."""
        return self.pyafk_dir / "pyafk.db"

    @property
    def mode_file(self) -> Path:
        """Path to mode file."""
        return self.pyafk_dir / "mode"

    def get_mode(self) -> str:
        """Get current mode (on/off)."""
        try:
            return self.mode_file.read_text().strip()
        except FileNotFoundError:
            return "off"

    def set_mode(self, mode: str):
        """Set current mode."""
        self.pyafk_dir.mkdir(parents=True, exist_ok=True)
        self.mode_file.write_text(mode)
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_config.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add configuration module with file persistence"
```

---

## Task 3: Storage Layer (SQLite)

**Files:**
- Create: `src/pyafk/core/__init__.py`
- Create: `src/pyafk/core/storage.py`
- Create: `tests/test_storage.py`

**Step 1: Write the failing test**

Create `tests/test_storage.py`:

```python
"""Tests for SQLite storage layer."""

import pytest

from pyafk.core.storage import Storage, Request, Session, AuditEntry


@pytest.mark.asyncio
async def test_storage_creates_tables(mock_pyafk_dir):
    """Storage should create tables on init."""
    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        # Tables should exist
        tables = await storage.list_tables()
        assert "requests" in tables
        assert "sessions" in tables
        assert "auto_approve_rules" in tables
        assert "audit_log" in tables


@pytest.mark.asyncio
async def test_storage_create_request(mock_pyafk_dir):
    """Storage should create and retrieve requests."""
    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        request_id = await storage.create_request(
            session_id="session-123",
            tool_name="Bash",
            tool_input='{"command": "ls"}',
            context="User wants to list files",
            description="List directory contents",
        )

        request = await storage.get_request(request_id)
        assert request.session_id == "session-123"
        assert request.tool_name == "Bash"
        assert request.status == "pending"


@pytest.mark.asyncio
async def test_storage_resolve_request(mock_pyafk_dir):
    """Storage should update request status."""
    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        request_id = await storage.create_request(
            session_id="session-123",
            tool_name="Bash",
            tool_input="{}",
        )

        await storage.resolve_request(request_id, "approved", "user")

        request = await storage.get_request(request_id)
        assert request.status == "approved"
        assert request.resolved_by == "user"


@pytest.mark.asyncio
async def test_storage_pending_requests(mock_pyafk_dir):
    """Storage should list pending requests."""
    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        await storage.create_request(session_id="s1", tool_name="Bash", tool_input="{}")
        await storage.create_request(session_id="s2", tool_name="Edit", tool_input="{}")

        pending = await storage.get_pending_requests()
        assert len(pending) == 2


@pytest.mark.asyncio
async def test_storage_sessions(mock_pyafk_dir):
    """Storage should track sessions."""
    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        await storage.upsert_session(
            session_id="session-123",
            project_path="/home/user/project",
        )

        session = await storage.get_session("session-123")
        assert session.project_path == "/home/user/project"
        assert session.status == "active"


@pytest.mark.asyncio
async def test_storage_audit_log(mock_pyafk_dir):
    """Storage should append to audit log."""
    db_path = mock_pyafk_dir / "test.db"

    async with Storage(db_path) as storage:
        await storage.log_audit(
            event_type="request",
            session_id="session-123",
            details={"tool": "Bash"},
        )

        entries = await storage.get_audit_log(limit=10)
        assert len(entries) == 1
        assert entries[0].event_type == "request"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_storage.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'pyafk.core'"

**Step 3: Create core/__init__.py**

```python
"""Core modules."""
```

**Step 4: Write implementation**

Create `src/pyafk/core/storage.py`:

```python
"""SQLite storage layer with WAL mode."""

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiosqlite


@dataclass
class Request:
    """Approval request."""
    id: str
    session_id: str
    tool_name: str
    tool_input: Optional[str]
    context: Optional[str]
    description: Optional[str]
    status: str
    telegram_msg_id: Optional[int]
    created_at: float
    resolved_at: Optional[float]
    resolved_by: Optional[str]


@dataclass
class Session:
    """Claude Code session."""
    session_id: str
    project_path: Optional[str]
    started_at: float
    last_seen_at: float
    status: str


@dataclass
class AuditEntry:
    """Audit log entry."""
    id: int
    timestamp: float
    event_type: str
    session_id: Optional[str]
    details: dict


SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_input      TEXT,
    context         TEXT,
    description     TEXT,
    status          TEXT DEFAULT 'pending',
    telegram_msg_id INTEGER,
    created_at      REAL,
    resolved_at     REAL,
    resolved_by     TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    project_path    TEXT,
    started_at      REAL,
    last_seen_at    REAL,
    status          TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS auto_approve_rules (
    id              INTEGER PRIMARY KEY,
    pattern         TEXT NOT NULL,
    action          TEXT DEFAULT 'approve',
    priority        INTEGER DEFAULT 0,
    created_via     TEXT,
    created_at      REAL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY,
    timestamp       REAL,
    event_type      TEXT,
    session_id      TEXT,
    details         TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
CREATE INDEX IF NOT EXISTS idx_requests_session ON requests(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
"""


class Storage:
    """Async SQLite storage with WAL mode."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self):
        """Open database connection."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row

        # Enable WAL mode for concurrent access
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")

        # Create tables
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def list_tables(self) -> list[str]:
        """List all tables (for testing)."""
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        return [row["name"] for row in rows]

    # Requests

    async def create_request(
        self,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        """Create a new approval request."""
        request_id = str(uuid.uuid4())
        now = time.time()

        await self._conn.execute(
            """
            INSERT INTO requests (id, session_id, tool_name, tool_input, context, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (request_id, session_id, tool_name, tool_input, context, description, now),
        )
        await self._conn.commit()
        return request_id

    async def get_request(self, request_id: str) -> Optional[Request]:
        """Get a request by ID."""
        cursor = await self._conn.execute(
            "SELECT * FROM requests WHERE id = ?", (request_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return Request(**dict(row))

    async def resolve_request(
        self,
        request_id: str,
        status: str,
        resolved_by: str,
    ):
        """Update request status."""
        now = time.time()
        await self._conn.execute(
            """
            UPDATE requests SET status = ?, resolved_at = ?, resolved_by = ?
            WHERE id = ?
            """,
            (status, now, resolved_by, request_id),
        )
        await self._conn.commit()

    async def get_pending_requests(self) -> list[Request]:
        """Get all pending requests."""
        cursor = await self._conn.execute(
            "SELECT * FROM requests WHERE status = 'pending' ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [Request(**dict(row)) for row in rows]

    async def set_telegram_msg_id(self, request_id: str, msg_id: int):
        """Set the Telegram message ID for a request."""
        await self._conn.execute(
            "UPDATE requests SET telegram_msg_id = ? WHERE id = ?",
            (msg_id, request_id),
        )
        await self._conn.commit()

    # Sessions

    async def upsert_session(
        self,
        session_id: str,
        project_path: Optional[str] = None,
    ):
        """Create or update a session."""
        now = time.time()
        await self._conn.execute(
            """
            INSERT INTO sessions (session_id, project_path, started_at, last_seen_at, status)
            VALUES (?, ?, ?, ?, 'active')
            ON CONFLICT(session_id) DO UPDATE SET
                last_seen_at = ?,
                project_path = COALESCE(?, project_path)
            """,
            (session_id, project_path, now, now, now, project_path),
        )
        await self._conn.commit()

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        cursor = await self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return Session(**dict(row))

    async def get_active_sessions(self) -> list[Session]:
        """Get all active sessions."""
        cursor = await self._conn.execute(
            "SELECT * FROM sessions WHERE status = 'active' ORDER BY last_seen_at DESC"
        )
        rows = await cursor.fetchall()
        return [Session(**dict(row)) for row in rows]

    # Audit log

    async def log_audit(
        self,
        event_type: str,
        session_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Append to audit log."""
        now = time.time()
        details_json = json.dumps(details) if details else None
        await self._conn.execute(
            """
            INSERT INTO audit_log (timestamp, event_type, session_id, details)
            VALUES (?, ?, ?, ?)
            """,
            (now, event_type, session_id, details_json),
        )
        await self._conn.commit()

    async def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        """Get recent audit log entries."""
        cursor = await self._conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        entries = []
        for row in rows:
            d = dict(row)
            d["details"] = json.loads(d["details"]) if d["details"] else {}
            entries.append(AuditEntry(**d))
        return entries
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_storage.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add SQLite storage layer with WAL mode"
```

---

## Task 4: Rules Engine

**Files:**
- Create: `src/pyafk/core/rules.py`
- Create: `tests/test_rules.py`

**Step 1: Write the failing test**

Create `tests/test_rules.py`:

```python
"""Tests for auto-approve rules engine."""

import pytest

from pyafk.core.rules import RulesEngine, matches_pattern


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
async def test_rules_engine_no_rules(mock_pyafk_dir):
    """No rules means no auto-approve."""
    from pyafk.core.storage import Storage

    db_path = mock_pyafk_dir / "test.db"
    async with Storage(db_path) as storage:
        engine = RulesEngine(storage)

        result = await engine.check("Bash", '{"command": "ls"}')
        assert result is None  # No rule matched


@pytest.mark.asyncio
async def test_rules_engine_approve_rule(mock_pyafk_dir):
    """Matching approve rule."""
    from pyafk.core.storage import Storage

    db_path = mock_pyafk_dir / "test.db"
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
async def test_rules_engine_deny_rule(mock_pyafk_dir):
    """Matching deny rule."""
    from pyafk.core.storage import Storage

    db_path = mock_pyafk_dir / "test.db"
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
async def test_rules_engine_priority(mock_pyafk_dir):
    """Higher priority rules win."""
    from pyafk.core.storage import Storage

    db_path = mock_pyafk_dir / "test.db"
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
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_rules.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'pyafk.core.rules'"

**Step 3: Write implementation**

Create `src/pyafk/core/rules.py`:

```python
"""Auto-approve rules engine."""

import fnmatch
import json
import re
from typing import Optional

from pyafk.core.storage import Storage


def matches_pattern(tool_call: str, pattern: str) -> bool:
    """Check if a tool call matches a pattern.

    Patterns can be:
    - Exact: "Read" matches "Read"
    - Wildcard: "Bash(git *)" matches "Bash(git status)"
    - Glob: "Read(*.py)" matches "Read(/path/to/file.py)"
    """
    # Convert pattern to regex
    # Escape special regex chars except * and ?
    regex_pattern = ""
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            regex_pattern += ".*"
        elif c == "?":
            regex_pattern += "."
        elif c in ".^$+{}[]|()":
            regex_pattern += "\\" + c
        else:
            regex_pattern += c
        i += 1

    regex_pattern = "^" + regex_pattern + "$"
    return bool(re.match(regex_pattern, tool_call, re.IGNORECASE))


def format_tool_call(tool_name: str, tool_input: Optional[str]) -> str:
    """Format tool name and input for pattern matching.

    Examples:
    - ("Bash", '{"command": "git status"}') -> "Bash(git status)"
    - ("Read", '{"file_path": "/foo/bar.py"}') -> "Read(/foo/bar.py)"
    - ("Edit", '{"file_path": "/x.py", "old": "a"}') -> "Edit(/x.py)"
    """
    if not tool_input:
        return tool_name

    try:
        data = json.loads(tool_input)
    except (json.JSONDecodeError, TypeError):
        return tool_name

    # Extract the most relevant field for matching
    if "command" in data:
        return f"{tool_name}({data['command']})"
    elif "file_path" in data:
        return f"{tool_name}({data['file_path']})"
    elif "path" in data:
        return f"{tool_name}({data['path']})"
    elif "url" in data:
        return f"{tool_name}({data['url']})"

    return tool_name


class RulesEngine:
    """Evaluate auto-approve rules against tool calls."""

    def __init__(self, storage: Storage):
        self.storage = storage
        self._rules_cache: Optional[list] = None

    async def check(self, tool_name: str, tool_input: Optional[str] = None) -> Optional[str]:
        """Check if a tool call matches any rule.

        Returns:
            "approve", "deny", or None if no rule matches
        """
        tool_call = format_tool_call(tool_name, tool_input)

        # Load rules (sorted by priority descending)
        cursor = await self.storage._conn.execute(
            "SELECT pattern, action FROM auto_approve_rules ORDER BY priority DESC"
        )
        rules = await cursor.fetchall()

        for row in rules:
            if matches_pattern(tool_call, row["pattern"]):
                return row["action"]

        return None

    async def add_rule(
        self,
        pattern: str,
        action: str = "approve",
        priority: int = 0,
        created_via: str = "cli",
    ) -> int:
        """Add a new rule."""
        import time
        cursor = await self.storage._conn.execute(
            """
            INSERT INTO auto_approve_rules (pattern, action, priority, created_via, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (pattern, action, priority, created_via, time.time()),
        )
        await self.storage._conn.commit()
        return cursor.lastrowid

    async def remove_rule(self, rule_id: int) -> bool:
        """Remove a rule by ID."""
        cursor = await self.storage._conn.execute(
            "DELETE FROM auto_approve_rules WHERE id = ?", (rule_id,)
        )
        await self.storage._conn.commit()
        return cursor.rowcount > 0

    async def list_rules(self) -> list[dict]:
        """List all rules."""
        cursor = await self.storage._conn.execute(
            "SELECT * FROM auto_approve_rules ORDER BY priority DESC, id"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_rules.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add auto-approve rules engine with pattern matching"
```

---

## Task 5: Notifier Interface + Console Notifier

**Files:**
- Create: `src/pyafk/notifiers/__init__.py`
- Create: `src/pyafk/notifiers/base.py`
- Create: `src/pyafk/notifiers/console.py`
- Create: `tests/test_notifiers.py`

**Step 1: Write the failing test**

Create `tests/test_notifiers.py`:

```python
"""Tests for notifier interface."""

import pytest

from pyafk.notifiers.base import Notifier
from pyafk.notifiers.console import ConsoleNotifier


def test_console_notifier_is_notifier():
    """ConsoleNotifier should implement Notifier."""
    notifier = ConsoleNotifier()
    assert isinstance(notifier, Notifier)


@pytest.mark.asyncio
async def test_console_notifier_send(capsys):
    """ConsoleNotifier should print to stdout."""
    notifier = ConsoleNotifier()

    msg_id = await notifier.send_approval_request(
        request_id="req-123",
        session_id="session-456",
        tool_name="Bash",
        tool_input='{"command": "ls"}',
        context="List files",
        description="Running ls command",
    )

    captured = capsys.readouterr()
    assert "Bash" in captured.out
    assert "req-123" in captured.out
    assert msg_id is not None


@pytest.mark.asyncio
async def test_console_notifier_auto_approve():
    """ConsoleNotifier in auto mode should return approve."""
    notifier = ConsoleNotifier(auto_response="approve")

    # This should return immediately without waiting
    response = await notifier.wait_for_response("req-123", timeout=1)
    assert response == "approve"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_notifiers.py -v
```

Expected: FAIL with "ModuleNotFoundError"

**Step 3: Create notifiers/__init__.py**

```python
"""Notification adapters."""

from pyafk.notifiers.base import Notifier
from pyafk.notifiers.console import ConsoleNotifier

__all__ = ["Notifier", "ConsoleNotifier"]
```

**Step 4: Create base.py**

Create `src/pyafk/notifiers/base.py`:

```python
"""Base notifier interface."""

from abc import ABC, abstractmethod
from typing import Optional


class Notifier(ABC):
    """Abstract base class for notification adapters."""

    @abstractmethod
    async def send_approval_request(
        self,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[int]:
        """Send an approval request notification.

        Returns:
            Message ID if applicable (e.g., Telegram message ID)
        """
        pass

    @abstractmethod
    async def wait_for_response(
        self,
        request_id: str,
        timeout: int,
    ) -> Optional[str]:
        """Wait for user response.

        Returns:
            "approve", "deny", or None if timeout
        """
        pass

    async def send_status_update(
        self,
        session_id: str,
        status: str,
        details: Optional[dict] = None,
    ):
        """Send a status update (optional)."""
        pass

    async def edit_message(
        self,
        message_id: int,
        new_text: str,
    ):
        """Edit a previously sent message (optional)."""
        pass
```

**Step 5: Create console.py**

Create `src/pyafk/notifiers/console.py`:

```python
"""Console notifier for testing and local use."""

import asyncio
from typing import Optional

from pyafk.notifiers.base import Notifier


class ConsoleNotifier(Notifier):
    """Simple console-based notifier for testing."""

    def __init__(self, auto_response: Optional[str] = None):
        """Initialize console notifier.

        Args:
            auto_response: If set, automatically return this response
                          ("approve" or "deny") without waiting.
        """
        self.auto_response = auto_response
        self._message_counter = 0

    async def send_approval_request(
        self,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[int]:
        """Print approval request to console."""
        self._message_counter += 1

        print("\n" + "=" * 50)
        print(f"APPROVAL REQUEST [{request_id}]")
        print("=" * 50)
        print(f"Session: {session_id}")
        print(f"Tool: {tool_name}")
        if description:
            print(f"Description: {description}")
        if tool_input:
            print(f"Input: {tool_input[:200]}...")
        if context:
            print(f"Context: {context}")
        print("=" * 50 + "\n")

        return self._message_counter

    async def wait_for_response(
        self,
        request_id: str,
        timeout: int,
    ) -> Optional[str]:
        """Wait for response (or return auto_response)."""
        if self.auto_response:
            return self.auto_response

        # In real console mode, we could read from stdin
        # For now, just timeout
        await asyncio.sleep(timeout)
        return None

    async def send_status_update(
        self,
        session_id: str,
        status: str,
        details: Optional[dict] = None,
    ):
        """Print status update."""
        print(f"[STATUS] Session {session_id}: {status}")
        if details:
            print(f"  Details: {details}")
```

**Step 6: Run test to verify it passes**

```bash
pytest tests/test_notifiers.py -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add -A
git commit -m "feat: add notifier interface and console implementation"
```

---

## Task 6: Telegram Notifier

**Files:**
- Create: `src/pyafk/notifiers/telegram.py`
- Create: `tests/test_telegram.py`

**Step 1: Write the failing test**

Create `tests/test_telegram.py`:

```python
"""Tests for Telegram notifier."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from pyafk.notifiers.telegram import TelegramNotifier, format_approval_message


def test_format_approval_message():
    """Format message for Telegram."""
    msg = format_approval_message(
        request_id="req-123",
        session_id="session-456",
        tool_name="Bash",
        tool_input='{"command": "git status"}',
        description="Check git status",
        context="User wants to see changes",
        timeout=3600,
        timeout_action="deny",
    )

    assert "Bash" in msg
    assert "git status" in msg
    assert "session-456" in msg
    assert "60m" in msg  # timeout formatted


def test_format_approval_message_truncates_long_input():
    """Long tool input should be truncated."""
    long_input = json.dumps({"command": "x" * 1000})
    msg = format_approval_message(
        request_id="req-123",
        session_id="s",
        tool_name="Bash",
        tool_input=long_input,
    )

    assert len(msg) < 2000  # Telegram limit is 4096, we should be well under


@pytest.mark.asyncio
async def test_telegram_notifier_send():
    """TelegramNotifier should send via API."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        msg_id = await notifier.send_approval_request(
            request_id="req-123",
            session_id="session-456",
            tool_name="Bash",
            tool_input='{"command": "ls"}',
        )

        assert msg_id == 42
        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert "sendMessage" in call_args[0][0]


@pytest.mark.asyncio
async def test_telegram_notifier_inline_keyboard():
    """Should include inline keyboard with buttons."""
    notifier = TelegramNotifier(
        bot_token="test-token",
        chat_id="12345",
    )

    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        await notifier.send_approval_request(
            request_id="req-123",
            session_id="session-456",
            tool_name="Bash",
            tool_input="{}",
        )

        call_kwargs = mock_api.call_args[1]
        data = call_kwargs.get("data", {})

        # Should have reply_markup with inline keyboard
        assert "reply_markup" in data
        markup = json.loads(data["reply_markup"])
        assert "inline_keyboard" in markup
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_telegram.py -v
```

Expected: FAIL

**Step 3: Write implementation**

Create `src/pyafk/notifiers/telegram.py`:

```python
"""Telegram notifier using Bot API."""

import json
from typing import Optional

import httpx

from pyafk.notifiers.base import Notifier


def format_approval_message(
    request_id: str,
    session_id: str,
    tool_name: str,
    tool_input: Optional[str] = None,
    description: Optional[str] = None,
    context: Optional[str] = None,
    timeout: int = 3600,
    timeout_action: str = "deny",
) -> str:
    """Format a tool request for Telegram display."""
    # Format timeout
    if timeout >= 3600:
        timeout_str = f"{timeout // 3600}h"
    else:
        timeout_str = f"{timeout // 60}m"

    # Parse and format tool input
    input_display = ""
    if tool_input:
        try:
            data = json.loads(tool_input)
            if "command" in data:
                cmd = data["command"]
                if len(cmd) > 500:
                    cmd = cmd[:500] + "..."
                input_display = f"\n<b>Command:</b>\n<code>{_escape_html(cmd)}</code>"
            elif "file_path" in data:
                input_display = f"\n<b>File:</b> <code>{_escape_html(data['file_path'])}</code>"
            else:
                input_str = json.dumps(data, indent=2)
                if len(input_str) > 500:
                    input_str = input_str[:500] + "..."
                input_display = f"\n<b>Input:</b>\n<code>{_escape_html(input_str)}</code>"
        except (json.JSONDecodeError, TypeError):
            if len(tool_input) > 500:
                tool_input = tool_input[:500] + "..."
            input_display = f"\n<b>Input:</b> <code>{_escape_html(tool_input)}</code>"

    # Build message
    lines = [
        f"🔧 <b>Tool Request</b> [<code>{session_id[:8]}</code>]",
        "",
        f"<b>Tool:</b> {_escape_html(tool_name)}",
    ]

    if description:
        lines.append(f"<b>Description:</b> {_escape_html(description)}")

    lines.append(input_display)

    if context:
        lines.append(f"\n<b>Context:</b> {_escape_html(context)}")

    lines.extend([
        "",
        "━" * 20,
        f"⏱ Timeout: {timeout_str} ({timeout_action})",
    ])

    return "\n".join(lines)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class TelegramNotifier(Notifier):
    """Telegram Bot API notifier."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout: int = 3600,
        timeout_action: str = "deny",
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self.timeout_action = timeout_action
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    async def _api_request(
        self,
        method: str,
        data: Optional[dict] = None,
    ) -> dict:
        """Make a Telegram API request."""
        url = f"{self._base_url}/{method}"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=30)
            return response.json()

    async def send_approval_request(
        self,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[int]:
        """Send approval request to Telegram."""
        message = format_approval_message(
            request_id=request_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            description=description,
            context=context,
            timeout=self.timeout,
            timeout_action=self.timeout_action,
        )

        # Inline keyboard with buttons
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"approve:{request_id}"},
                    {"text": "❌ Deny", "callback_data": f"deny:{request_id}"},
                ],
                [
                    {"text": "⏭ Approve All", "callback_data": f"approve_all:{session_id}"},
                    {"text": "📝 Add Rule", "callback_data": f"add_rule:{request_id}"},
                ],
            ]
        }

        result = await self._api_request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            },
        )

        if result.get("ok"):
            return result["result"]["message_id"]
        return None

    async def wait_for_response(
        self,
        request_id: str,
        timeout: int,
    ) -> Optional[str]:
        """Wait for callback response from Telegram.

        Note: This is handled by the poller, not here.
        The poller writes responses to SQLite, and the manager reads them.
        """
        # This method exists for interface compliance
        # Real waiting is done via SQLite polling in the manager
        return None

    async def edit_message(
        self,
        message_id: int,
        new_text: str,
    ):
        """Edit a sent message."""
        await self._api_request(
            "editMessageText",
            data={
                "chat_id": self.chat_id,
                "message_id": message_id,
                "text": new_text,
                "parse_mode": "HTML",
            },
        )

    async def answer_callback(self, callback_id: str, text: str = ""):
        """Answer a callback query."""
        await self._api_request(
            "answerCallbackQuery",
            data={
                "callback_query_id": callback_id,
                "text": text,
            },
        )

    async def get_updates(self, offset: Optional[int] = None, timeout: int = 30) -> list:
        """Get updates (for polling)."""
        data = {"timeout": timeout}
        if offset is not None:
            data["offset"] = offset

        result = await self._api_request("getUpdates", data=data)
        if result.get("ok"):
            return result.get("result", [])
        return []
```

**Step 4: Update notifiers/__init__.py**

```python
"""Notification adapters."""

from pyafk.notifiers.base import Notifier
from pyafk.notifiers.console import ConsoleNotifier
from pyafk.notifiers.telegram import TelegramNotifier

__all__ = ["Notifier", "ConsoleNotifier", "TelegramNotifier"]
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_telegram.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add Telegram notifier with inline keyboard buttons"
```

---

## Task 7: Poller with Lock

**Files:**
- Create: `src/pyafk/core/poller.py`
- Create: `tests/test_poller.py`

**Step 1: Write the failing test**

Create `tests/test_poller.py`:

```python
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

    # Second lock should fail
    acquired2 = await lock2.acquire(timeout=0.1)
    assert acquired2 is False

    await lock1.release()

    # Now second lock should succeed
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
        # Create a pending request
        request_id = await storage.create_request(
            session_id="session-123",
            tool_name="Bash",
            tool_input="{}",
        )

        # Mock Telegram notifier
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

        # Process one update
        await poller.process_updates_once()

        # Request should be approved
        request = await storage.get_request(request_id)
        assert request.status == "approved"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_poller.py -v
```

Expected: FAIL

**Step 3: Write implementation**

Create `src/pyafk/core/poller.py`:

```python
"""Telegram poller with file-based locking."""

import asyncio
import fcntl
import os
from pathlib import Path
from typing import Optional

from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier


class PollLock:
    """File-based lock for single poller."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fd: Optional[int] = None

    async def acquire(self, timeout: float = 5.0) -> bool:
        """Try to acquire the lock.

        Returns True if acquired, False if timeout.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        start = asyncio.get_event_loop().time()
        while True:
            try:
                self._fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_RDWR,
                )
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Write PID to lock file
                os.ftruncate(self._fd, 0)
                os.write(self._fd, str(os.getpid()).encode())
                return True
            except (BlockingIOError, OSError):
                if self._fd is not None:
                    os.close(self._fd)
                    self._fd = None

                elapsed = asyncio.get_event_loop().time() - start
                if elapsed >= timeout:
                    return False

                await asyncio.sleep(0.1)

    async def release(self):
        """Release the lock."""
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

            # Remove lock file
            try:
                self.lock_path.unlink()
            except OSError:
                pass


class Poller:
    """Poll Telegram for callback responses."""

    def __init__(
        self,
        storage: Storage,
        notifier: TelegramNotifier,
        pyafk_dir: Path,
    ):
        self.storage = storage
        self.notifier = notifier
        self.lock = PollLock(pyafk_dir / "poll.lock")
        self._offset: Optional[int] = None
        self._running = False

    async def process_updates_once(self) -> int:
        """Process one batch of updates.

        Returns number of updates processed.
        """
        updates = await self.notifier.get_updates(
            offset=self._offset,
            timeout=1,  # Short timeout for single poll
        )

        processed = 0
        for update in updates:
            self._offset = update["update_id"] + 1

            if "callback_query" in update:
                await self._handle_callback(update["callback_query"])
                processed += 1

        return processed

    async def _handle_callback(self, callback: dict):
        """Handle a callback query from inline button."""
        callback_id = callback["id"]
        data = callback.get("data", "")

        # Parse callback data: "action:id"
        if ":" not in data:
            return

        action, target_id = data.split(":", 1)

        if action in ("approve", "deny"):
            await self._handle_approval(target_id, action, callback_id)
        elif action == "approve_all":
            await self._handle_approve_all(target_id, callback_id)
        elif action == "add_rule":
            await self._handle_add_rule(target_id, callback_id)

    async def _handle_approval(
        self,
        request_id: str,
        action: str,
        callback_id: str,
    ):
        """Handle approve/deny callback."""
        status = "approved" if action == "approve" else "denied"

        await self.storage.resolve_request(
            request_id=request_id,
            status=status,
            resolved_by="user",
        )

        # Acknowledge callback
        await self.notifier.answer_callback(
            callback_id,
            f"{'✅ Approved' if action == 'approve' else '❌ Denied'}",
        )

        # Update message to show result
        request = await self.storage.get_request(request_id)
        if request and request.telegram_msg_id:
            await self.notifier.edit_message(
                request.telegram_msg_id,
                f"{'✅' if action == 'approve' else '❌'} {request.tool_name} - {status.upper()}",
            )

        # Log to audit
        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id if request else None,
            details={
                "request_id": request_id,
                "action": action,
                "resolved_by": "user",
            },
        )

    async def _handle_approve_all(self, session_id: str, callback_id: str):
        """Approve all pending requests for a session."""
        pending = await self.storage.get_pending_requests()
        session_pending = [r for r in pending if r.session_id == session_id]

        for request in session_pending:
            await self.storage.resolve_request(
                request_id=request.id,
                status="approved",
                resolved_by="user:approve_all",
            )

        await self.notifier.answer_callback(
            callback_id,
            f"✅ Approved {len(session_pending)} requests",
        )

    async def _handle_add_rule(self, request_id: str, callback_id: str):
        """Handle add rule button - for now just acknowledge."""
        # TODO: Implement rule creation flow via followup message
        await self.notifier.answer_callback(
            callback_id,
            "Rule creation coming soon",
        )

    async def poll_loop(self, timeout: float = 30.0):
        """Main polling loop. Acquires lock first.

        Args:
            timeout: How long to poll before returning
        """
        acquired = await self.lock.acquire(timeout=0.1)
        if not acquired:
            # Another process is polling, just wait
            return

        try:
            self._running = True
            start = asyncio.get_event_loop().time()

            while self._running:
                elapsed = asyncio.get_event_loop().time() - start
                if elapsed >= timeout:
                    break

                await self.process_updates_once()
                await asyncio.sleep(0.5)
        finally:
            self._running = False
            await self.lock.release()

    def stop(self):
        """Signal the poll loop to stop."""
        self._running = False
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_poller.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add Telegram poller with file-based locking"
```

---

## Task 8: Approval Manager (Core API)

**Files:**
- Create: `src/pyafk/core/manager.py`
- Create: `tests/test_manager.py`

**Step 1: Write the failing test**

Create `tests/test_manager.py`:

```python
"""Tests for ApprovalManager."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pyafk.core.manager import ApprovalManager


@pytest.mark.asyncio
async def test_manager_auto_approve_by_rule(mock_pyafk_dir):
    """Manager should auto-approve based on rules."""
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    # Add an auto-approve rule
    await manager.rules.add_rule("Bash(git *)", "approve")

    result = await manager.request_approval(
        session_id="session-123",
        tool_name="Bash",
        tool_input='{"command": "git status"}',
    )

    assert result == "approve"
    await manager.close()


@pytest.mark.asyncio
async def test_manager_auto_deny_by_rule(mock_pyafk_dir):
    """Manager should auto-deny based on rules."""
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    await manager.rules.add_rule("Bash(rm *)", "deny")

    result = await manager.request_approval(
        session_id="session-123",
        tool_name="Bash",
        tool_input='{"command": "rm -rf /"}',
    )

    assert result == "deny"
    await manager.close()


@pytest.mark.asyncio
async def test_manager_timeout_action(mock_pyafk_dir):
    """Manager should apply timeout action when no response."""
    manager = ApprovalManager(
        pyafk_dir=mock_pyafk_dir,
        timeout=0.1,  # Very short timeout
        timeout_action="deny",
    )
    await manager.initialize()

    # Use console notifier with no auto response
    from pyafk.notifiers.console import ConsoleNotifier
    manager.notifier = ConsoleNotifier()

    result = await manager.request_approval(
        session_id="session-123",
        tool_name="Bash",
        tool_input='{"command": "ls"}',
    )

    assert result == "deny"
    await manager.close()


@pytest.mark.asyncio
async def test_manager_tracks_session(mock_pyafk_dir):
    """Manager should track session heartbeat."""
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    await manager.rules.add_rule("Read(*)", "approve")

    await manager.request_approval(
        session_id="session-123",
        tool_name="Read",
        tool_input='{"file_path": "/test.txt"}',
        project_path="/home/user/project",
    )

    session = await manager.storage.get_session("session-123")
    assert session is not None
    assert session.project_path == "/home/user/project"

    await manager.close()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_manager.py -v
```

Expected: FAIL

**Step 3: Write implementation**

Create `src/pyafk/core/manager.py`:

```python
"""Approval Manager - the core API."""

import asyncio
from pathlib import Path
from typing import Optional

from pyafk.core.poller import Poller
from pyafk.core.rules import RulesEngine
from pyafk.core.storage import Storage
from pyafk.notifiers.base import Notifier
from pyafk.notifiers.console import ConsoleNotifier
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.config import Config, get_pyafk_dir


class ApprovalManager:
    """Main API for requesting approvals."""

    def __init__(
        self,
        pyafk_dir: Optional[Path] = None,
        timeout: int = 3600,
        timeout_action: str = "deny",
        config: Optional[Config] = None,
    ):
        self.pyafk_dir = pyafk_dir or get_pyafk_dir()
        self.timeout = timeout
        self.timeout_action = timeout_action
        self._config = config

        self.storage: Optional[Storage] = None
        self.rules: Optional[RulesEngine] = None
        self.notifier: Optional[Notifier] = None
        self.poller: Optional[Poller] = None
        self._initialized = False

    async def initialize(self):
        """Initialize storage and components."""
        if self._initialized:
            return

        self.pyafk_dir.mkdir(parents=True, exist_ok=True)

        # Load config
        if not self._config:
            self._config = Config(self.pyafk_dir)

        # Initialize storage
        self.storage = Storage(self._config.db_path)
        await self.storage.connect()

        # Initialize rules engine
        self.rules = RulesEngine(self.storage)

        # Initialize notifier
        if self._config.telegram_bot_token and self._config.telegram_chat_id:
            self.notifier = TelegramNotifier(
                bot_token=self._config.telegram_bot_token,
                chat_id=self._config.telegram_chat_id,
                timeout=self.timeout,
                timeout_action=self.timeout_action,
            )
            self.poller = Poller(self.storage, self.notifier, self.pyafk_dir)
        else:
            self.notifier = ConsoleNotifier()
            self.poller = None

        self._initialized = True

    async def close(self):
        """Close connections."""
        if self.storage:
            await self.storage.close()
            self.storage = None
        self._initialized = False

    async def request_approval(
        self,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
        project_path: Optional[str] = None,
    ) -> str:
        """Request approval for a tool call.

        Returns:
            "approve" or "deny"
        """
        if not self._initialized:
            await self.initialize()

        # Update session heartbeat
        await self.storage.upsert_session(
            session_id=session_id,
            project_path=project_path,
        )

        # Check auto-approve rules first
        rule_result = await self.rules.check(tool_name, tool_input)
        if rule_result:
            await self.storage.log_audit(
                event_type="auto_response",
                session_id=session_id,
                details={
                    "tool_name": tool_name,
                    "action": rule_result,
                    "reason": "rule_match",
                },
            )
            return rule_result

        # Create request in database
        request_id = await self.storage.create_request(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
            description=description,
        )

        # Send notification
        msg_id = await self.notifier.send_approval_request(
            request_id=request_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
            description=description,
        )

        if msg_id:
            await self.storage.set_telegram_msg_id(request_id, msg_id)

        # Log the request
        await self.storage.log_audit(
            event_type="request",
            session_id=session_id,
            details={
                "request_id": request_id,
                "tool_name": tool_name,
            },
        )

        # Wait for response
        result = await self._wait_for_response(request_id)
        return result

    async def _wait_for_response(self, request_id: str) -> str:
        """Wait for approval response with polling."""
        start = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= self.timeout:
                # Timeout - apply default action
                await self.storage.resolve_request(
                    request_id=request_id,
                    status=self.timeout_action + "d",  # "approved" or "denied"
                    resolved_by="timeout",
                )
                await self.storage.log_audit(
                    event_type="timeout",
                    details={
                        "request_id": request_id,
                        "action": self.timeout_action,
                    },
                )
                return self.timeout_action

            # Poll for updates if we have a poller
            if self.poller:
                await self.poller.process_updates_once()

            # Check if request was resolved
            request = await self.storage.get_request(request_id)
            if request and request.status != "pending":
                if request.status == "approved":
                    return "approve"
                else:
                    return "deny"

            await asyncio.sleep(0.5)
```

**Step 4: Update pyafk/__init__.py exports**

```python
"""pyafk - Remote approval system for Claude Code."""

__version__ = "0.1.0"

from pyafk.core.manager import ApprovalManager
from pyafk.notifiers import ConsoleNotifier, Notifier, TelegramNotifier

__all__ = [
    "ApprovalManager",
    "Notifier",
    "ConsoleNotifier",
    "TelegramNotifier",
]
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_manager.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: add ApprovalManager as core API"
```

---

## Task 9: Fast Path Entry Point

**Files:**
- Create: `src/pyafk/fast_path.py`
- Create: `tests/test_fast_path.py`

**Step 1: Write the failing test**

Create `tests/test_fast_path.py`:

```python
"""Tests for fast path mode check."""

import pytest

from pyafk.fast_path import check_fast_path, FastPathResult


def test_fast_path_off_mode(mock_pyafk_dir):
    """Fast path should return approve when mode is off."""
    mode_file = mock_pyafk_dir / "mode"
    mode_file.write_text("off")

    result = check_fast_path(mock_pyafk_dir)

    assert result == FastPathResult.APPROVE


def test_fast_path_on_mode(mock_pyafk_dir):
    """Fast path should return continue when mode is on."""
    mode_file = mock_pyafk_dir / "mode"
    mode_file.write_text("on")

    result = check_fast_path(mock_pyafk_dir)

    assert result == FastPathResult.CONTINUE


def test_fast_path_no_mode_file(mock_pyafk_dir):
    """Fast path should return approve when no mode file."""
    result = check_fast_path(mock_pyafk_dir)

    assert result == FastPathResult.APPROVE


def test_fast_path_invalid_mode(mock_pyafk_dir):
    """Fast path should return continue for unknown mode."""
    mode_file = mock_pyafk_dir / "mode"
    mode_file.write_text("unknown")

    result = check_fast_path(mock_pyafk_dir)

    # Unknown mode = continue to full check
    assert result == FastPathResult.CONTINUE
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_fast_path.py -v
```

Expected: FAIL

**Step 3: Write implementation**

Create `src/pyafk/fast_path.py`:

```python
"""Fast path mode check - minimal overhead when disabled."""

import os
from enum import Enum
from pathlib import Path
from typing import Optional


class FastPathResult(Enum):
    """Result of fast path check."""
    APPROVE = "approve"  # Exit immediately with approve
    DENY = "deny"        # Exit immediately with deny
    CONTINUE = "continue"  # Continue to full approval flow


def check_fast_path(pyafk_dir: Optional[Path] = None) -> FastPathResult:
    """Check if we can fast-path without loading heavy modules.

    This function is designed to be as fast as possible:
    - No imports beyond stdlib
    - Single file read
    - No exception handling overhead for common case

    Args:
        pyafk_dir: Path to pyafk directory. If None, uses PYAFK_DIR env
                   or defaults to ~/.pyafk

    Returns:
        FastPathResult indicating whether to approve, deny, or continue
    """
    if pyafk_dir is None:
        env_dir = os.environ.get("PYAFK_DIR")
        if env_dir:
            pyafk_dir = Path(env_dir)
        else:
            pyafk_dir = Path.home() / ".pyafk"

    mode_file = pyafk_dir / "mode"

    try:
        mode = mode_file.read_text().strip()
    except FileNotFoundError:
        # No mode file = disabled = fast approve
        return FastPathResult.APPROVE
    except Exception:
        # Any other error = continue to full check
        return FastPathResult.CONTINUE

    if mode == "off":
        return FastPathResult.APPROVE
    elif mode == "on":
        return FastPathResult.CONTINUE
    else:
        # Unknown mode, let full system handle it
        return FastPathResult.CONTINUE


def fast_path_main():
    """Entry point for fast path check only.

    Usage from shell:
        python -c "from pyafk.fast_path import fast_path_main; fast_path_main()"

    Exit codes:
        0 = approve (fast path)
        1 = deny (fast path)
        2 = continue to full check
    """
    import sys

    result = check_fast_path()

    if result == FastPathResult.APPROVE:
        print('{"decision": "approve"}')
        sys.exit(0)
    elif result == FastPathResult.DENY:
        print('{"decision": "deny"}')
        sys.exit(1)
    else:
        sys.exit(2)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_fast_path.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add fast path for instant mode check"
```

---

## Task 10: Hook Handlers

**Files:**
- Create: `src/pyafk/hooks/__init__.py`
- Create: `src/pyafk/hooks/handler.py`
- Create: `src/pyafk/hooks/pretool.py`
- Create: `tests/test_hooks.py`

**Step 1: Write the failing test**

Create `tests/test_hooks.py`:

```python
"""Tests for Claude Code hook handlers."""

import json
import pytest

from pyafk.hooks.pretool import handle_pretool_use


@pytest.mark.asyncio
async def test_pretool_approve_by_rule(mock_pyafk_dir):
    """PreToolUse should auto-approve by rule."""
    # Set mode to on
    (mock_pyafk_dir / "mode").write_text("on")

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "session_id": "session-123",
    }

    # Add auto-approve rule
    from pyafk.core.manager import ApprovalManager
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()
    await manager.rules.add_rule("Bash(git *)", "approve")
    await manager.close()

    result = await handle_pretool_use(hook_input, mock_pyafk_dir)

    assert result["decision"] == "approve"


@pytest.mark.asyncio
async def test_pretool_off_mode_approves(mock_pyafk_dir):
    """PreToolUse should approve when mode is off."""
    (mock_pyafk_dir / "mode").write_text("off")

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /"},
        "session_id": "session-123",
    }

    result = await handle_pretool_use(hook_input, mock_pyafk_dir)

    assert result["decision"] == "approve"


@pytest.mark.asyncio
async def test_pretool_extracts_context(mock_pyafk_dir):
    """PreToolUse should extract context from hook input."""
    (mock_pyafk_dir / "mode").write_text("on")

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "ls", "description": "List files"},
        "session_id": "session-123",
        "tool_context": "User wants to see directory contents",
    }

    # Add rule so we don't block
    from pyafk.core.manager import ApprovalManager
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()
    await manager.rules.add_rule("Bash(*)", "approve")
    await manager.close()

    result = await handle_pretool_use(hook_input, mock_pyafk_dir)

    assert result["decision"] == "approve"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_hooks.py -v
```

Expected: FAIL

**Step 3: Create hooks/__init__.py**

```python
"""Claude Code hook handlers."""
```

**Step 4: Create handler.py**

Create `src/pyafk/hooks/handler.py`:

```python
"""Main hook handler dispatcher."""

import json
import sys
from pathlib import Path
from typing import Optional

from pyafk.fast_path import FastPathResult, check_fast_path


async def handle_hook(
    hook_type: str,
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle a Claude Code hook.

    Args:
        hook_type: "PreToolUse", "Stop", or "SessionStart"
        hook_input: Parsed JSON from stdin
        pyafk_dir: Path to pyafk directory

    Returns:
        Response dict to output as JSON
    """
    if hook_type == "PreToolUse":
        from pyafk.hooks.pretool import handle_pretool_use
        return await handle_pretool_use(hook_input, pyafk_dir)
    elif hook_type == "Stop":
        from pyafk.hooks.stop import handle_stop
        return await handle_stop(hook_input, pyafk_dir)
    elif hook_type == "SessionStart":
        from pyafk.hooks.session import handle_session_start
        return await handle_session_start(hook_input, pyafk_dir)
    else:
        return {"error": f"Unknown hook type: {hook_type}"}


def main():
    """CLI entry point for hooks."""
    import asyncio

    if len(sys.argv) < 3 or sys.argv[1] != "hook":
        print(json.dumps({"error": "Usage: pyafk hook <HookType>"}))
        sys.exit(1)

    hook_type = sys.argv[2]

    # Fast path check first
    result = check_fast_path()
    if result == FastPathResult.APPROVE:
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)
    elif result == FastPathResult.DENY:
        print(json.dumps({"decision": "deny"}))
        sys.exit(0)

    # Read stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input"}))
        sys.exit(1)

    # Run async handler
    response = asyncio.run(handle_hook(hook_type, hook_input))
    print(json.dumps(response))
```

**Step 5: Create pretool.py**

Create `src/pyafk/hooks/pretool.py`:

```python
"""PreToolUse hook handler."""

import json
from pathlib import Path
from typing import Optional

from pyafk.core.manager import ApprovalManager
from pyafk.fast_path import FastPathResult, check_fast_path


async def handle_pretool_use(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle PreToolUse hook.

    Args:
        hook_input: Hook data from Claude Code containing:
            - tool_name: Name of the tool being called
            - tool_input: Parameters for the tool
            - session_id: Claude session ID
            - tool_context: (optional) Why the tool is being called

    Returns:
        {"decision": "approve"} or {"decision": "deny"}
    """
    # Fast path check
    fast_result = check_fast_path(pyafk_dir)
    if fast_result == FastPathResult.APPROVE:
        return {"decision": "approve"}
    elif fast_result == FastPathResult.DENY:
        return {"decision": "deny"}

    # Extract fields
    tool_name = hook_input.get("tool_name", "Unknown")
    tool_input = hook_input.get("tool_input")
    session_id = hook_input.get("session_id", "unknown")
    context = hook_input.get("tool_context")

    # tool_input might be dict or string
    if isinstance(tool_input, dict):
        description = tool_input.get("description")
        tool_input_str = json.dumps(tool_input)
    else:
        description = None
        tool_input_str = str(tool_input) if tool_input else None

    # Get project path from environment or hook
    project_path = hook_input.get("project_path")

    # Request approval
    manager = ApprovalManager(pyafk_dir=pyafk_dir)
    try:
        result = await manager.request_approval(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input_str,
            context=context,
            description=description,
            project_path=project_path,
        )
        return {"decision": result}
    finally:
        await manager.close()
```

**Step 6: Create stop.py and session.py stubs**

Create `src/pyafk/hooks/stop.py`:

```python
"""Stop hook handler."""

from pathlib import Path
from typing import Optional


async def handle_stop(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle Stop hook - notify that session ended."""
    # TODO: Send summary to Telegram
    return {}
```

Create `src/pyafk/hooks/session.py`:

```python
"""SessionStart hook handler."""

from pathlib import Path
from typing import Optional


async def handle_session_start(
    hook_input: dict,
    pyafk_dir: Optional[Path] = None,
) -> dict:
    """Handle SessionStart hook - notify new session."""
    # TODO: Send notification to Telegram
    return {}
```

**Step 7: Run test to verify it passes**

```bash
pytest tests/test_hooks.py -v
```

Expected: PASS

**Step 8: Commit**

```bash
git add -A
git commit -m "feat: add Claude Code hook handlers"
```

---

## Task 11: CLI Commands

**Files:**
- Modify: `src/pyafk/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
"""Tests for CLI commands."""

import json
import pytest
from click.testing import CliRunner

from pyafk.cli import main


@pytest.fixture
def cli_runner():
    return CliRunner()


def test_cli_status_off(cli_runner, mock_pyafk_dir, monkeypatch):
    """Status command shows off mode."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    (mock_pyafk_dir / "mode").write_text("off")

    result = cli_runner.invoke(main, ["status"])

    assert result.exit_code == 0
    assert "off" in result.output.lower()


def test_cli_on_command(cli_runner, mock_pyafk_dir, monkeypatch):
    """On command enables pyafk."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))

    result = cli_runner.invoke(main, ["on"])

    assert result.exit_code == 0
    assert (mock_pyafk_dir / "mode").read_text() == "on"


def test_cli_off_command(cli_runner, mock_pyafk_dir, monkeypatch):
    """Off command disables pyafk."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    (mock_pyafk_dir / "mode").write_text("on")

    result = cli_runner.invoke(main, ["off"])

    assert result.exit_code == 0
    assert (mock_pyafk_dir / "mode").read_text() == "off"


def test_cli_rules_list_empty(cli_runner, mock_pyafk_dir, monkeypatch):
    """Rules list shows empty when no rules."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))

    result = cli_runner.invoke(main, ["rules", "list"])

    assert result.exit_code == 0
    assert "no rules" in result.output.lower() or "empty" in result.output.lower() or result.output.strip() == ""


def test_cli_rules_add(cli_runner, mock_pyafk_dir, monkeypatch):
    """Rules add creates a new rule."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))

    result = cli_runner.invoke(main, ["rules", "add", "Bash(git *)", "--approve"])

    assert result.exit_code == 0

    # Verify rule was added
    result = cli_runner.invoke(main, ["rules", "list"])
    assert "Bash(git *)" in result.output
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_cli.py -v
```

Expected: FAIL

**Step 3: Write full CLI implementation**

Replace `src/pyafk/cli.py`:

```python
"""CLI entry point."""

import asyncio
import json
import sys
from pathlib import Path

import click

from pyafk.utils.config import Config, get_pyafk_dir


def run_async(coro):
    """Run async function synchronously."""
    return asyncio.run(coro)


@click.group()
@click.pass_context
def main(ctx):
    """pyafk - Remote approval system for Claude Code."""
    ctx.ensure_object(dict)
    ctx.obj["pyafk_dir"] = get_pyafk_dir()


@main.command()
@click.pass_context
def status(ctx):
    """Show current status."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    mode = config.get_mode()

    click.echo(f"Mode: {mode}")
    click.echo(f"Config dir: {pyafk_dir}")

    if config.telegram_bot_token:
        click.echo("Telegram: configured")
    else:
        click.echo("Telegram: not configured")


@main.command()
@click.pass_context
def on(ctx):
    """Enable pyafk approvals."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    config.set_mode("on")
    click.echo("pyafk enabled")


@main.command()
@click.pass_context
def off(ctx):
    """Disable pyafk (fast approve all)."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)
    config.set_mode("off")
    click.echo("pyafk disabled")


@main.group()
def rules():
    """Manage auto-approve rules."""
    pass


@rules.command("list")
@click.pass_context
def rules_list(ctx):
    """List all rules."""
    async def _list():
        from pyafk.core.manager import ApprovalManager
        manager = ApprovalManager(pyafk_dir=ctx.obj["pyafk_dir"])
        await manager.initialize()
        rules = await manager.rules.list_rules()
        await manager.close()
        return rules

    rules_data = run_async(_list())

    if not rules_data:
        click.echo("No rules configured")
        return

    for rule in rules_data:
        action_icon = "✅" if rule["action"] == "approve" else "❌"
        click.echo(f"{rule['id']:3d}. {action_icon} {rule['pattern']}")


@rules.command("add")
@click.argument("pattern")
@click.option("--approve", "action", flag_value="approve", default=True)
@click.option("--deny", "action", flag_value="deny")
@click.option("--priority", default=0, type=int)
@click.pass_context
def rules_add(ctx, pattern, action, priority):
    """Add an auto-approve rule."""
    async def _add():
        from pyafk.core.manager import ApprovalManager
        manager = ApprovalManager(pyafk_dir=ctx.obj["pyafk_dir"])
        await manager.initialize()
        rule_id = await manager.rules.add_rule(pattern, action, priority)
        await manager.close()
        return rule_id

    rule_id = run_async(_add())
    action_word = "auto-approve" if action == "approve" else "auto-deny"
    click.echo(f"Added rule #{rule_id}: {action_word} {pattern}")


@rules.command("remove")
@click.argument("rule_id", type=int)
@click.pass_context
def rules_remove(ctx, rule_id):
    """Remove a rule by ID."""
    async def _remove():
        from pyafk.core.manager import ApprovalManager
        manager = ApprovalManager(pyafk_dir=ctx.obj["pyafk_dir"])
        await manager.initialize()
        removed = await manager.rules.remove_rule(rule_id)
        await manager.close()
        return removed

    if run_async(_remove()):
        click.echo(f"Removed rule #{rule_id}")
    else:
        click.echo(f"Rule #{rule_id} not found")


@main.group()
def telegram():
    """Telegram configuration."""
    pass


@telegram.command("setup")
@click.pass_context
def telegram_setup(ctx):
    """Interactive Telegram setup."""
    pyafk_dir = ctx.obj["pyafk_dir"]
    config = Config(pyafk_dir)

    click.echo("Telegram Bot Setup")
    click.echo("=" * 40)
    click.echo("1. Talk to @BotFather on Telegram")
    click.echo("2. Create a new bot with /newbot")
    click.echo("3. Copy the bot token")
    click.echo()

    token = click.prompt("Bot token")
    config.telegram_bot_token = token

    click.echo()
    click.echo("4. Send a message to your bot")
    click.echo("5. Get your chat ID from the message")
    click.echo()

    chat_id = click.prompt("Chat ID")
    config.telegram_chat_id = chat_id

    config.save()
    click.echo()
    click.echo("Telegram configured! Run 'pyafk telegram test' to verify.")


@telegram.command("test")
@click.pass_context
def telegram_test(ctx):
    """Send a test message."""
    async def _test():
        from pyafk.notifiers.telegram import TelegramNotifier
        pyafk_dir = ctx.obj["pyafk_dir"]
        config = Config(pyafk_dir)

        if not config.telegram_bot_token or not config.telegram_chat_id:
            click.echo("Telegram not configured. Run 'pyafk telegram setup' first.")
            return False

        notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        msg_id = await notifier.send_approval_request(
            request_id="test",
            session_id="test-session",
            tool_name="Test",
            description="This is a test message from pyafk",
        )

        return msg_id is not None

    if run_async(_test()):
        click.echo("Test message sent successfully!")
    else:
        click.echo("Failed to send test message")


@main.command()
@click.argument("hook_type")
@click.pass_context
def hook(ctx, hook_type):
    """Handle a Claude Code hook (internal)."""
    from pyafk.hooks.handler import handle_hook

    # Read stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        click.echo(json.dumps({"error": "Invalid JSON input"}))
        sys.exit(1)

    response = run_async(handle_hook(hook_type, hook_input, ctx.obj["pyafk_dir"]))
    click.echo(json.dumps(response))


@main.command()
@click.pass_context
def sessions(ctx):
    """List active sessions."""
    async def _sessions():
        from pyafk.core.manager import ApprovalManager
        manager = ApprovalManager(pyafk_dir=ctx.obj["pyafk_dir"])
        await manager.initialize()
        sessions = await manager.storage.get_active_sessions()
        await manager.close()
        return sessions

    sessions_data = run_async(_sessions())

    if not sessions_data:
        click.echo("No active sessions")
        return

    for session in sessions_data:
        import time
        age = time.time() - session.last_seen_at
        if age < 60:
            age_str = f"{int(age)}s ago"
        elif age < 3600:
            age_str = f"{int(age/60)}m ago"
        else:
            age_str = f"{int(age/3600)}h ago"

        click.echo(f"{session.session_id[:8]} - {session.project_path or 'unknown'} - {age_str}")


@main.command()
@click.option("--limit", default=20, type=int)
@click.pass_context
def history(ctx, limit):
    """Show audit log."""
    async def _history():
        from pyafk.core.manager import ApprovalManager
        manager = ApprovalManager(pyafk_dir=ctx.obj["pyafk_dir"])
        await manager.initialize()
        entries = await manager.storage.get_audit_log(limit=limit)
        await manager.close()
        return entries

    entries = run_async(_history())

    if not entries:
        click.echo("No history")
        return

    import datetime
    for entry in entries:
        dt = datetime.datetime.fromtimestamp(entry.timestamp)
        time_str = dt.strftime("%H:%M:%S")
        click.echo(f"{time_str} [{entry.event_type}] {entry.details}")


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_cli.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add full CLI with rules, telegram, and status commands"
```

---

## Task 12: Install/Uninstall Commands

**Files:**
- Modify: `src/pyafk/cli.py` (add install/uninstall)
- Create: `tests/test_install.py`

**Step 1: Write the failing test**

Create `tests/test_install.py`:

```python
"""Tests for install/uninstall commands."""

import json
import pytest
from click.testing import CliRunner
from pathlib import Path

from pyafk.cli import main


@pytest.fixture
def cli_runner():
    return CliRunner()


def test_install_creates_hooks(cli_runner, mock_pyafk_dir, tmp_path, monkeypatch):
    """Install should create hook configuration."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))

    # Create mock Claude settings dir
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))

    result = cli_runner.invoke(main, ["install"], input="y\n")

    assert result.exit_code == 0

    # Check settings file was created/modified
    settings_file = claude_dir / "settings.json"
    assert settings_file.exists()

    settings = json.loads(settings_file.read_text())
    assert "hooks" in settings


def test_uninstall_removes_hooks(cli_runner, mock_pyafk_dir, tmp_path, monkeypatch):
    """Uninstall should remove hook configuration."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    monkeypatch.setenv("HOME", str(tmp_path))

    # Create mock Claude settings with hooks
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_file = claude_dir / "settings.json"
    settings_file.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{"command": "pyafk hook PreToolUse"}]
        }
    }))

    result = cli_runner.invoke(main, ["uninstall"], input="k\n")  # Keep data

    assert result.exit_code == 0

    # Hooks should be removed
    settings = json.loads(settings_file.read_text())
    assert "PreToolUse" not in settings.get("hooks", {})
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_install.py -v
```

Expected: FAIL

**Step 3: Add install/uninstall commands to cli.py**

Add these commands to `src/pyafk/cli.py`:

```python
@main.command()
@click.pass_context
def install(ctx):
    """Install pyafk hooks into Claude Code."""
    import os

    pyafk_dir = ctx.obj["pyafk_dir"]
    home = Path(os.environ.get("HOME", Path.home()))
    claude_settings = home / ".claude" / "settings.json"

    # Ensure directories exist
    pyafk_dir.mkdir(parents=True, exist_ok=True)
    claude_settings.parent.mkdir(parents=True, exist_ok=True)

    # Load existing settings
    if claude_settings.exists():
        settings = json.loads(claude_settings.read_text())
    else:
        settings = {}

    # Hook command
    hook_cmd = "pyafk hook"

    # Define hooks
    new_hooks = {
        "PreToolUse": [{"command": f"{hook_cmd} PreToolUse"}],
        "Stop": [{"command": f"{hook_cmd} Stop"}],
        "SessionStart": [{"command": f"{hook_cmd} SessionStart"}],
    }

    # Merge with existing hooks
    existing_hooks = settings.get("hooks", {})

    click.echo("Installing pyafk hooks...")
    click.echo()

    for hook_name, hook_config in new_hooks.items():
        if hook_name in existing_hooks:
            click.echo(f"  {hook_name}: already has hooks, adding pyafk")
            # Prepend our hook
            existing_hooks[hook_name] = hook_config + existing_hooks[hook_name]
        else:
            click.echo(f"  {hook_name}: adding pyafk hook")
            existing_hooks[hook_name] = hook_config

    settings["hooks"] = existing_hooks

    # Confirm
    click.echo()
    if not click.confirm("Apply these changes?"):
        click.echo("Cancelled")
        return

    # Write settings
    claude_settings.write_text(json.dumps(settings, indent=2))

    click.echo()
    click.echo("Hooks installed!")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Run 'pyafk telegram setup' to configure Telegram")
    click.echo("  2. Run 'pyafk on' to enable approvals")


@main.command()
@click.pass_context
def uninstall(ctx):
    """Remove pyafk hooks from Claude Code."""
    import os

    pyafk_dir = ctx.obj["pyafk_dir"]
    home = Path(os.environ.get("HOME", Path.home()))
    claude_settings = home / ".claude" / "settings.json"

    # Remove hooks
    if claude_settings.exists():
        settings = json.loads(claude_settings.read_text())
        hooks = settings.get("hooks", {})

        click.echo("Removing pyafk hooks...")

        for hook_name in ["PreToolUse", "Stop", "SessionStart"]:
            if hook_name in hooks:
                # Remove pyafk hooks
                hooks[hook_name] = [
                    h for h in hooks[hook_name]
                    if "pyafk" not in h.get("command", "")
                ]
                if not hooks[hook_name]:
                    del hooks[hook_name]

        settings["hooks"] = hooks
        claude_settings.write_text(json.dumps(settings, indent=2))
        click.echo("Hooks removed")
    else:
        click.echo("No Claude settings found")

    # Handle data
    click.echo()
    if pyafk_dir.exists():
        # Count data
        db_path = pyafk_dir / "pyafk.db"
        db_size = db_path.stat().st_size if db_path.exists() else 0

        click.echo(f"Found pyafk data in {pyafk_dir}")
        if db_size > 0:
            click.echo(f"  Database: {db_size / 1024:.1f} KB")

        click.echo()
        click.echo("What would you like to do?")
        click.echo("  [K] Keep data (can reinstall later)")
        click.echo("  [D] Delete everything")
        click.echo("  [E] Export history first, then delete")

        choice = click.prompt("Choice", type=click.Choice(["k", "d", "e"], case_sensitive=False))

        if choice.lower() == "d":
            import shutil
            shutil.rmtree(pyafk_dir)
            click.echo("Data deleted")
        elif choice.lower() == "e":
            # Export then delete
            export_path = home / f"pyafk-export-{__import__('datetime').date.today()}.json"
            # TODO: Implement export
            click.echo(f"Export to {export_path} not yet implemented")
            click.echo("Data kept")
        else:
            click.echo("Data kept")

    click.echo()
    click.echo("pyafk uninstalled")
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_install.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: add install and uninstall commands"
```

---

## Task 13: Integration Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

Create `tests/test_integration.py`:

```python
"""End-to-end integration tests."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from pyafk.core.manager import ApprovalManager
from pyafk.hooks.pretool import handle_pretool_use


@pytest.mark.asyncio
async def test_full_approval_flow(mock_pyafk_dir):
    """Test complete approval flow from hook to response."""
    # Enable pyafk
    (mock_pyafk_dir / "mode").write_text("on")

    # Configure Telegram (mocked)
    config_data = {
        "telegram_bot_token": "test-token",
        "telegram_chat_id": "12345",
        "timeout_seconds": 1,
        "timeout_action": "deny",
    }
    (mock_pyafk_dir / "config.json").write_text(json.dumps(config_data))

    # Mock Telegram API
    with patch("pyafk.notifiers.telegram.TelegramNotifier._api_request") as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 1}}

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "session_id": "integration-test",
        }

        # This should timeout and deny (1 second timeout)
        result = await handle_pretool_use(hook_input, mock_pyafk_dir)

        assert result["decision"] == "deny"

        # Verify Telegram was called
        mock_api.assert_called()


@pytest.mark.asyncio
async def test_rule_based_auto_approve(mock_pyafk_dir):
    """Test that rules auto-approve without Telegram."""
    (mock_pyafk_dir / "mode").write_text("on")

    # Add rule
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()
    await manager.rules.add_rule("Read(*)", "approve")
    await manager.close()

    hook_input = {
        "tool_name": "Read",
        "tool_input": {"file_path": "/etc/passwd"},
        "session_id": "rule-test",
    }

    result = await handle_pretool_use(hook_input, mock_pyafk_dir)

    assert result["decision"] == "approve"


@pytest.mark.asyncio
async def test_session_tracking(mock_pyafk_dir):
    """Test that sessions are tracked across requests."""
    (mock_pyafk_dir / "mode").write_text("on")

    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()

    # Add rule so we don't block
    await manager.rules.add_rule("*", "approve")

    # Make requests from same session
    await manager.request_approval(
        session_id="tracked-session",
        tool_name="Read",
        project_path="/home/user/project1",
    )

    await manager.request_approval(
        session_id="tracked-session",
        tool_name="Write",
        project_path="/home/user/project1",
    )

    # Check session was tracked
    session = await manager.storage.get_session("tracked-session")
    assert session is not None
    assert session.project_path == "/home/user/project1"

    # Check audit log
    log = await manager.storage.get_audit_log(limit=10)
    assert len(log) >= 2

    await manager.close()
```

**Step 2: Run integration test**

```bash
pytest tests/test_integration.py -v
```

Expected: PASS

**Step 3: Run full test suite**

```bash
pytest -v
```

Expected: All tests pass

**Step 4: Commit**

```bash
git add -A
git commit -m "test: add integration tests for full approval flow"
```

---

## Summary

This plan creates pyafk in 13 tasks:

1. **Project Setup** - pyproject.toml, directory structure
2. **Config Module** - Load/save configuration
3. **Storage Layer** - SQLite with WAL mode
4. **Rules Engine** - Pattern matching for auto-approve
5. **Notifier Interface** - Abstract base + console implementation
6. **Telegram Notifier** - Bot API integration
7. **Poller with Lock** - Single-poller pattern
8. **Approval Manager** - Core API
9. **Fast Path** - Instant mode check
10. **Hook Handlers** - Claude Code integration
11. **CLI Commands** - User interface
12. **Install/Uninstall** - Setup automation
13. **Integration Tests** - End-to-end verification

Each task follows TDD with specific test → implement → verify → commit steps.
