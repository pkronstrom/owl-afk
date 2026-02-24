"""Constants used throughout owl."""

# Default timeout for approval requests (in seconds)
DEFAULT_REQUEST_TIMEOUT = 3600  # 1 hour

# Default action when request times out
DEFAULT_TIMEOUT_ACTION = "deny"

# Polling intervals (in seconds)
DEFAULT_POLL_INTERVAL = 0.5
LONG_POLL_TIMEOUT = 30
HTTP_CLIENT_TIMEOUT = 30

# SQLite busy timeout (in milliseconds)
SQLITE_BUSY_TIMEOUT_MS = 5000


# Approval actions
class Action:
    """Approval action constants."""

    APPROVE = "approve"
    DENY = "deny"


# Hook decisions
class HookDecision:
    """Hook decision constants for Claude CLI."""

    ALLOW = "allow"
    DENY = "deny"


# Callback action prefixes
class CallbackAction:
    """Telegram callback action names."""

    APPROVE = "approve"
    DENY = "deny"
    DENY_MSG = "deny_msg"
    ADD_RULE = "add_rule"
    SUBAGENT_OK = "subagent_ok"
    SUBAGENT_CONTINUE = "subagent_continue"
    BATCH_APPROVE_ALL = "batch_approve_all"
    BATCH_DENY_ALL = "batch_deny_all"
    # Chain-related actions
    CHAIN_APPROVE = "chain_approve"
    MCP_ALLOW_ALL = "mcp_allow_all"
    CHAIN_APPROVE_ALL = "chain_approve_all"
    CHAIN_DENY = "chain_deny"
    CHAIN_RULE = "chain_rule"
