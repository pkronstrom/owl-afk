#!/usr/bin/env bash
# Install pyafk hooks for captain-hook
#
# This script copies pyafk wrapper scripts to captain-hook's hooks directory.
# After running, use 'captain-hook toggle' to enable the hooks.

set -e

CAPTAIN_HOOK_DIR="${HOME}/.config/captain-hook/hooks"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check captain-hook is set up
if [[ ! -d "$CAPTAIN_HOOK_DIR" ]]; then
    echo "Error: captain-hook hooks directory not found at $CAPTAIN_HOOK_DIR"
    echo "Run 'captain-hook' first to initialize captain-hook."
    exit 1
fi

# Check pyafk is installed
if ! python3 -c "import pyafk" 2>/dev/null; then
    echo "Error: pyafk is not installed"
    echo "Install it with: pip install pyafk"
    exit 1
fi

# Copy hooks for each event
for event in pre_tool_use post_tool_use stop subagent_stop; do
    mkdir -p "$CAPTAIN_HOOK_DIR/$event"
    cp "$SCRIPT_DIR/hooks/$event/pyafk.sh" "$CAPTAIN_HOOK_DIR/$event/"
    chmod +x "$CAPTAIN_HOOK_DIR/$event/pyafk.sh"
    echo "Installed: $event/pyafk.sh"
done

echo ""
echo "Done! Next steps:"
echo "  1. Configure pyafk: pyafk setup"
echo "  2. Enable hooks: captain-hook toggle"
echo "  3. Start using Claude Code with Telegram approvals"
