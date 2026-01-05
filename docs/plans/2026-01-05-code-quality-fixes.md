# Code Quality Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix remaining code review issues: race condition, code duplication, type hints, error handling.

**Architecture:** Optimistic locking for chain state, extract helpers with notifier separation, full mypy-strict types, layered fail-safe error handling.

**Tech Stack:** Python 3.10+, aiosqlite, mypy, pytest

---

## Task 1: Add mypy configuration

**Files:**
- Modify: `pyproject.toml`
- Create: `src/pyafk/py.typed`

**Step 1: Add mypy to dev dependencies and config**

Edit `pyproject.toml`:
```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "mypy>=1.0.0",
]

[tool.mypy]
python_version = "3.10"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_configs = true
show_error_codes = true
files = ["src/pyafk"]
```

**Step 2: Create py.typed marker**

Create `src/pyafk/py.typed` (empty file):
```
```

**Step 3: Install mypy**

Run: `pip install mypy`

**Step 4: Commit**

```bash
git add pyproject.toml src/pyafk/py.typed
git commit -m "chore: add mypy configuration for strict type checking"
```

---

## Task 2: Add type hints to storage.py

**Files:**
- Modify: `src/pyafk/core/storage.py`

**Step 1: Add type hints to all methods**

Key changes:
- Import `from typing import Optional, Any`
- Add return types to all methods
- Add parameter types to all methods
- Type the `_conn` attribute properly

Example signatures:
```python
async def get_chain_state(self, msg_id: int) -> Optional[str]: ...
async def save_chain_state(self, msg_id: int, state_json: str) -> None: ...
async def get_rules_for_matching(self) -> list[tuple[str, str]]: ...
```

**Step 2: Run mypy to verify**

Run: `mypy src/pyafk/core/storage.py`
Expected: No errors

**Step 3: Commit**

```bash
git add src/pyafk/core/storage.py
git commit -m "chore: add type hints to storage.py"
```

---

## Task 3: Add type hints to rules.py

**Files:**
- Modify: `src/pyafk/core/rules.py`

**Step 1: Add type hints to all functions and methods**

Key changes:
```python
def matches_pattern(tool_call: str, pattern: str) -> bool: ...
def format_tool_call(tool_name: str, tool_input: Optional[str]) -> str: ...

class RulesEngine:
    def __init__(self, storage: Storage) -> None: ...
    async def check(self, tool_name: str, tool_input: Optional[str] = None) -> Optional[str]: ...
    async def add_rule(self, pattern: str, action: str = "approve", priority: int = 0, created_via: str = "cli") -> int: ...
    async def remove_rule(self, rule_id: int) -> bool: ...
    async def list_rules(self) -> list[dict[str, Any]]: ...
```

**Step 2: Run mypy to verify**

Run: `mypy src/pyafk/core/rules.py`
Expected: No errors

**Step 3: Commit**

```bash
git add src/pyafk/core/rules.py
git commit -m "chore: add type hints to rules.py"
```

---

## Task 4: Create formatting helpers module

**Files:**
- Create: `src/pyafk/utils/formatting.py`
- Modify: `src/pyafk/utils/__init__.py`

**Step 1: Create formatting.py with core helpers**

```python
"""Formatting utilities for pyafk."""

from typing import Optional


def format_project_id(project_path: Optional[str], session_id: str) -> str:
    """Format project path for display.

    Returns last 2 path components or short session ID.
    """
    if project_path:
        parts = project_path.rstrip("/").split("/")
        return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return session_id[:8]


def truncate_command(cmd: str, max_len: int = 60) -> str:
    """Truncate command for display."""
    if len(cmd) <= max_len:
        return cmd
    return cmd[:max_len - 3] + "..."


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
```

**Step 2: Update utils/__init__.py**

```python
"""Utilities for pyafk."""

from pyafk.utils.formatting import escape_html, format_project_id, truncate_command

__all__ = ["escape_html", "format_project_id", "truncate_command"]
```

**Step 3: Run mypy to verify**

Run: `mypy src/pyafk/utils/formatting.py`
Expected: No errors

**Step 4: Commit**

```bash
git add src/pyafk/utils/formatting.py src/pyafk/utils/__init__.py
git commit -m "feat: add formatting helpers module"
```

---

## Task 5: Add optimistic locking to chain state

**Files:**
- Modify: `src/pyafk/core/storage.py`

**Step 1: Update chain state methods with version support**

