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
    denial_reason: Optional[str] = None


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
    resolved_by     TEXT,
    denial_reason   TEXT
);

CREATE TABLE IF NOT EXISTS pending_feedback (
    prompt_msg_id   INTEGER PRIMARY KEY,
    request_id      TEXT NOT NULL,
    created_at      REAL
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
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA temp_store=memory")

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
        denial_reason: Optional[str] = None,
    ):
        """Update request status."""
        now = time.time()
        await self._conn.execute(
            """
            UPDATE requests SET status = ?, resolved_at = ?, resolved_by = ?, denial_reason = ?
            WHERE id = ?
            """,
            (status, now, resolved_by, denial_reason, request_id),
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

    # Pending feedback

    async def set_pending_feedback(self, prompt_msg_id: int, request_id: str):
        """Track a feedback prompt message."""
        now = time.time()
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO pending_feedback (prompt_msg_id, request_id, created_at)
            VALUES (?, ?, ?)
            """,
            (prompt_msg_id, request_id, now),
        )
        await self._conn.commit()

    async def get_pending_feedback(self, prompt_msg_id: int) -> Optional[str]:
        """Get request_id for a feedback prompt message."""
        cursor = await self._conn.execute(
            "SELECT request_id FROM pending_feedback WHERE prompt_msg_id = ?",
            (prompt_msg_id,),
        )
        row = await cursor.fetchone()
        return row["request_id"] if row else None

    async def clear_pending_feedback(self, prompt_msg_id: int):
        """Remove a pending feedback entry."""
        await self._conn.execute(
            "DELETE FROM pending_feedback WHERE prompt_msg_id = ?",
            (prompt_msg_id,),
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
