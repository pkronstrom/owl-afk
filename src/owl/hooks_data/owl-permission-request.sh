#!/usr/bin/env bash
# hawk-hook: events=permission_request
# hawk-hook: description=OWL AFK permission request gate
# hawk-hook: timeout=3600
exec owl hook PermissionRequest
