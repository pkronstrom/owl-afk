"""Tests for hook response helpers."""

from pyafk.hooks.response import make_hook_response


class TestMakeHookResponse:
    def test_pretool_allow(self):
        result = make_hook_response("PreToolUse", decision="allow")
        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "",
            }
        }

    def test_pretool_deny_with_reason(self):
        result = make_hook_response(
            "PreToolUse", decision="deny", reason="blocked by rule"
        )
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert (
            result["hookSpecificOutput"]["permissionDecisionReason"]
            == "blocked by rule"
        )

    def test_posttool_with_context(self):
        result = make_hook_response(
            "PostToolUse", additional_context="User sent a message"
        )
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert (
            result["hookSpecificOutput"]["additionalContext"] == "User sent a message"
        )

    def test_posttool_empty(self):
        result = make_hook_response("PostToolUse")
        assert result == {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}

    def test_permission_allow(self):
        result = make_hook_response("PermissionRequest", decision="allow")
        assert result["hookSpecificOutput"]["hookEventName"] == "PermissionRequest"
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
