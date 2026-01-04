# Smart Recursive Rule Pattern Engine - Implementation

**Date:** January 4, 2025
**Status:** ✅ Complete
**Test Coverage:** 34 passing tests (14 integration tests + 20 unit tests)

## Overview

This implementation adds a comprehensive smart recursive rule pattern engine to pyafk that handles complex bash command chains, wrappers, and substitutions. The system provides intelligent approval workflows with multi-step Telegram UI for chain approvals and automatic rule-based decisions.

### Key Features

- **Recursive Command Parser:** Parses bash commands into tree structures, handling wrappers (ssh, docker, sudo, etc.), command chains (&amp;&amp;, ||, ;, |), and quoted arguments
- **Multi-Level Pattern Generation:** Creates approval patterns from specific to general, enabling granular rule matching
- **Chain Approval Flow:** Step-by-step approval UI for command chains with progress tracking
- **Auto-Approval Engine:** Automatically approves/denies chains when all commands match rules
- **Smart Rule Creation:** Generates multiple pattern options for creating rules from the Telegram UI

## Architecture

### Component Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    Approval Request Flow                      │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  CommandParser   │
                    │  - split_chain() │
                    │  - parse()       │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  CommandNode Tree│
                    │  (recursive)     │
                    └──────────────────┘
                              │
                              ▼
                ┌────────────────────────────┐
                │  Pattern Generator         │
                │  - Wrapper patterns        │
                │  - Unwrapped patterns      │
                │  - Wildcard patterns       │
                └────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Rules Engine    │
                    │  - check()       │
                    └──────────────────┘
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
         ┌────────────┐             ┌─────────────┐
         │ Auto-      │             │ Manual      │
         │ Approve/   │             │ Approval    │
         │ Deny       │             │ (Telegram)  │
         └────────────┘             └─────────────┘
                                           │
                                           ▼
                                ┌──────────────────────┐
                                │ Chain Approval UI    │
                                │ - Step-by-step       │
                                │ - Progress tracking  │
                                │ - Rule creation      │
                                └──────────────────────┘
```

## Components

### 1. CommandParser

**Location:** `src/pyafk/core/command_parser.py`

The CommandParser is the core component that transforms bash command strings into structured tree representations.

#### Key Methods

- **`split_chain(cmd: str) -> List[str]`**
  Splits command chains into individual commands, respecting quotes and shell operators (&amp;&amp;, ||, ;, |).

  ```python
  parser = CommandParser()
  parser.split_chain("cd ~/project && npm test && git log")
  # Returns: ["cd ~/project", "npm test", "git log"]
  ```

- **`parse(cmd: str) -> List[CommandNode]`**
  Parses a complete bash command string into CommandNode objects, one per chained command.

  ```python
  parser = CommandParser()
  nodes = parser.parse("ssh aarni git status && npm test")
  # Returns: [CommandNode(wrapper=ssh, nested=git status), CommandNode(npm test)]
  ```

- **`parse_single_command(cmd: str) -> CommandNode`**
  Parses a single command into a CommandNode tree, handling nested wrappers recursively.

- **`generate_patterns(node: CommandNode) -> List[str]`**
  Generates approval patterns from most specific to most general.

#### CommandNode Structure

```python
@dataclass
class CommandNode:
    type: CommandType          # WRAPPER, FILE_OP, VCS, GENERIC
    name: str                  # Command name (e.g., "ssh", "git", "rm")
    args: List[str]           # Command arguments
    params: Dict[str, str]    # Wrapper parameters (host, container, etc.)
    nested: Optional[CommandNode]  # Nested command for wrappers
    full_cmd: str             # Original command string
