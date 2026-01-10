# Code Audit: pyafk

**Date**: 2026-01-10
**Scope**: Whole codebase
**Health Score**: Needs Work

## Executive Summary

pyafk is a well-structured remote approval system with clear separation of concerns. However, the codebase has accumulated technical debt primarily in error handling (15+ swallowed exceptions, 12+ broad except blocks), code duplication (tool formatting logic in 3 places), and some long functions that do too much. Quick wins are available by consolidating duplicated code and improving exception specificity.

## Findings by Category

### Dead Code

**Minimal issues found.** The codebase is relatively clean of dead code.

- Some unused imports may exist but are minor
- No significant orphaned files or unreachable code paths detected

### Code Smells

#### Long Functions
- `request_approval()` in `manager.py` (~135 lines) - handles too many concerns: validation, deduplication, notification, polling orchestration
- `handle_hook()` in `hooks/handler.py` - complex conditional logic for different hook types
- `_handle_callback()` in `poller.py` - large switch-like structure for callback routing

#### Magic Numbers/Strings
- Hardcoded timeouts: `30` seconds in multiple places (httpx, polling)
- Hardcoded retry counts: `3` retries scattered across files
- Hardcoded message prefixes/formats throughout handlers
- Database path `"pyafk.db"` hardcoded in multiple locations

#### Deep Nesting
- `ChainApproveEntireHandler.handle()` has 4+ levels of nesting
- Several try/except blocks with nested conditionals

### DRY Violations

#### Tool Formatting (3 locations)
The same logic for formatting tool calls/summaries exists in:
1. `src/pyafk/core/handlers/approval.py` - `_format_tool_summary()`
2. `src/pyafk/core/handlers/chain.py` - `_format_tool_call()`
3. `src/pyafk/notifiers/telegram.py` - similar formatting logic

These should be consolidated into `utils/formatting.py`.

#### Message Construction
Telegram message formatting patterns are duplicated across:
- `ApproveHandler` and `DenyHandler` (identical structure)
- All chain handlers (similar patterns)
- `TelegramNotifier.send_approval_request()`

#### Storage Patterns
Similar get-then-check patterns repeated:
```python
request = await storage.get_request(id)
if not request:
    # handle missing
    return
```
This pattern appears 10+ times across handlers.

### Coupling & Modularity

#### Tight Coupling in Dispatcher
`CallbackDispatcher` in `chain.py` directly instantiates all handler classes. Consider:
- Handler registry pattern
- Dependency injection for handlers

#### Storage Dependency Threading
Many components take `pyafk_dir` and construct their own Storage instances. A single shared storage instance or factory would be cleaner.

#### Handler Context
`CallbackContext` is well-designed but handlers still reach into `ctx.storage` and `ctx.notifier` directly rather than through defined interfaces.

### Clarity & Maintainability

#### Inconsistent Naming
- `target_id` vs `request_id` - both used for the same concept
- `msg_id` vs `message_id` - inconsistent across codebase
- `telegram_msg_id` (stored) vs `message_id` (parameter)

#### Missing Type Hints
- Several utility functions lack return type hints
- Some async functions don't annotate `-> None`

#### Complex Conditionals
```python
if request.status != "pending":
    # handle
    return
```
This idempotency check is repeated but could be a decorator or base class method.

### Error Handling

#### Swallowed Exceptions (15+ instances)
```python
except Exception:
    pass  # Silent failure
```
Found in:
- `cmd_off()` - message editing failures
- `TelegramNotifier._api_request()` - JSON decode failures
- `poller.py` - callback handling
- Multiple handlers - error recovery paths

#### Broad Exception Handling (12+ instances)
```python
except Exception as e:
    # Generic handling
```
Should be specific exceptions:
- `json.JSONDecodeError` for JSON parsing
- `httpx.TimeoutException` for HTTP timeouts
- `aiosqlite.Error` for database operations

#### Missing Error Propagation
Handlers catch exceptions and answer callbacks but don't propagate errors for monitoring/alerting.

## Priority Matrix

