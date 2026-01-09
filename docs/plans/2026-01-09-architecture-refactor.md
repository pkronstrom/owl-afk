# pyafk Architecture Refactoring Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor pyafk to publication-quality code: modular, DRY, readable, and extensible.

**Architecture:** Extract god objects (poller.py 2215 lines, cli.py 1479 lines) into focused modules. Consolidate duplicate code. Add proper abstractions and custom exceptions. Use handler dispatch pattern for callbacks.

**Tech Stack:** Python 3.10+, asyncio, aiosqlite, httpx, questionary, rich

---

## Phase 1: DRY Consolidation (Foundation)

### Task 1.1: Consolidate escape_html

**Files:**
- Modify: `src/pyafk/notifiers/telegram.py:70-72` (remove duplicate)
- Modify: `src/pyafk/notifiers/telegram.py` (update imports)

**Step 1: Update telegram.py imports**

Add the import at the top of the file:

```python
from pyafk.utils.formatting import escape_html
```

**Step 2: Remove duplicate _escape_html function**

Delete lines 70-72:

```python
# DELETE THIS:
def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
```

**Step 3: Replace all _escape_html calls with escape_html**

Find and replace all occurrences of `_escape_html(` with `escape_html(` in telegram.py.

**Step 4: Run tests**

Run: `pytest tests/test_telegram.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pyafk/notifiers/telegram.py
git commit -m "refactor: consolidate escape_html to single source"
```

---

### Task 1.2: Consolidate format_project_id usage

**Files:**
- Modify: `src/pyafk/notifiers/telegram.py:48-53` (use existing function)

**Step 1: Add import**

Add to imports in telegram.py:

```python
from pyafk.utils.formatting import format_project_id
```

**Step 2: Replace inline implementation**

In `format_approval_message()`, replace lines 48-53:

```python
# REPLACE THIS:
    if project_path:
        # Show last 2 path components for context
        parts = project_path.rstrip("/").split("/")
        project_id = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    else:
        project_id = session_id[:8]

# WITH THIS:
    project_id = format_project_id(project_path, session_id)
```

**Step 3: Find and replace other inline usages**

Search telegram.py for other places that duplicate format_project_id logic (lines 521-525, 607-612, 742-746, 868-872) and replace with the imported function.

**Step 4: Run tests**

Run: `pytest tests/ -v -k telegram`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pyafk/notifiers/telegram.py
git commit -m "refactor: use format_project_id from utils.formatting"
```

---

### Task 1.3: Create async storage context manager helper

**Files:**
- Create: `src/pyafk/utils/storage_helpers.py`
- Test: `tests/test_storage_helpers.py`

**Step 1: Write the failing test**

```python
# tests/test_storage_helpers.py
import pytest
from pathlib import Path
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

    async def failing_operation(storage: Storage) -> None:
        raise ValueError("test error")

    with pytest.raises(ValueError):
        await with_storage(tmp_path, failing_operation)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage_helpers.py -v`
Expected: FAIL with "No module named 'pyafk.utils.storage_helpers'"

**Step 3: Write minimal implementation**

```python
# src/pyafk/utils/storage_helpers.py
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage_helpers.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pyafk/utils/storage_helpers.py tests/test_storage_helpers.py
git commit -m "feat: add with_storage helper for managed connections"
```

---

### Task 1.4: Refactor cli.py to use with_storage

**Files:**
- Modify: `src/pyafk/cli.py:670-724`

**Step 1: Add import**

```python
from pyafk.utils.storage_helpers import with_storage
```

**Step 2: Refactor _get_rules**

Replace lines 670-686:

```python
def _get_rules(pyafk_dir):
    """Get all rules from database."""
    from pyafk.core.rules import RulesEngine

    async def operation(storage):
        engine = RulesEngine(storage)
        return await engine.list_rules()

    return asyncio.run(with_storage(pyafk_dir, operation))
```

**Step 3: Refactor _add_rule**

Replace lines 689-705:

```python
def _add_rule(pyafk_dir, pattern, action):
    """Add a rule to database."""
    from pyafk.core.rules import RulesEngine

    async def operation(storage):
        engine = RulesEngine(storage)
        return await engine.add_rule(pattern, action, 0, created_via="cli")

    return asyncio.run(with_storage(pyafk_dir, operation))