```

#### Wrapper Registry

The parser recognizes these wrappers:
- `ssh` (host parameter)
- `docker` (action, container parameters)
- `sudo` (no parameters)
- `nix-shell` (no parameters)
- `kubectl` (action parameter)
- `screen` (session parameter)
- `tmux` (session parameter)
- `env` (no parameters)
- `timeout` (seconds parameter)

### 2. Pattern Generation

**How it works:** The pattern generator creates multiple approval patterns for each command, from most specific to most general. This allows users to create rules at different granularity levels.

#### Simple Command Patterns

For a command like `rm /tmp/file.txt`:
1. `rm /tmp/file.txt` - Exact match
2. `rm *` - Any rm command

#### Wrapper Command Patterns

For a command like `ssh aarni git log`:
1. `ssh aarni git log` - Exact match
2. `ssh aarni git *` - Any git command on aarni
3. `ssh aarni *` - Any command on aarni
4. `git log` - Unwrapped: exact git log
5. `git *` - Unwrapped: any git command

#### Chain Command Patterns

For a chain like `cd ~/project && npm test`:
- Generates patterns for EACH command in the chain
- Each command gets its own pattern set
- Rules are checked against each command's patterns

### 3. Chain Approval Flow

**Location:** `src/pyafk/core/poller.py`

The chain approval system provides a step-by-step UI for approving complex command chains.

#### Flow Diagram

```
┌─────────────────────────────────────────────────────────┐
│  1. User receives chain approval request               │
│     Shows: All commands stacked, first one highlighted  │
└─────────────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   ┌─────────┐    ┌─────────┐    ┌─────────┐
   │ Approve │    │  Deny   │    │  Rule   │
   └─────────┘    └─────────┘    └─────────┘
        │               │               │
        ▼               │               ▼
   ┌─────────┐         │         ┌──────────────┐
   │ Move to │         │         │ Show pattern │
   │ next    │         │         │ options      │
   │ command │         │         └──────────────┘
   └─────────┘         │               │
        │               │               ▼
        │               │         ┌──────────────┐
        │               │         │ Create rule  │
        │               │         │ + mark cmd   │
        │               │         │ approved     │
        │               │         └──────────────┘
        │               │               │
        └───────────────┴───────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │ All commands     │
              │ approved?        │
              └──────────────────┘
                        │
           ┌────────────┴────────────┐
           ▼                         ▼
    ┌──────────┐              ┌──────────┐
    │ Show     │              │ Continue │
    │ "Approve │              │ to next  │
    │ All"     │              │ command  │
    └──────────┘              └──────────┘
```

#### Key Methods

- **`_handle_chain_approve(request_id, command_idx, ...)`**
  Approves a single command in the chain and moves to the next.

- **`_handle_chain_deny(request_id, ...)`**
  Denies the entire chain immediately.

- **`_handle_chain_rule(request_id, command_idx, ...)`**
  Shows pattern options for creating a rule for the current command.

- **`_handle_chain_approve_all(request_id, ...)`**
  Final approval after all commands are individually approved.

- **`_check_chain_rules(cmd: str) -> Optional[str]`**
  Auto-checks if entire chain can be approved/denied via rules:
  - Returns `"approve"` if ALL commands match allow rules
  - Returns `"deny"` if ANY command matches deny rule
  - Returns `None` if manual approval needed

#### Chain State Persistence

Chain approval state is stored in the database using the `pending_feedback` table:
```python
{
    "commands": ["cmd1", "cmd2", "cmd3"],
    "approved_indices": [0, 1]  # Commands 0 and 1 approved
}
```

### 4. Telegram UI

**Location:** `src/pyafk/notifiers/telegram.py`

The Telegram UI provides a multi-step approval interface with inline keyboards.

#### Chain Approval Message Format

```
project/path
Command chain approval:

→ cd ~/project
  npm test
  git log

[✅ Approve] [❌ Deny]
[📝 Rule]
```

After approving the first command:

```
project/path
Command chain approval:

✓ cd ~/project
→ npm test
  git log

[✅ Approve] [❌ Deny]
[📝 Rule]
```

All approved, ready for final confirmation:

```
project/path
Command chain approval:

✓ cd ~/project
✓ npm test
✓ git log

[✅ Approve All] [❌ Cancel]
```

#### Key Methods

- **`send_chain_approval_request(...)`**
  Sends the initial chain approval message with stacked command list.

- **`update_chain_progress(...)`**
  Updates the message to show progress (which commands approved, current command).

- **`edit_message_with_rule_keyboard(...)`**
  Shows pattern options when user clicks "Rule" button.

#### Rule Pattern Selection UI

When user clicks "📝 Rule", they see pattern options:

```
Command 1: cd ~/project

📌 cd ~/project
🔧 cd *
⚡ Any Bash

[✅ Approve] [↩️ Cancel]
```

Each button creates the corresponding rule and marks the command as approved.

## Examples

### Example 1: Simple Chain Auto-Approval

**Scenario:** User has rules for git commands, chain is auto-approved.

```python
# Rules in database
rules = [
    "Bash(git status)" -> approve,
    "Bash(git diff)" -> approve,
    "Bash(git log)" -> approve
]

