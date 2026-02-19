#!/usr/bin/env bash
# hawk-hook: events=pre_tool_use
# hawk-hook: description=OWL AFK pre-tool-use gate
# hawk-hook: timeout=3600
exec owl hook PreToolUse
