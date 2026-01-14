# Auto-Approve Notification Feature

**Date:** 2026-01-11
**Status:** Completed
**Source:** Codex analysis, revised after code review

## Overview

Add a config toggle that sends informational Telegram messages when auto-approve rules trigger, giving visibility into what's being auto-approved.

## Design Principles

- **DRY**: Reuse existing `send_message()` instead of new notifier methods
- **No code smell**: No `isinstance` checks in manager - use polymorphism
- **Minimal overhead**: Single formatting helper, simple integration
- **Clean abstraction**: Extend `Notifier` base class properly

## Implementation Plan

### 1. Config Toggle

**File:** `src/owl/utils/config.py`

Add to `TOGGLES` dict:
```python
TOGGLES: dict[str, str] = {
    ...
    "auto_approve_notify": "Notify on auto-approvals",
}
```

Add attribute with default `False`:
```python
self.auto_approve_notify = False
```

Load/save in `_load()` and `save()` methods.

Env override: `OWL_AUTO_APPROVE_NOTIFY=1`

### 2. Notifier Base Class Extension

**File:** `src/owl/notifiers/base.py`

Add method with no-op default:
```python
async def send_info_message(self, text: str) -> None:
    """Send an informational message (no response expected).

    Default implementation is no-op. Override in notifiers that
    support one-way messages (e.g., Telegram).
    """
    pass
```

### 3. TelegramNotifier Override

**File:** `src/owl/notifiers/telegram.py`

Override to use existing `send_message()`:
```python
async def send_info_message(self, text: str) -> None:
    """Send an informational message."""
    await self.send_message(text)
```

### 4. Formatting Helper

**File:** `src/owl/utils/formatting.py`

Add function:
```python
def format_auto_approval_message(
    tool_name: str,
    tool_input: Optional[str],
    project_path: Optional[str],
    session_id: str,
    is_chain: bool = False,
    chain_commands: Optional[list[str]] = None,
) -> str:
    """Format auto-approval notification message.

    Args:
        tool_name: Name of the tool (e.g., "Bash")
        tool_input: JSON tool input
        project_path: Project path for display
        session_id: Session ID for display
        is_chain: Whether this is a command chain
        chain_commands: List of commands if chain

    Returns:
        HTML-formatted message string
    """
    project_id = format_project_id(project_path, session_id)

    if is_chain and chain_commands:
        # Chain: show count and first few commands
        preview = chain_commands[:3]
        preview_text = ", ".join(cmd[:30] + "..." if len(cmd) > 30 else cmd for cmd in preview)
        if len(chain_commands) > 3:
            preview_text += f" (+{len(chain_commands) - 3} more)"
        summary = f"{len(chain_commands)} commands: {preview_text}"
    else:
        # Single command: extract summary from tool_input
        summary = format_tool_summary(tool_name, tool_input)

    return (
        f"<i>{escape_html(project_id)}</i>\n"
        f"✓ Auto-approved: <code>{escape_html(summary)}</code>"
    )
```

### 5. Manager Integration

**File:** `src/owl/core/manager.py`

In `request_approval()`, after rule check returns approve (around line 217):

```python
if check_result.rule_result:
    # Send auto-approval notification if enabled
    if check_result.rule_result == "approve" and self.config.auto_approve_notify:
        from owl.utils.formatting import format_auto_approval_message

        msg = format_auto_approval_message(
            tool_name=tool_name,
            tool_input=tool_input,
            project_path=project_path,
            session_id=session_id,
            is_chain=check_result.is_chain,
            chain_commands=check_result.chain_commands if check_result.is_chain else None,
        )
        await self.notifier.send_info_message(msg)

    # Existing audit log code...
    await self.storage.log_audit(...)
    return (check_result.rule_result, None)
```

### 6. Tests

**File:** `tests/test_config.py`
- Test default value is False
- Test load/save persistence
- Test env override

**File:** `tests/test_manager.py`
- Test notification sent when enabled + rule matches
- Test no notification when disabled
- Test chain vs single command formatting

## File Summary

| File | Changes |
|------|---------|
| `src/owl/utils/config.py` | Add `auto_approve_notify` toggle |
| `src/owl/notifiers/base.py` | Add `send_info_message()` no-op |
| `src/owl/notifiers/telegram.py` | Override `send_info_message()` |
| `src/owl/utils/formatting.py` | Add `format_auto_approval_message()` |
| `src/owl/core/manager.py` | Call notification after auto-approve |
| `tests/test_config.py` | Test new toggle |
| `tests/test_manager.py` | Test notification integration |

## Notes

- Default is off (`False`) to avoid noise for users with many rules
- Uses existing `send_message()` infrastructure - no new Telegram API calls
- Message format is compact: project ID + "Auto-approved: summary"
- No matched pattern shown (can add later if needed)
- ConsoleNotifier's `send_info_message()` is no-op (appropriate for CLI)