```python
async def get_chain_state(self, msg_id: int) -> Optional[tuple[str, int]]:
    """Get chain state JSON and version.

    Returns (state_json, version) or None.
    """
    cursor = await self._conn.execute(
        "SELECT request_id, created_at FROM pending_feedback WHERE prompt_msg_id = ?",
        (msg_id,),
    )
    row = await cursor.fetchone()
    if row:
        # Use created_at as version (it gets updated on each save)
        return (row["request_id"], int(row["created_at"] * 1000))
    return None

async def save_chain_state_atomic(
    self, msg_id: int, state_json: str, expected_version: int
) -> bool:
    """Save chain state atomically with version check.

    Returns True if saved, False if version mismatch (stale update).
    """
    new_version = int(time.time() * 1000)
    cursor = await self._conn.execute(
        """
        UPDATE pending_feedback
        SET request_id = ?, created_at = ?
        WHERE prompt_msg_id = ? AND CAST(created_at * 1000 AS INTEGER) = ?
        """,
        (state_json, new_version / 1000, msg_id, expected_version),
    )
    if cursor.rowcount == 0:
        # Either doesn't exist or version mismatch - try insert
        try:
            await self._conn.execute(
                """
                INSERT INTO pending_feedback (prompt_msg_id, request_id, created_at)
                VALUES (?, ?, ?)
                """,
                (msg_id, state_json, new_version / 1000),
            )
        except Exception:
            await self._conn.rollback()
            return False
    await self._conn.commit()
    return True
```

**Step 2: Run tests**

Run: `pytest tests/ -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/pyafk/core/storage.py
git commit -m "feat: add optimistic locking to chain state storage"
```

---

## Task 6: Update poller to use atomic chain state

**Files:**
- Modify: `src/pyafk/core/poller.py`

**Step 1: Update _get_chain_state to return version**

```python
async def _get_chain_state(self, request_id: str) -> Optional[tuple[dict, int]]:
    """Get chain state and version from storage."""
    msg_id = self._chain_state_key(request_id)
    result = await self.storage.get_chain_state(msg_id)
    if result:
        state_json, version = result
        try:
            return (json.loads(state_json), version)
        except (json.JSONDecodeError, TypeError):
            pass
    return None
```

**Step 2: Update _save_chain_state to use atomic save with retry**

```python
async def _save_chain_state(
    self, request_id: str, state: dict, version: int
) -> bool:
    """Save chain state atomically. Returns True if saved."""
    state_json = json.dumps(state)
    msg_id = self._chain_state_key(request_id)
    return await self.storage.save_chain_state_atomic(msg_id, state_json, version)
```

**Step 3: Update all chain handlers to use versioned operations**

Pattern for each handler:
```python
# Get state with version
result = await self._get_chain_state(request_id)
if not result:
    # Initialize new state
    state = {"commands": commands, "approved_indices": [], "version": 0}
    version = 0
else:
    state, version = result

# Modify state
state["approved_indices"].append(command_idx)

# Save with retry on conflict
if not await self._save_chain_state(request_id, state, version):
    # Conflict - re-read and retry once
    result = await self._get_chain_state(request_id)
    if result:
        state, version = result
        state["approved_indices"].append(command_idx)
        await self._save_chain_state(request_id, state, version)
```

**Step 4: Commit**

```bash
git add src/pyafk/core/poller.py
git commit -m "fix: use optimistic locking for chain state updates"
```

---

## Task 7: Extract Telegram keyboard builders

**Files:**
- Modify: `src/pyafk/notifiers/telegram.py`

**Step 1: Create keyboard builder methods**

```python
def _build_approval_keyboard(
    self, request_id: str, session_id: str, tool_name: str
) -> dict[str, list[list[dict[str, str]]]]:
    """Build standard approval keyboard."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{request_id}"},
                {"text": "📝 Rule", "callback_data": f"add_rule:{request_id}"},
                {"text": f"⏩ All {tool_name}", "callback_data": f"approve_all:{session_id}:{tool_name}"},
            ],
            [
                {"text": "❌ Deny", "callback_data": f"deny:{request_id}"},
                {"text": "💬 Deny+Msg", "callback_data": f"deny_msg:{request_id}"},
            ],
        ]
    }

def _build_chain_keyboard(
    self, request_id: str, current_idx: int
) -> dict[str, list[list[dict[str, str]]]]:
    """Build chain approval keyboard."""
    return {
        "inline_keyboard": [
            [{"text": "⏩ Approve Chain", "callback_data": f"chain_approve_entire:{request_id}"}],
            [{"text": "✅ Approve Step", "callback_data": f"chain_approve:{request_id}:{current_idx}"}],
            [
                {"text": "📝 Rule", "callback_data": f"chain_rule:{request_id}:{current_idx}"},
                {"text": "❌ Deny", "callback_data": f"chain_deny:{request_id}"},
                {"text": "✍️ Deny+Msg", "callback_data": f"chain_deny_msg:{request_id}"},
            ],
        ]
    }
```

**Step 2: Update send_approval_request and send_chain_approval_request to use builders**

