# Auto-Approve Notification Feature

**Date:** 2026-01-11
**Status:** Planned
**Source:** Codex analysis

## Overview

Add a config toggle that sends informational Telegram messages when auto-approve rules trigger, giving visibility into what's being auto-approved.

## Current State

- Auto-accept rules stored in SQLite (`auto_approve_rules`) managed by `RulesEngine`
- When rules match, `ApprovalManager.request_approval` logs an `auto_response` audit event and returns immediately
- No Telegram notification is sent for auto-approved requests
- Config toggles managed in `src/pyafk/utils/config.py` with `PYAFK_*` env var overrides

## Implementation Plan

### 1. Config Toggle

**File:** `src/pyafk/utils/config.py`

```python
# Add to Config.TOGGLES dict
TOGGLES = {
    ...
    "auto_approve_notify": "Notify on auto-approvals",
}

# Add attribute with default
self.auto_approve_notify = False

# Load from config.json
self.auto_approve_notify = data.get("auto_approve_notify", False)

# Save to config.json
"auto_approve_notify": self.auto_approve_notify,
```

Env override: `PYAFK_AUTO_APPROVE_NOTIFY=1`

**File:** `src/pyafk/cli/ui/interactive.py`

Add to `HOOK_TOGGLES` or create a new toggle group:
```python
GENERAL_TOGGLES = ["auto_approve_notify"]
```

### 2. Rule Match Pattern Details (Optional Enhancement)

**File:** `src/pyafk/core/rules.py`

Add method to return matched pattern:
```python
def check_with_pattern(self, tool_call: str) -> tuple[Optional[str], Optional[str]]:
    """Check if tool_call matches any rule.

    Returns:
        (action, matched_pattern) or (None, None) if no match
    """
    for pattern, action, priority in self._get_sorted_rules():
        if matches_pattern(tool_call, pattern):
            return action, pattern
    return None, None
```

**File:** `src/pyafk/core/manager.py`

Extend `RuleCheckResult`:
```python
@dataclass
class RuleCheckResult:
    rule_result: Optional[str]
    is_chain: bool
    chain_commands: Optional[list[str]] = None
    matched_pattern: Optional[str] = None  # NEW
```

### 3. Telegram Info Message

**File:** `src/pyafk/notifiers/telegram.py`

Add method:
```python
async def send_auto_approval_notice(
    self,
    tool_name: str,
    tool_input: Optional[str],
    matched_pattern: Optional[str] = None,
    project_path: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[int]:
    """Send informational message about auto-approved request."""
    project_id = format_project_id(project_path, session_id or "")
    tool_summary = format_tool_summary(tool_name, tool_input)

    parts = [
        f"<b>[{escape_html(project_id)}]</b>",
        f"Auto-approved: <code>{escape_html(tool_summary)}</code>",
    ]

    if matched_pattern:
        parts.append(f"Rule: <code>{escape_html(matched_pattern)}</code>")

    message = "\n".join(parts)
    return await self.send_message(message)
```

For chain auto-approvals, include count + truncated list:
```python
async def send_chain_auto_approval_notice(
    self,
    commands: list[str],
    matched_pattern: Optional[str] = None,
    project_path: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[int]:
    """Send informational message about auto-approved chain."""
    project_id = format_project_id(project_path, session_id or "")

    # Truncate to first 3 commands
    preview = commands[:3]
    preview_text = "\n".join(f"  <code>{escape_html(c[:60])}</code>" for c in preview)
    if len(commands) > 3:
        preview_text += f"\n  <i>... +{len(commands) - 3} more</i>"

    parts = [
        f"<b>[{escape_html(project_id)}]</b>",
        f"Auto-approved chain ({len(commands)} commands):",
        preview_text,
    ]

    if matched_pattern:
        parts.append(f"Rule: <code>{escape_html(matched_pattern)}</code>")

    message = "\n".join(parts)
    return await self.send_message(message)
```

### 4. Manager Integration

**File:** `src/pyafk/core/manager.py`

In `request_approval()`, after rule check returns approve:

```python
# Around line 218-225, after "if check_result.rule_result:"
if check_result.rule_result:
    # Send auto-approval notification if enabled
    if (
        check_result.rule_result == "approve"
        and self.config.auto_approve_notify
        and isinstance(self.notifier, TelegramNotifier)
    ):
        if check_result.is_chain and check_result.chain_commands:
            await self.notifier.send_chain_auto_approval_notice(
                commands=check_result.chain_commands,
                matched_pattern=check_result.matched_pattern,
                project_path=project_path,
                session_id=session_id,
            )
        else:
            await self.notifier.send_auto_approval_notice(
                tool_name=tool_name,
                tool_input=tool_input,
                matched_pattern=check_result.matched_pattern,
                project_path=project_path,
                session_id=session_id,
            )

    # Existing audit log code...
    await self.storage.log_audit(...)
    return check_result.rule_result == "approve", None
```

### 5. Tests

**File:** `tests/test_config.py`

```python
def test_auto_approve_notify_default(mock_pyafk_dir):
    """auto_approve_notify should default to False."""
    config = Config(mock_pyafk_dir)
    assert config.auto_approve_notify is False

def test_auto_approve_notify_load_save(mock_pyafk_dir):
    """auto_approve_notify should persist."""
    config = Config(mock_pyafk_dir)
    config.auto_approve_notify = True
    config.save()

    config2 = Config(mock_pyafk_dir)
    assert config2.auto_approve_notify is True
```

**File:** `tests/test_manager.py`

```python
@pytest.mark.asyncio
async def test_auto_approve_notify_sends_telegram(mock_pyafk_dir):
    """Should send Telegram message when auto_approve_notify enabled."""
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    manager.config.auto_approve_notify = True
    # ... mock TelegramNotifier and verify send_auto_approval_notice called
```

## File Summary

| File | Changes |
|------|---------|
| `src/pyafk/utils/config.py` | Add `auto_approve_notify` toggle |
| `src/pyafk/cli/ui/interactive.py` | Add toggle to UI |
| `src/pyafk/core/rules.py` | Add `check_with_pattern()` (optional) |
| `src/pyafk/core/manager.py` | Extend `RuleCheckResult`, add notification logic |
| `src/pyafk/notifiers/telegram.py` | Add `send_auto_approval_notice()` methods |
| `tests/test_config.py` | Test new toggle |
| `tests/test_manager.py` | Test notification integration |

## Notes

- Default is off (`False`) to avoid noise for users with many rules
- Uses existing `send_message()` for one-way info (no buttons)
- Message format is compact to avoid Telegram spam
- Chain notifications show preview of first 3 commands + count
- Optional: add separate toggle for auto-deny notifications if needed