| Category | Severity | Effort | Recommended Action |
|----------|----------|--------|-------------------|
| Swallowed exceptions | High | Small | Add logging before pass statements |
| Broad except blocks | High | Medium | Specify exception types |
| Tool format duplication | Medium | Small | Consolidate to utils/formatting.py |
| Long functions | Medium | Medium | Extract sub-functions |
| Magic numbers | Low | Small | Define constants |
| Handler coupling | Low | Large | Refactor to registry pattern |
| Naming inconsistency | Low | Medium | Standardize on request_id, message_id |

## Recommended Cleanup Plan

### Phase 1: Quick Wins (Low effort, high impact)

1. **Consolidate tool formatting** - Move all `_format_tool_*` functions to `utils/formatting.py`
   - Files: `approval.py`, `chain.py`, `telegram.py`
   - Create: `utils/formatting.py` (add to existing)

2. **Add logging to swallowed exceptions** - Every `except: pass` should at least log
   - Files: `commands.py`, `telegram.py`, `poller.py`

3. **Define constants for magic numbers**
   - Create: `utils/constants.py`
   - Values: `DEFAULT_TIMEOUT = 30`, `MAX_RETRIES = 3`, `DB_NAME = "pyafk.db"`

### Phase 2: Core Improvements

4. **Specify exception types** - Replace `except Exception` with specific types
   - Add proper exception hierarchy in `utils/exceptions.py`
   - Update all handlers to catch specific exceptions

5. **Extract idempotency check** - Create decorator or base class method
   ```python
   @ensure_pending
   async def handle(self, ctx):
       # handler logic
   ```

6. **Refactor request_approval()** - Split into:
   - `_validate_request()`
   - `_check_deduplication()`
   - `_send_notification()`
   - `_orchestrate_polling()`

7. **Standardize naming** - Rename throughout codebase:
   - `target_id` → `request_id`
   - `msg_id` → `message_id`

### Phase 3: Architectural Changes

8. **Handler registry pattern** - Replace direct instantiation in dispatcher
   ```python
   class HandlerRegistry:
       _handlers: dict[str, Type[Handler]] = {}

       @classmethod
       def register(cls, action: str):
           def decorator(handler_cls):
               cls._handlers[action] = handler_cls
               return handler_cls
           return decorator
   ```

9. **Storage factory** - Single point of storage creation
   ```python
   class StorageFactory:
       @classmethod
       async def create(cls, pyafk_dir: Path) -> Storage:
           storage = Storage(pyafk_dir / "pyafk.db")
           await storage.connect()
           return storage
   ```

10. **Message builder pattern** - Consolidate Telegram message construction
    ```python
    class TelegramMessageBuilder:
        def approval_message(self, request, session) -> str: ...
        def resolved_message(self, request, status) -> str: ...
    ```

---

## Implementation Document for Implementation Agent

### Overview

This document provides actionable tasks for cleaning up the pyafk codebase. Execute phases in order. Each task is independent within its phase.

### Pre-requisites

- Run `pytest` to ensure all tests pass before starting
- Create a feature branch: `git checkout -b refactor/code-audit-cleanup`

### Phase 1 Tasks

#### Task 1.1: Consolidate Tool Formatting

**Files to modify:**
- `src/pyafk/utils/formatting.py` (add functions)
- `src/pyafk/core/handlers/approval.py` (remove `_format_tool_summary`, import from utils)
- `src/pyafk/core/handlers/chain.py` (remove `_format_tool_call`, import from utils)

**Implementation:**
1. Add to `utils/formatting.py`:
```python
def format_tool_summary(tool_name: str, tool_input: Optional[str]) -> str:
    """Format tool input for display in Telegram messages."""
    if not tool_input:
        return ""
    try:
        data = json.loads(tool_input)
    except (json.JSONDecodeError, TypeError):
        return escape_html(str(tool_input)[:100])

    # Extract most relevant field
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

def format_tool_call(tool_name: str, tool_input: Optional[str]) -> str:
    """Format tool call for display."""
    summary = format_tool_summary(tool_name, tool_input)
    return f"[{tool_name}] {summary}" if summary else f"[{tool_name}]"
```

2. Update imports in `approval.py` and `chain.py`
3. Remove duplicate functions
4. Run tests: `pytest tests/core/handlers/`

#### Task 1.2: Add Logging to Swallowed Exceptions

**Files to modify:**
- `src/pyafk/cli/commands.py`
- `src/pyafk/notifiers/telegram.py`

