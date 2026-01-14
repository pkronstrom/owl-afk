"""End-to-end integration tests."""

import json
import pytest
from unittest.mock import patch, AsyncMock

from owl.core.manager import ApprovalManager
from owl.hooks.pretool import handle_pretool_use


@pytest.mark.asyncio
async def test_full_approval_flow(mock_owl_dir):
    """Test complete approval flow from hook to response."""
    (mock_owl_dir / "mode").write_text("on")

    config_data = {
        "telegram_bot_token": "test-token",
        "telegram_chat_id": "12345",
        "timeout_seconds": 1,
        "timeout_action": "deny",
    }
    (mock_owl_dir / "config.json").write_text(json.dumps(config_data))

    # Patch ApprovalManager to use short timeout from config
    original_init = ApprovalManager.__init__

    def patched_init(self, owl_dir=None, timeout=3600, timeout_action="deny", config=None):
        # Read config to get timeout settings
        from owl.utils.config import Config
        cfg = Config(owl_dir)
        original_init(
            self,
            owl_dir=owl_dir,
            timeout=cfg.timeout_seconds,
            timeout_action=cfg.timeout_action,
            config=cfg,
        )

    with patch.object(ApprovalManager, "__init__", patched_init):
        with patch("owl.notifiers.telegram.TelegramNotifier._api_request") as mock_api:
            mock_api.return_value = {"ok": True, "result": {"message_id": 1}}

            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
                "session_id": "integration-test",
            }

            # This should timeout and deny (1 second timeout)
            result = await handle_pretool_use(hook_input, mock_owl_dir)

            assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
            mock_api.assert_called()


@pytest.mark.asyncio
async def test_rule_based_auto_approve(mock_owl_dir):
    """Test that rules auto-approve without Telegram."""
    (mock_owl_dir / "mode").write_text("on")

    manager = ApprovalManager(owl_dir=mock_owl_dir)
    await manager.initialize()
    await manager.rules.add_rule("Read(*)", "approve")
    await manager.close()

    hook_input = {
        "tool_name": "Read",
        "tool_input": {"file_path": "/etc/passwd"},
        "session_id": "rule-test",
    }

    result = await handle_pretool_use(hook_input, mock_owl_dir)
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


@pytest.mark.asyncio
async def test_session_tracking(mock_owl_dir):
    """Test that sessions are tracked across requests."""
    (mock_owl_dir / "mode").write_text("on")

    manager = ApprovalManager(owl_dir=mock_owl_dir)
    await manager.initialize()
    await manager.rules.add_rule("*", "approve")

    await manager.request_approval(
        session_id="tracked-session",
        tool_name="Read",
        project_path="/home/user/project1",
    )

    await manager.request_approval(
        session_id="tracked-session",
        tool_name="Write",
        project_path="/home/user/project1",
    )

    session = await manager.storage.get_session("tracked-session")
    assert session is not None
    assert session.project_path == "/home/user/project1"

    log = await manager.storage.get_audit_log(limit=10)
    assert len(log) >= 2

    await manager.close()