```

**Step 4: Refactor _remove_rule**

Replace lines 708-724:

```python
def _remove_rule(pyafk_dir, rule_id):
    """Remove a rule from database."""
    from pyafk.core.rules import RulesEngine

    async def operation(storage):
        engine = RulesEngine(storage)
        return await engine.remove_rule(rule_id)

    return asyncio.run(with_storage(pyafk_dir, operation))
```

**Step 5: Run tests**

Run: `pytest tests/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/pyafk/cli.py
git commit -m "refactor: use with_storage helper in CLI"
```

---

### Task 1.5: Create custom exceptions module

**Files:**
- Create: `src/pyafk/utils/exceptions.py`
- Test: `tests/test_exceptions.py`

**Step 1: Write the failing test**

```python
# tests/test_exceptions.py
"""Tests for custom exceptions."""

import pytest
from pyafk.utils.exceptions import (
    PyafkError,
    StorageError,
    TelegramAPIError,
    ChainApprovalError,
    ConfigurationError,
)


def test_pyafk_error_is_base():
    """Test PyafkError is base exception."""
    assert issubclass(StorageError, PyafkError)
    assert issubclass(TelegramAPIError, PyafkError)
    assert issubclass(ChainApprovalError, PyafkError)
    assert issubclass(ConfigurationError, PyafkError)


def test_exceptions_with_message():
    """Test exceptions can carry messages."""
    err = StorageError("database locked")
    assert str(err) == "database locked"

    err = TelegramAPIError("rate limited", error_code=429)
    assert "rate limited" in str(err)


def test_telegram_error_has_code():
    """Test TelegramAPIError can carry error code."""
    err = TelegramAPIError("forbidden", error_code=403)
    assert err.error_code == 403
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_exceptions.py -v`
Expected: FAIL with "No module named 'pyafk.utils.exceptions'"

**Step 3: Write minimal implementation**

```python
# src/pyafk/utils/exceptions.py
"""Custom exceptions for pyafk."""

from typing import Optional


class PyafkError(Exception):
    """Base exception for all pyafk errors."""
    pass


class StorageError(PyafkError):
    """Database/storage related errors."""
    pass


class TelegramAPIError(PyafkError):
    """Telegram Bot API errors."""

    def __init__(self, message: str, error_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code


class ChainApprovalError(PyafkError):
    """Chain approval flow errors."""
    pass


class ConfigurationError(PyafkError):
    """Configuration related errors."""
    pass


class RuleMatchError(PyafkError):
    """Rule pattern matching errors."""
    pass
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_exceptions.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pyafk/utils/exceptions.py tests/test_exceptions.py
git commit -m "feat: add custom exception types"
```

---

## Phase 2: Extract Callback Handlers from poller.py

### Task 2.1: Create handler protocol and context

**Files:**
- Create: `src/pyafk/core/handlers/__init__.py`
- Create: `src/pyafk/core/handlers/base.py`
- Test: `tests/core/handlers/test_base.py`

**Step 1: Create directory structure**

```bash
mkdir -p src/pyafk/core/handlers
mkdir -p tests/core/handlers
touch tests/core/__init__.py
touch tests/core/handlers/__init__.py
```

**Step 2: Write the failing test**

```python
# tests/core/handlers/test_base.py
"""Tests for handler base classes."""

import pytest
from dataclasses import dataclass
from pyafk.core.handlers.base import CallbackContext, CallbackHandler


def test_callback_context_has_required_fields():
    """Test CallbackContext has all required fields."""
    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=None,  # Would be Storage in real use
        notifier=None,  # Would be TelegramNotifier in real use
        original_text="test message",
    )
    assert ctx.target_id == "req123"
    assert ctx.callback_id == "cb456"
    assert ctx.message_id == 789


def test_callback_handler_protocol():
    """Test CallbackHandler protocol can be implemented."""
    class TestHandler(CallbackHandler):
        async def handle(self, ctx: CallbackContext) -> None:
            pass

    handler = TestHandler()
    assert hasattr(handler, "handle")
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/core/handlers/test_base.py -v`
Expected: FAIL with "No module named 'pyafk.core.handlers'"

**Step 4: Write minimal implementation**

```python
# src/pyafk/core/handlers/__init__.py
"""Callback handlers for Telegram interactions."""

from pyafk.core.handlers.base import CallbackContext, CallbackHandler

__all__ = ["CallbackContext", "CallbackHandler"]
```

```python
# src/pyafk/core/handlers/base.py
"""Base classes for callback handlers."""