# Command received
cmd = "git status && git diff && git log"

# Flow
1. Parser splits: ["git status", "git diff", "git log"]
2. Pattern generator creates patterns for each
3. Rules engine checks all three - all match approve rules
4. AUTO-APPROVE (no Telegram message sent)
```

### Example 2: Chain with One Unmatched Command

**Scenario:** Only some commands have rules, manual approval required.

```python
# Rules in database
rules = [
    "Bash(git status)" -> approve,
    "Bash(git commit *)" -> approve
]

# Command received (npm test has no rule)
cmd = "git status && npm test && git commit -m 'test'"

# Flow
1. Parser splits into 3 commands
2. Pattern check: git status ✓, npm test ✗, git commit ✓
3. Manual approval REQUIRED (Telegram UI shown)
4. User approves npm test step-by-step
5. Chain approved
```

### Example 3: Wrapper Command with Rule

**Scenario:** SSH wrapper command matches a rule.

```python
# Rules in database
rules = [
    "Bash(ssh aarni git *)" -> approve
]

# Command received
cmd = "ssh aarni git log"

# Flow
1. Parser detects ssh wrapper with nested git log
2. Pattern generator creates:
   - "ssh aarni git log"
   - "ssh aarni git *"  ← MATCHES RULE
   - "ssh aarni *"
   - "git log" (unwrapped)
   - "git *" (unwrapped)
3. Rule matches on pattern #2
4. AUTO-APPROVE
```

### Example 4: Creating Rule from Chain UI

**Scenario:** User approves a command and wants to create a rule.

```python
# Chain received
cmd = "cd ~/project && npm test && git commit -m 'test'"

# User flow
1. Telegram shows: "→ cd ~/project"
2. User clicks "📝 Rule"
3. UI shows pattern options:
   - "📌 cd ~/project" (exact)
   - "🔧 cd *" (any cd)
   - "⚡ Any Bash" (any bash)
4. User selects "🔧 cd *"
5. Rule created: "Bash(cd *)" -> approve
6. Command marked approved, UI moves to "npm test"
```

### Example 5: Deny Rule Blocks Chain

**Scenario:** One command in chain has a deny rule.

```python
# Rules in database
rules = [
    "Bash(cd *)" -> approve,
    "Bash(rm -rf *)" -> deny,  ← DENY RULE
    "Bash(npm install)" -> approve
]

# Command received
cmd = "cd ~/projects && rm -rf node_modules && npm install"

# Flow
1. Parser splits into 3 commands
2. Pattern check:
   - cd ~/projects → "cd *" → approve
   - rm -rf node_modules → "rm -rf *" → DENY ← Stops here
3. AUTO-DENY entire chain (no Telegram message)
```

## Test Coverage

### Unit Tests (20 tests)
**File:** `tests/test_command_parser.py`

- CommandNode data structure tests
- Chain splitting with various operators (&amp;&amp;, ||, ;, |)
- Quote handling in chain splitting
- Wrapper detection (ssh, docker, sudo)
- Command type detection (FILE_OP, VCS, GENERIC)
- Single command parsing
- Chain parsing with multiple commands
- Pattern generation for simple commands
- Pattern generation for wrapper commands

### Integration Tests (14 tests)
**File:** `tests/test_chain_approval_integration.py`

- **test_full_chain_approval_flow** - Complete chain approval with sequential approvals
- **test_chain_denial_flow** - Chain denial workflow
- **test_chain_rule_creation** - Creating rules for commands in chains
- **test_chain_auto_approval_via_rules** - Auto-approval when all commands match rules
- **test_chain_partial_auto_approval** - Manual approval when some commands lack rules
- **test_chain_deny_rule_blocks_entire_chain** - Deny rule blocks entire chain
- **test_parser_integration_with_chains** - Complex command parsing
- **test_wrapper_command_in_chain** - Wrapper commands within chains
- **test_single_command_not_treated_as_chain** - Single commands use regular UI
- **test_empty_chain_handling** - Edge case handling
- **test_chain_state_persistence** - Chain state survives poller interactions
- **test_pattern_generation_for_chain_commands** - Pattern generation for each command
- **test_chain_with_quoted_arguments** - Quoted argument handling in chains
- **test_long_chain_truncation_in_ui** - UI handles very long chains (50+ commands)

### Test Results

```
✅ All chain approval tests passing (14/14)
✅ All command parser tests passing (20/20)
✅ Total: 34 tests passing