**Pattern to apply:**
```python
# Before
except Exception:
    pass

# After
except Exception as e:
    logger.debug(f"Ignored error: {e}")
```

**Specific locations:**
- `cmd_off()` lines ~114, ~131 - message editing failures
- `TelegramNotifier._api_request()` - JSON decode in error path

#### Task 1.3: Define Constants

**Create:** `src/pyafk/utils/constants.py`

```python
"""Application constants."""

# Timeouts (seconds)
DEFAULT_HTTP_TIMEOUT = 30
POLL_TIMEOUT = 30
CALLBACK_ANSWER_TIMEOUT = 10

# Retries
MAX_API_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0

# Database
DB_FILENAME = "pyafk.db"

# Message limits
MAX_TOOL_SUMMARY_LENGTH = 100
MAX_MESSAGE_LENGTH = 4096
```

**Update files to use constants:**
- `telegram.py` - timeouts
- `storage.py` - DB filename
- `approval.py`, `chain.py` - summary length

### Phase 2 Tasks

#### Task 2.1: Specify Exception Types

**Create:** `src/pyafk/utils/exceptions.py`

```python
"""Custom exceptions for pyafk."""

class PyafkError(Exception):
    """Base exception for pyafk."""
    pass

class StorageError(PyafkError):
    """Database operation failed."""
    pass

class NotifierError(PyafkError):
    """Notification delivery failed."""
    pass

class TelegramAPIError(NotifierError):
    """Telegram API returned an error."""
    def __init__(self, message: str, error_code: int = None):
        super().__init__(message)
        self.error_code = error_code

class ConfigurationError(PyafkError):
    """Configuration is invalid or missing."""
    pass
```

**Update handlers to use specific exceptions.**

#### Task 2.2: Extract Idempotency Check

**Add to:** `src/pyafk/core/handlers/base.py`

```python
from functools import wraps

def ensure_pending(handler_method):
    """Decorator to skip if request already resolved."""
    @wraps(handler_method)
    async def wrapper(self, ctx: CallbackContext):
        request = await ctx.storage.get_request(ctx.target_id)
        if not request:
            await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
            if ctx.message_id:
                await ctx.notifier.edit_message(ctx.message_id, "Request expired")
            return

        if request.status != "pending":
            await ctx.notifier.answer_callback(ctx.callback_id, "Already processed")
            return

        # Attach request to context for handler use
        ctx.request = request
        return await handler_method(self, ctx)
    return wrapper
```

**Update handlers to use decorator.**

#### Task 2.3: Refactor request_approval()

**File:** `src/pyafk/core/manager.py`

Split into helper methods:
1. `_validate_approval_input()` - Check required fields
2. `_check_deduplication()` - Fingerprint check
3. `_create_and_notify()` - Storage + notification
4. `_run_polling()` - Polling orchestration

Keep `request_approval()` as orchestrator calling these methods.

### Phase 3 Tasks

#### Task 3.1: Handler Registry

**File:** `src/pyafk/core/handlers/registry.py`

```python
"""Handler registry for callback dispatching."""

from typing import Type, Dict
from pyafk.core.handlers.base import Handler

class HandlerRegistry:
    """Registry for callback handlers."""

    _handlers: Dict[str, Type[Handler]] = {}

    @classmethod
    def register(cls, action: str):
        """Decorator to register a handler for an action."""
        def decorator(handler_cls: Type[Handler]):
            cls._handlers[action] = handler_cls
            return handler_cls
        return decorator

    @classmethod
    def get(cls, action: str) -> Type[Handler] | None:
        """Get handler class for action."""
        return cls._handlers.get(action)

    @classmethod
    def create(cls, action: str) -> Handler | None:
        """Create handler instance for action."""
        handler_cls = cls.get(action)
        return handler_cls() if handler_cls else None
```

**Update handlers with decorator:**
```python
@HandlerRegistry.register("approve")
class ApproveHandler:
    ...
```

**Update dispatcher to use registry.**

### Verification

After each phase:
1. Run full test suite: `pytest`
2. Run type checker: `mypy src/pyafk/`
3. Manual test: `pyafk on`, trigger approval, verify flow

### Commit Strategy

- One commit per task: `refactor: consolidate tool formatting (audit 1.1)`
- Squash phase commits if desired before merge
