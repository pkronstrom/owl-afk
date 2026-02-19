#!/usr/bin/env bash
# hawk-hook: events=subagent_stop
# hawk-hook: description=OWL AFK subagent stop handler
# hawk-hook: timeout=3600
exec owl hook SubagentStop
