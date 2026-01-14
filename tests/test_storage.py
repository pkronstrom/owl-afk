"""Tests for SQLite storage layer."""

import pytest

from owl.core.storage import Storage, Request, Session, AuditEntry


@pytest.mark.asyncio
async def test_storage_creates_tables(mock_owl_dir):
    """Storage should create tables on init."""
    db_path = mock_owl_dir / "test.db"

    async with Storage(db_path) as storage:
        tables = await storage.list_tables()
        assert "requests" in tables
        assert "sessions" in tables
        assert "auto_approve_rules" in tables
        assert "audit_log" in tables


@pytest.mark.asyncio
async def test_storage_create_request(mock_owl_dir):
    """Storage should create and retrieve requests."""
    db_path = mock_owl_dir / "test.db"

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
async def test_storage_resolve_request(mock_owl_dir):
    """Storage should update request status."""
    db_path = mock_owl_dir / "test.db"

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
async def test_storage_pending_requests(mock_owl_dir):
    """Storage should list pending requests."""
    db_path = mock_owl_dir / "test.db"

    async with Storage(db_path) as storage:
        await storage.create_request(session_id="s1", tool_name="Bash", tool_input="{}")
        await storage.create_request(session_id="s2", tool_name="Edit", tool_input="{}")

        pending = await storage.get_pending_requests()
        assert len(pending) == 2


@pytest.mark.asyncio
async def test_storage_sessions(mock_owl_dir):
    """Storage should track sessions."""
    db_path = mock_owl_dir / "test.db"

    async with Storage(db_path) as storage:
        await storage.upsert_session(
            session_id="session-123",
            project_path="/home/user/project",
        )

        session = await storage.get_session("session-123")
        assert session.project_path == "/home/user/project"
        assert session.status == "active"


@pytest.mark.asyncio
async def test_storage_audit_log(mock_owl_dir):
    """Storage should append to audit log."""
    db_path = mock_owl_dir / "test.db"

    async with Storage(db_path) as storage:
        await storage.log_audit(
            event_type="request",
            session_id="session-123",
            details={"tool": "Bash"},
        )

        entries = await storage.get_audit_log(limit=10)
        assert len(entries) == 1
        assert entries[0].event_type == "request"