Replace inline keyboard dicts with method calls.

**Step 3: Run mypy**

Run: `mypy src/pyafk/notifiers/telegram.py`
Expected: No errors

**Step 4: Commit**

```bash
git add src/pyafk/notifiers/telegram.py
git commit -m "refactor: extract keyboard builder methods in telegram.py"
```

---

## Task 8: Use formatting helpers in poller.py

**Files:**
- Modify: `src/pyafk/core/poller.py`

**Step 1: Import formatting helpers**

```python
from pyafk.utils.formatting import escape_html, format_project_id, truncate_command
```

**Step 2: Remove duplicate _format_project_id method**

Delete the `_format_project_id` method and replace all calls with `format_project_id()`.

**Step 3: Use truncate_command helper**

Replace inline truncation logic with `truncate_command()`.

**Step 4: Run mypy**

Run: `mypy src/pyafk/core/poller.py`
Expected: No errors (or only expected errors to fix in next task)

**Step 5: Commit**

```bash
git add src/pyafk/core/poller.py
git commit -m "refactor: use formatting helpers in poller.py"
```

---

## Task 9: Add type hints to telegram.py

**Files:**
- Modify: `src/pyafk/notifiers/telegram.py`

**Step 1: Add type hints to all methods**

Key signatures:
```python
async def _api_request(self, method: str, data: Optional[dict[str, Any]] = None) -> dict[str, Any]: ...
async def send_approval_request(...) -> Optional[int]: ...
async def edit_message(self, message_id: int, new_text: str, remove_keyboard: bool = True) -> None: ...
def _build_approval_keyboard(...) -> dict[str, list[list[dict[str, str]]]]: ...
```

**Step 2: Run mypy**

Run: `mypy src/pyafk/notifiers/telegram.py`
Expected: No errors

**Step 3: Commit**

```bash
git add src/pyafk/notifiers/telegram.py
git commit -m "chore: add type hints to telegram.py"
```

---

## Task 10: Add type hints to poller.py

**Files:**
- Modify: `src/pyafk/core/poller.py`

**Step 1: Add type hints to all methods**

This is the largest file. Key signatures:
```python
async def _handle_callback(self, callback: dict[str, Any]) -> None: ...
async def _handle_chain_approve(self, request_id: str, command_idx: int, callback_id: str, message_id: Optional[int] = None) -> None: ...
async def _get_chain_state(self, request_id: str) -> Optional[tuple[dict[str, Any], int]]: ...
def _generate_rule_patterns(self, tool_name: str, tool_input: Optional[str], project_path: Optional[str] = None) -> list[tuple[str, str]]: ...
```

**Step 2: Run mypy**

Run: `mypy src/pyafk/core/poller.py`
Expected: No errors

**Step 3: Commit**

```bash
git add src/pyafk/core/poller.py
git commit -m "chore: add type hints to poller.py"
```

---

## Task 11: Add layered error handling to poller

**Files:**
- Modify: `src/pyafk/core/poller.py`

**Step 1: Wrap process_updates_once in try/except**

```python
async def process_updates_once(self) -> int:
    """Process one batch of updates."""
    try:
        # existing code...
    except Exception as e:
        debug_callback(f"Error in process_updates_once", error=str(e)[:200])
        return 0
```

**Step 2: Add consistent error handling to callback handlers**

Pattern for each handler:
```python
async def _handle_chain_approve(self, request_id: str, ...):
    try:
        # existing code
    except Exception as e:
        debug_callback(f"Error in _handle_chain_approve", error=str(e)[:100])
        await self.notifier.answer_callback(callback_id, "Error occurred")
```

**Step 3: Replace silent pass statements with logging**

Find all `except ... pass` and replace with:
```python
except Exception as e:
    debug_callback(f"Ignored error", error=str(e)[:50])
```

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add src/pyafk/core/poller.py
git commit -m "fix: add layered fail-safe error handling"
```

---

## Task 12: Final mypy verification and cleanup

**Files:**
- All modified files

**Step 1: Run mypy on entire package**

Run: `mypy src/pyafk`
Expected: No errors

**Step 2: Fix any remaining type errors**

Address each error individually.

**Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final type hint fixes and cleanup"
```

---

## Task 13: Update tag for release

**Step 1: Delete old tag and create new one**

```bash
git tag -d v0.1.0
git tag -a v0.1.0 -m "Release v0.1.0: Code quality improvements

Features:
- Telegram integration with inline approval buttons
- Smart pattern rules
- Chain command support
- Wrapper command detection
- Optimistic locking for chain state
- Full type hint coverage (mypy strict)
- Layered fail-safe error handling"
```

**Step 2: Verify**

Run: `git tag -l -n1`
Expected: Shows v0.1.0 with new message