from dataclasses import dataclass
from typing import Any, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pyafk.core.storage import Storage
    from pyafk.notifiers.telegram import TelegramNotifier


@dataclass
class CallbackContext:
    """Context passed to callback handlers.

    Attributes:
        target_id: The target identifier from callback data (request_id, session_id, etc.)
        callback_id: Telegram callback query ID for answering
        message_id: Telegram message ID for editing
        storage: Database storage instance
        notifier: Telegram notifier for sending messages
        original_text: Original message text (for restoration)
    """
    target_id: str
    callback_id: str
    message_id: Optional[int]
    storage: "Storage"
    notifier: "TelegramNotifier"
    original_text: str = ""


class CallbackHandler(Protocol):
    """Protocol for callback handlers.

    Implementations handle specific callback actions (approve, deny, add_rule, etc.)
    """

    async def handle(self, ctx: CallbackContext) -> None:
        """Handle the callback.

        Args:
            ctx: Callback context with all necessary dependencies
        """
        ...
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/core/handlers/test_base.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/pyafk/core/handlers/ tests/core/
git commit -m "feat: add callback handler protocol and context"
```

---

### Task 2.2: Extract ApproveHandler and DenyHandler

**Files:**
- Create: `src/pyafk/core/handlers/approval.py`
- Test: `tests/core/handlers/test_approval.py`

**Step 1: Write the failing test**

```python
# tests/core/handlers/test_approval.py
"""Tests for approval handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pyafk.core.handlers.base import CallbackContext
from pyafk.core.handlers.approval import ApproveHandler, DenyHandler


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.get_request = AsyncMock()
    storage.resolve_request = AsyncMock()
    storage.get_session = AsyncMock()
    storage.log_audit = AsyncMock()
    return storage


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    notifier.answer_callback = AsyncMock()
    notifier.edit_message = AsyncMock()
    return notifier


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.id = "req123"
    request.session_id = "sess456"
    request.tool_name = "Bash"
    request.tool_input = '{"command": "git status"}'
    request.telegram_msg_id = 789
    return request


@pytest.mark.asyncio
async def test_approve_handler_resolves_request(mock_storage, mock_notifier, mock_request):
    """Test ApproveHandler resolves request as approved."""
    mock_storage.get_request.return_value = mock_request
    mock_storage.get_session.return_value = MagicMock(project_path="/test/project")

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = ApproveHandler()
    await handler.handle(ctx)

    mock_storage.resolve_request.assert_called_once()
    call_kwargs = mock_storage.resolve_request.call_args.kwargs
    assert call_kwargs["request_id"] == "req123"
    assert call_kwargs["status"] == "approved"


@pytest.mark.asyncio
async def test_deny_handler_resolves_request(mock_storage, mock_notifier, mock_request):
    """Test DenyHandler resolves request as denied."""
    mock_storage.get_request.return_value = mock_request
    mock_storage.get_session.return_value = MagicMock(project_path="/test/project")

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = DenyHandler()
    await handler.handle(ctx)

    mock_storage.resolve_request.assert_called_once()
    call_kwargs = mock_storage.resolve_request.call_args.kwargs
    assert call_kwargs["status"] == "denied"


@pytest.mark.asyncio
async def test_approve_handler_handles_missing_request(mock_storage, mock_notifier):
    """Test ApproveHandler handles missing request gracefully."""
    mock_storage.get_request.return_value = None

    ctx = CallbackContext(
        target_id="req123",
        callback_id="cb456",
        message_id=789,
        storage=mock_storage,
        notifier=mock_notifier,
    )

    handler = ApproveHandler()
    await handler.handle(ctx)  # Should not raise

    mock_notifier.edit_message.assert_called()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/handlers/test_approval.py -v`
Expected: FAIL with "No module named 'pyafk.core.handlers.approval'"

**Step 3: Write minimal implementation**

```python
# src/pyafk/core/handlers/approval.py
"""Approval and denial handlers."""

from typing import Optional

from pyafk.core.handlers.base import CallbackContext, CallbackHandler
from pyafk.utils.debug import debug_callback
from pyafk.utils.formatting import escape_html, format_project_id


def _format_tool_summary(tool_name: str, tool_input: Optional[str]) -> str:
    """Format tool input for display."""
    import json

    if not tool_input:
        return ""

    try:
        data = json.loads(tool_input)
    except (json.JSONDecodeError, TypeError):
        return str(tool_input)[:100]

    summary: str
    if "command" in data:
        summary = str(data["command"])
    elif "file_path" in data:
        summary = str(data["file_path"])
    elif "path" in data:
        summary = str(data["path"])
    elif "url" in data:
        summary = str(data["url"])
    else:
        summary = json.dumps(data)

    if len(summary) > 100:
        summary = summary[:100] + "..."

    return escape_html(summary)


class ApproveHandler:
    """Handle approve callback."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Approve the request."""
        try:
            debug_callback(
                "ApproveHandler called", request_id=ctx.target_id
            )
            request = await ctx.storage.get_request(ctx.target_id)
            if not request:
                debug_callback("Request not found", request_id=ctx.target_id)
                await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
                if ctx.message_id:
                    await ctx.notifier.edit_message(ctx.message_id, "Request expired")
                return

            await ctx.storage.resolve_request(
                request_id=ctx.target_id,
                status="approved",
                resolved_by="user",
            )

            await ctx.notifier.answer_callback(ctx.callback_id, "Approved")

            if ctx.message_id:
                session = await ctx.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                tool_summary = _format_tool_summary(
                    request.tool_name, request.tool_input
                )
                await ctx.notifier.edit_message(
                    ctx.message_id,
                    f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>",
                )

            await ctx.storage.log_audit(
                event_type="response",
                session_id=request.session_id,
                details={
                    "request_id": ctx.target_id,
                    "action": "approve",
                    "resolved_by": "user",
                },
            )
        except Exception as e:
            debug_callback(
                "Error in ApproveHandler", error=str(e)[:100], request_id=ctx.target_id
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")


class DenyHandler:
    """Handle deny callback."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Deny the request."""
        try:
            debug_callback("DenyHandler called", request_id=ctx.target_id)
            request = await ctx.storage.get_request(ctx.target_id)
            if not request:
                debug_callback("Request not found", request_id=ctx.target_id)
                await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
                if ctx.message_id:
                    await ctx.notifier.edit_message(ctx.message_id, "Request expired")
                return

            await ctx.storage.resolve_request(
                request_id=ctx.target_id,
                status="denied",
                resolved_by="user",
            )

            await ctx.notifier.answer_callback(ctx.callback_id, "Denied")

            if ctx.message_id:
                session = await ctx.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                tool_summary = _format_tool_summary(
                    request.tool_name, request.tool_input
                )
                await ctx.notifier.edit_message(
                    ctx.message_id,
                    f"<i>{project_id}</i>\n❌ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>",
                )

            await ctx.storage.log_audit(
                event_type="response",
                session_id=request.session_id,
                details={
                    "request_id": ctx.target_id,
                    "action": "deny",
                    "resolved_by": "user",
                },
            )
        except Exception as e:
            debug_callback(
                "Error in DenyHandler", error=str(e)[:100], request_id=ctx.target_id
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/handlers/test_approval.py -v`
Expected: PASS

**Step 5: Update handlers __init__.py**

```python
# src/pyafk/core/handlers/__init__.py
"""Callback handlers for Telegram interactions."""

from pyafk.core.handlers.base import CallbackContext, CallbackHandler
from pyafk.core.handlers.approval import ApproveHandler, DenyHandler

__all__ = [
    "CallbackContext",
    "CallbackHandler",
    "ApproveHandler",
    "DenyHandler",
]
```

**Step 6: Commit**

```bash
git add src/pyafk/core/handlers/ tests/core/handlers/
git commit -m "feat: extract ApproveHandler and DenyHandler from poller"
```

---

### Task 2.3: Create handler dispatcher

**Files:**
- Create: `src/pyafk/core/handlers/dispatcher.py`
- Test: `tests/core/handlers/test_dispatcher.py`

**Step 1: Write the failing test**

```python
# tests/core/handlers/test_dispatcher.py
"""Tests for handler dispatcher."""

import pytest
from unittest.mock import AsyncMock
from pyafk.core.handlers.dispatcher import HandlerDispatcher
from pyafk.core.handlers.base import CallbackContext


@pytest.fixture
def mock_storage():
    return AsyncMock()


@pytest.fixture
def mock_notifier():
    return AsyncMock()


@pytest.mark.asyncio
async def test_dispatcher_routes_approve(mock_storage, mock_notifier):
    """Test dispatcher routes approve action correctly."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    # Mock the handler
    mock_handler = AsyncMock()
    dispatcher._handlers["approve"] = mock_handler

    await dispatcher.dispatch("approve:req123", "cb456", 789, "original text")

    mock_handler.handle.assert_called_once()
    ctx = mock_handler.handle.call_args[0][0]
    assert ctx.target_id == "req123"


@pytest.mark.asyncio
async def test_dispatcher_handles_unknown_action(mock_storage, mock_notifier):
    """Test dispatcher handles unknown actions gracefully."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    # Should not raise
    await dispatcher.dispatch("unknown_action:req123", "cb456", 789, "")


@pytest.mark.asyncio
async def test_dispatcher_parses_compound_target(mock_storage, mock_notifier):
    """Test dispatcher parses compound target IDs like session_id:tool_name."""
    dispatcher = HandlerDispatcher(mock_storage, mock_notifier)

    mock_handler = AsyncMock()
    dispatcher._handlers["approve_all"] = mock_handler

    await dispatcher.dispatch("approve_all:sess123:Bash", "cb456", 789, "")

    ctx = mock_handler.handle.call_args[0][0]
    assert ctx.target_id == "sess123:Bash"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/handlers/test_dispatcher.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# src/pyafk/core/handlers/dispatcher.py
"""Handler dispatcher for routing callbacks to appropriate handlers."""

from typing import Dict, Optional, TYPE_CHECKING

from pyafk.core.handlers.base import CallbackContext, CallbackHandler
from pyafk.core.handlers.approval import ApproveHandler, DenyHandler
from pyafk.utils.debug import debug_callback

if TYPE_CHECKING:
    from pyafk.core.storage import Storage
    from pyafk.notifiers.telegram import TelegramNotifier


class HandlerDispatcher:
    """Routes callback data to appropriate handlers.

    Replaces the large if-elif chain in poller.py with a dispatch table.
    """

    def __init__(
        self,
        storage: "Storage",
        notifier: "TelegramNotifier",
    ) -> None:
        self.storage = storage
        self.notifier = notifier

        # Register handlers
        self._handlers: Dict[str, CallbackHandler] = {
            "approve": ApproveHandler(),
            "deny": DenyHandler(),
            # More handlers will be added in subsequent tasks
        }

    async def dispatch(
        self,
        callback_data: str,
        callback_id: str,
        message_id: Optional[int],
        original_text: str = "",
    ) -> None:
        """Dispatch callback to appropriate handler.

        Args:
            callback_data: The callback_data from Telegram button (e.g., "approve:req123")
            callback_id: Telegram callback query ID
            message_id: Telegram message ID
            original_text: Original message text for restoration
        """
        if ":" not in callback_data:
            debug_callback("Invalid callback data format", data=callback_data)
            return

        action, target_id = callback_data.split(":", 1)
        debug_callback("Dispatching callback", action=action, target_id=target_id[:20])

        handler = self._handlers.get(action)
        if handler is None:
            debug_callback("No handler for action", action=action)
            return

        ctx = CallbackContext(
            target_id=target_id,
            callback_id=callback_id,
            message_id=message_id,
            storage=self.storage,
            notifier=self.notifier,
            original_text=original_text,
        )

        await handler.handle(ctx)

    def register(self, action: str, handler: CallbackHandler) -> None:
        """Register a handler for an action.

        Args:
            action: The action string (e.g., "approve", "deny", "add_rule")
            handler: Handler instance
        """
        self._handlers[action] = handler
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/handlers/test_dispatcher.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pyafk/core/handlers/dispatcher.py tests/core/handlers/test_dispatcher.py
git commit -m "feat: add handler dispatcher for callback routing"
```

---

### Task 2.4: Extract remaining handlers (rules, subagent, stop, chain)

This is a larger task. For each handler type, follow the same pattern:

1. Create handler file: `src/pyafk/core/handlers/{type}.py`
2. Write tests: `tests/core/handlers/test_{type}.py`
3. Extract logic from poller.py
4. Register in dispatcher
5. Commit

**Handler files to create:**

| File | Handlers | Lines from poller.py |
|------|----------|---------------------|
| `rules.py` | `AddRuleMenuHandler`, `AddRuleHandler`, `CancelRuleHandler` | 890-1027 |
| `subagent.py` | `SubagentOkHandler`, `SubagentContinueHandler` | 1029-1089 |
| `stop.py` | `StopOkHandler`, `StopCommentHandler` | 1090-1141 |
| `chain.py` | `ChainApproveHandler`, `ChainDenyHandler`, `ChainApproveEntireHandler`, etc. | 1142-1852 |

**Each handler extraction follows the same pattern as Task 2.2. Detailed implementation omitted for brevity but should:**

1. Copy the handler method body from poller.py
2. Adapt to use `ctx` instead of individual parameters
3. Add proper error handling
4. Write tests

---

### Task 2.5: Integrate dispatcher into poller.py

**Files:**
- Modify: `src/pyafk/core/poller.py`

**Step 1: Add imports**

```python
from pyafk.core.handlers.dispatcher import HandlerDispatcher
```

**Step 2: Initialize dispatcher in __init__**

```python
def __init__(self, storage, notifier, pyafk_dir):
    # ... existing code ...
    self._dispatcher = HandlerDispatcher(storage, notifier)
```

**Step 3: Replace _handle_callback**

Replace the giant if-elif chain with:

```python
async def _handle_callback(self, callback: dict) -> None:
    """Handle a callback query from inline button."""
    callback_id = callback["id"]
    data = callback.get("data", "")
    message_id = callback.get("message", {}).get("message_id")
    original_text = callback.get("message", {}).get("text", "")

    debug_callback("Received callback", data=data, message_id=message_id)

    # Answer callback immediately to prevent timeout
    try:
        await self.notifier.answer_callback(callback_id, "")
    except Exception:
        pass

    # Dispatch to handler
    await self._dispatcher.dispatch(data, callback_id, message_id, original_text)
```

**Step 4: Run all tests**

Run: `pytest tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pyafk/core/poller.py
git commit -m "refactor: integrate handler dispatcher into poller"
```

---

## Phase 3: Extract Chain Logic

### Task 3.1: Create ChainApprovalManager

**Files:**
- Create: `src/pyafk/core/chain.py`
- Test: `tests/core/test_chain.py`

This extracts:
- `_chain_state_key()` (lines 1854-1863)
- `_get_chain_state()` (lines 1865-1883)
- `_save_chain_state()` (lines 1885-1905)
- `_clear_chain_state()` (lines 1907-1910)
- `_check_chain_rules()` (lines 2058-2105)
- `_format_chain_approved_message()` (lines 2107-2122)

**Implementation pattern follows Tasks 2.1-2.2**

---

## Phase 4: Split cli.py

### Task 4.1: Create cli/commands.py

**Files:**
- Create: `src/pyafk/cli/__init__.py`
- Create: `src/pyafk/cli/commands.py`
- Move: Command handlers from cli.py lines 1003-1343

### Task 4.2: Create cli/interactive.py

**Files:**
- Create: `src/pyafk/cli/interactive.py`
- Move: Interactive menu functions from cli.py lines 84-656

### Task 4.3: Create cli/install.py

**Files:**
- Create: `src/pyafk/cli/install.py`
- Move: Installation functions from cli.py lines 754-996

### Task 4.4: Refactor cli.py as entry point

**Files:**
- Modify: `src/pyafk/cli.py` → thin wrapper importing from cli/

---

## Phase 5: Fix Notifier Abstraction

### Task 5.1: Separate Telegram-specific interface

**Files:**
- Modify: `src/pyafk/notifiers/base.py`
- Modify: `src/pyafk/notifiers/telegram.py`

Create a clean base interface and a separate TelegramSpecific protocol for chain/subagent methods.

---

## Phase 6: Cleanup & Polish

### Task 6.1: Add __all__ exports

Add `__all__` to all `__init__.py` files.

### Task 6.2: Remove global state from debug.py

Pass config explicitly instead of using global singleton.

### Task 6.3: Consistent error handling

Replace silent `except: pass` with proper logging.

### Task 6.4: Type hint coverage

Add type hints to remaining functions.

---

## Summary

| Phase | Tasks | Estimated Commits |
|-------|-------|-------------------|
| **Phase 1**: DRY Consolidation | 5 | 5 |
| **Phase 2**: Extract Handlers | 5 | 6-10 |
| **Phase 3**: Extract Chain Logic | 1 | 2 |
| **Phase 4**: Split CLI | 4 | 4 |
| **Phase 5**: Fix Notifier | 1 | 2 |
| **Phase 6**: Cleanup | 4 | 4 |
| **Total** | ~20 | ~25-30 |

Each phase is independent and can be merged separately. Run `pytest` after each task to ensure nothing breaks.
