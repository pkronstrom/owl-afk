# owl

![owl banner](docs/owl_banner.png)

[![PyPI version](https://img.shields.io/pypi/v/owl-afk)](https://pypi.org/project/owl-afk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Part of NDD](https://img.shields.io/badge/NDD-minimum%20viable%20workflow-blue)](https://github.com/pkronstrom/nest-driven-development)

**Approve your AI agents' actions from your phone. Stay AFK without going blind.**

Part of [**Nest-Driven Development**](https://github.com/pkronstrom/nest-driven-development) — the minimum viable workflow.

![Telegram demo](docs/tg_cap.gif)

---

## The Problem

You stepped away from your laptop while Claude Code was mid-task. Now you have no idea whether it just edited a config file, ran a migration, or rewrote half your codebase — and it's been waiting on your approval the whole time.

## The Solution

owl intercepts Claude Code's permission requests and forwards them to your phone via Telegram. See exactly what your agent is about to do, approve or deny with one tap, and let smart rules handle the routine stuff automatically.

---

## Quick Start

```bash
# Install
uv tool install git+https://github.com/pkronstrom/owl-afk

# Setup (wizard — handles bot config + Claude Code hooks)
owl install

# Enable remote supervision
owl on
```

Then step away from your laptop. Approvals arrive in Telegram.

---

## Features

- **Approve from anywhere** — tool calls land in Telegram with inline buttons: approve, deny, create a rule
- **Auto-approve the safe stuff** — pattern rules like `Bash(git *)` or `Edit(*.py)` pass trusted commands silently
- **Handle complex pipelines** — Bash chains are broken into individual steps, SSH/Docker wrappers are expanded so nothing slips through as a bundle
- **Stay informed without babysitting** — get notified when subagents finish, sessions start/end, and context gets compacted
- **Keep it scoped** — enable owl per-project so it guards what matters without adding noise everywhere else

---

## Setup

### 1. Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 2. Get your chat ID

1. Message your new bot
2. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `chat.id` in the response

### 3. Install owl

```bash
owl install
# Prompts for bot token + chat ID, then sets up Claude Code hooks
```

---

## Usage

```bash
owl on     # Enable remote approval
owl off    # Disable (auto-approves pending requests)
owl status # Show current state
```

---

## Auto-Approval Rules

Skip the phone for routine operations:

```bash
owl rules preset              # Interactive menu
owl rules preset cautious     # Read-only tools, git reads, file inspection
owl rules preset standard     # + file writes, git commits, dev tools, testing
owl rules preset permissive   # + git push, docker run, network, runtimes
```

Manage individual rules:

```bash
owl rules list               # List all rules
owl rules add "Bash(git *)"  # Add a rule
owl rules remove 1           # Remove rule by ID
```

### Pattern reference

| Pattern | What it auto-approves |
|---------|----------------------|
| `Bash(git *)` | Any git command |
| `Bash(ssh aarni git *)` | Any git command on a specific host |
| `Edit(*.py)` | Any Python file edit |
| `Edit(/path/to/project/*)` | Any edit in a specific project |
| `Read(*)` | Any file read |

---

## Telegram Controls

When a request arrives, you'll see inline buttons:

- **Allow** — approve the current command
- **Approve Chain** — approve all commands in a chain at once
- **Step** — approve a single step in a chain
- **Always...** — create a pattern rule for future auto-approval
- **Deny** / **Deny + msg** — deny with optional feedback to Claude

---

## Architecture

```
~/.config/owl/
├── mode         # "on" or "off"
├── owl.db       # SQLite (requests, rules, sessions)
├── debug.log    # Debug log (when enabled)
└── config.json  # Bot token and chat ID
```

owl hooks into Claude Code at these events:
- `PreToolUse` — intercepts before execution
- `PostToolUse` — delivers queued messages, edits approval messages with results
- `PermissionRequest` — handles permission/trust prompts
- `SessionStart` / `SessionEnd` — lifecycle notifications
- `PreCompact` — notifies before context compaction
- `Stop` — interactive confirmation before Claude stops
- `SubagentStop` — notifies when subagents complete

---

## Hawk-Hooks Integration

owl works with [hawk-hooks](https://github.com/pkronstrom/hawk-hooks) as the hook manager. See [extras/hawk-hooks/README.md](extras/hawk-hooks/README.md) for setup.

---

## Security

- Bot token and chat ID stored in `~/.config/owl/config.json` (permissions: `0600`)
- Don't commit `config.json` to version control
- All communication with Telegram happens over HTTPS
- No data leaves your machine except to your own bot
- owl gates Claude's actions — it cannot prevent malicious commands if you approve them

---

## Requirements

- Python 3.10+
- Claude Code CLI with hooks support
- Telegram account

---

## License

MIT
