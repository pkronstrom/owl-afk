# owl

![owl banner](docs/owl_banner.png)

**Your AI agents, supervised from anywhere.**

Part of [**Nest-Driven Development**](https://github.com/pkronstrom/nest-driven-development) — the minimum vibable workflow.

![Telegram demo](docs/tg_cap.gif)

You stepped away from your laptop while Claude Code was mid-task. Now you have no idea whether it just edited a config file, ran a migration, or rewrote half your codebase — and it's been waiting on your approval the whole time.

owl forwards Claude's permission requests to your phone via Telegram. See exactly what your agents are about to do, approve or deny with one tap, and let smart rules handle the rest. Stay AFK without going blind.

## Features

- **Approve from anywhere**: Tool calls land in Telegram with inline buttons — approve, deny, or create a rule without touching your laptop
- **Auto-approve the safe stuff**: Pattern rules like `Bash(git *)` or `Edit(*.py)` silently pass trusted commands so you only see what actually needs a decision
- **Handle complex pipelines**: Bash chains are broken into individual approvable steps, and SSH/Docker wrappers are expanded so nothing slips through as a bundle
- **Stay informed without babysitting**: Get notified when subagents finish, sessions start or end, and context gets compacted — the full picture without constant watching
- **Keep it scoped**: Enable owl only for specific projects, so it guards the work that matters without adding noise to everything else

## Installation

```bash
# With uv (recommended)
uv tool install git+https://github.com/pkronstrom/owl-afk

# With pipx
pipx install git+https://github.com/pkronstrom/owl-afk

# Development (editable install)
git clone https://github.com/pkronstrom/owl-afk
cd owl-afk
uv sync
```

## Setup

### 1. Create a Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Save the bot token

### 2. Get Your Chat ID

1. Message your new bot
2. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find your `chat.id` in the response

### 3. Configure owl

```bash
owl install
```

This will prompt for your bot token and chat ID, then set up Claude Code hooks.

## Usage

### Enable/Disable

```bash
owl on   # Enable remote approval
owl off  # Disable (auto-approves pending requests)
```

### Check Status

```bash
owl status
```

### Rule Presets

Load pre-built rulesets to auto-approve common operations:

```bash
owl rules preset              # Interactive menu
owl rules preset cautious     # Read-only tools, git reads, file inspection
owl rules preset standard     # + file writes, git commits, dev tools, testing
owl rules preset permissive   # + git push, docker run, network, runtimes
```

The setup wizard also offers preset selection on first run.

### Manage Rules

```bash
owl rules list              # List all rules
owl rules add "Bash(git *)" # Add a rule
owl rules remove 1          # Remove rule by ID
```

### Debug Mode

```bash
owl debug on   # Enable debug logging to ~/.config/owl/debug.log
owl debug off  # Disable debug logging
```

### Environment Overrides

```bash
owl env list           # List env var overrides
owl env set KEY value  # Set an override
owl env unset KEY      # Remove an override
```

## Telegram Commands

Once a request comes in, you'll see inline buttons:

- **Allow**: Approve the current command
- **Approve Chain**: Approve all commands in a chain at once
- **Step**: Approve a single step in a chain
- **Always...**: Create a pattern rule for future auto-approval
- **Deny** / **Deny + msg**: Deny with optional feedback message

### Pattern Examples

| Pattern | Matches |
|---------|---------|
| `Bash(git *)` | Any git command |
| `Bash(ssh aarni git *)` | Any git command on host "aarni" |
| `Bash(ssh aarni *)` | Any command on host "aarni" |
| `Edit(*.py)` | Any Python file edit |
| `Edit(/path/to/project/*)` | Any edit in project |
| `Read(*)` | Any file read |

## Architecture

```
~/.config/owl/
├── mode           # "on" or "off"
├── owl.db       # SQLite database (requests, rules, sessions)
├── debug.log      # Debug log (when enabled)
└── config.json    # Bot token and chat ID
```

owl uses Claude Code hooks to intercept tool calls:
- `PreToolUse` - Intercepts before tool execution
- `PostToolUse` - Delivers queued messages, optionally edits approval messages with tool results
- `PermissionRequest` - Handles permission/trust prompts
- `SessionStart` / `SessionEnd` - Session lifecycle notifications
- `PreCompact` - Notifies before context compaction
- `Stop` - Interactive confirmation before Claude stops
- `SubagentStop` - Notifies when subagents complete

## Hawk-Hooks Integration

owl can also be used with [hawk-hooks](https://github.com/pkronstrom/hawk-hooks) as the hook manager. See [extras/hawk-hooks/README.md](extras/hawk-hooks/README.md) for setup instructions.

## Requirements

- Python 3.10+
- Claude Code CLI with hooks support
- Telegram account

## Security Considerations

### Credential Storage

- Telegram bot token and chat ID are stored in `~/.config/owl/config.json`
- File permissions are automatically set to `0600` (owner read/write only)
- Do not commit config.json to version control
- Limit filesystem access to trusted users

### Approval Security

- owl intercepts and gates Claude Code tool calls
- Commands approved by you are executed by Claude Code, not owl
- owl cannot prevent malicious commands if you approve them
- Review all commands carefully before approving

### Debug Mode

- Debug logs may contain sensitive information (commands, file paths, session data)
- Only enable debug mode when troubleshooting
- Debug logs stored in `~/.config/owl/debug.log`

### Network Security

- owl communicates with Telegram API over HTTPS
- Telegram bot token transmitted in URL path (standard Telegram API practice)
- No user data leaves your machine except to your own Telegram bot

## License

MIT