Note: 9 pre-existing test failures in other modules (unrelated to this implementation)
```

## Known Issues and Limitations

### Pre-existing Test Failures
The following tests were failing before this implementation and remain unresolved:
- `test_hooks.py::test_pretool_approve_by_rule` - KeyError: 'decision'
- `test_hooks.py::test_pretool_off_mode_approves` - KeyError: 'decision'
- `test_hooks.py::test_pretool_extracts_context` - KeyError: 'decision'
- `test_integration.py::test_full_approval_flow` - KeyError: 'decision'
- `test_integration.py::test_rule_based_auto_approve` - KeyError: 'decision'
- `test_manager.py::test_manager_auto_approve_by_rule` - Return type mismatch
- `test_manager.py::test_manager_auto_deny_by_rule` - Return type mismatch
- `test_manager.py::test_manager_timeout_action` - Return type mismatch
- `test_poller.py::test_poller_processes_callback` - Status assertion failure

These failures appear to be related to API changes in other parts of the codebase and are not caused by the chain approval engine implementation.

### TODO Comments
The following TODO comments remain in the codebase:

1. **`src/pyafk/core/poller.py:664`**
   ```python
   # TODO: We need to get original message text - for now use a simple placeholder
   ```
   Context: When showing rule pattern keyboard for a chain command, the original message text is not preserved. Currently uses a simplified placeholder. This is a minor UI issue that doesn't affect functionality.

2. **`src/pyafk/hooks/stop.py:12`**
   ```python
   # TODO: Send summary to Telegram
   ```
   Pre-existing TODO, unrelated to chain approval engine.

3. **`src/pyafk/hooks/session.py:12`**
   ```python
   # TODO: Send notification to Telegram
   ```
   Pre-existing TODO, unrelated to chain approval engine.

### Debug Print Statements
Debug print statements exist in `src/pyafk/core/poller.py` lines 243, 246, and 251:
```python
print(f"[pyafk] Looking up request: {request_id}", file=sys.stderr)
print(f"[pyafk] Request not found: {request_id}", file=sys.stderr)
print(f"[pyafk] Found request: {request.id} status={request.status}", file=sys.stderr)
```

These are intentional debug logs for troubleshooting approval request issues and can be kept or removed as needed.

Other print statements in the codebase are legitimate (part of CLI output, console notifier, hook handlers, etc.).

### Limitations

1. **Chain Length Display:** Very long chains (50+ commands) are truncated in the Telegram UI to fit within Telegram's 4096 character message limit. The system shows the first 20 commands, an ellipsis, and the last 10 commands.

2. **Quote Handling:** The parser handles double and single quotes but doesn't support escaped quotes or complex shell expansions (e.g., `$(command)`, backticks).

3. **Nested Chain Operators:** For wrapper commands with nested chains in quotes (e.g., `ssh host "cmd1 && cmd2"`), only the first command in the nested chain is parsed as the nested command. This is by design to keep the tree structure simple.

## Performance Characteristics

- **Pattern Generation:** O(n) where n is the depth of wrapper nesting (typically 1-3)
- **Chain Splitting:** O(n) where n is the command length
- **Rule Matching:** O(m × p) where m is the number of rules and p is the number of patterns per command
- **Chain Approval:** State is persisted to database for reliability across poller restarts

## Future Enhancements

Potential improvements for future iterations:

1. **Pattern Preview:** Show which rules would match before creating a new rule
2. **Rule Priority UI:** Allow users to set rule priority from Telegram
3. **Command Grouping:** Option to approve/deny multiple similar commands at once
4. **Pattern Suggestions:** ML-based suggestions for common command patterns
5. **Batch Rule Creation:** Create rules for all commands in a chain at once
6. **Command History:** Show similar commands approved in the past
7. **Escape Quote Support:** Handle escaped quotes in command parsing

## Conclusion

The Smart Recursive Rule Pattern Engine successfully implements intelligent command chain handling with multi-step approval flows. The system provides excellent user experience through progressive disclosure (step-by-step approval) while maintaining powerful automation capabilities (auto-approve/deny based on rules).

All 34 tests pass, demonstrating comprehensive coverage of the core functionality including parsing, pattern generation, chain approval flow, and Telegram UI integration.

The implementation is production-ready with only minor TODO items remaining for future enhancement.
