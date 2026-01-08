# UI Improvements Design

## Overview

Three improvements to pyafk Telegram UI:
1. Cleaner button layouts with consistent labels
2. Smart "All X *" pattern button for Bash commands
3. Richer subagent completion messages with auto-dismiss

## 1. Button Layout Changes

### Chain Approval Keyboard

**Before:**
```
Row 1: ⏩ Approve Chain
Row 2: ✅ Approve Step
Row 3: 📝 Rule | ❌ Deny | ✍️ Deny+Msg
```

**After:**
```
Row 1: ⏩ Approve Chain
Row 2: ✅ Step | 📝 Always...
Row 3: ❌ Deny | 💬 Deny...
```

### Standard Approval Keyboard

**Before:**
```
Row 1: ✅ Approve | 📝 Rule | ⏩ All {tool_name}
Row 2: ❌ Deny | 💬 Deny+Msg
```

**After:**
```
Row 1: ✅ Allow | 📝 Always... | ⏩ All git *
Row 2: ❌ Deny | 💬 Deny...
```

### Label Conventions
- Buttons that prompt for input get "..." suffix
- "Rule" renamed to "Always" (clearer intent)
- All buttons have icon + short label

## 2. Smart Pattern Button

For Bash commands, extract first word to create smarter pattern:
- `git status` → "All git *"
- `tail -f log.txt` → "All tail *"
- `npm install foo` → "All npm *"

**Fallback:** If command can't be parsed or first word is empty, show "All Bash"

### Implementation
- In `_build_approval_keyboard()`, check if `tool_name == "Bash"`
- Parse `tool_input` JSON to get command
- Extract first word (split on whitespace, take [0])
- Display "All {first_word} *" or "All Bash" as fallback

## 3. Subagent Completion Messages

### Initial Message (rich)
```
_project_ 🤖 Done (2m 30s)
📝 {task description}
📁 {files modified}
{brief summary}

[✅ OK] [💬 Continue...]
```

### After Auto-Dismiss (compact)
```
_project_ ✅ Agent: {1-line summary} (2m 30s)
```

### Auto-Dismiss Mechanism (Lazy Cleanup)
1. When sending subagent message, store in DB:
   - `msg_id`
   - `timestamp`
   - `compact_text` (pre-computed dismiss text)
2. On next hook invocation, check for messages older than `subagent_auto_dismiss_seconds`
3. Edit old messages to compact form
4. Delete from tracking table

### Config Addition
```json
{
  "subagent_auto_dismiss_seconds": 60
}
```

## Files to Modify

1. **`src/pyafk/notifiers/telegram.py`**
   - `_build_approval_keyboard()` - new layout, smart pattern
   - `_build_chain_keyboard()` - new layout
   - `send_subagent_stop()` - richer message format

2. **`src/pyafk/core/storage.py`**
   - Add `pending_subagent_messages` table
   - `store_subagent_message(msg_id, timestamp, compact_text)`
   - `get_expired_subagent_messages(max_age_seconds)`
   - `delete_subagent_message(msg_id)`

3. **`src/pyafk/utils/config.py`**
   - Add `subagent_auto_dismiss_seconds` config field

4. **`src/pyafk/hooks/subagent.py`**
   - Call lazy cleanup on entry
   - Extract richer info (duration, files, summary)

5. **`src/pyafk/core/poller.py`**
   - Update callback handlers for renamed actions (if any)
