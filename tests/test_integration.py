"""End-to-end integration tests."""

import json
import pytest
from unittest.mock import patch, AsyncMock

from pyafk.core.manager import ApprovalManager
from pyafk.hooks.pretool import handle_pretool_use


@pytest.mark.asyncio
async def test_full_approval_flow(mock_pyafk_dir):
    """Test complete approval flow from hook to response."""
    (mock_pyafk_dir / "mode").write_text("on")

    config_data = {
        "telegram_bot_token": "test-token",
        "telegram_chat_id": "12345",
        "timeout_seconds": 1,
        "timeout_action": "deny",
    }
    (mock_pyafk_dir / "config.json").write_text(json.dumps(config_data))

    # Patch ApprovalManager to use short timeout from config
    original_init = ApprovalManager.__init__

    def patched_init(self, pyafk_dir=None, timeout=3600, timeout_action="deny", config=None):
        # Read config to get timeout settings
        from pyafk.utils.config import Config
        cfg = Config(pyafk_dir)
        original_init(
            self,
            pyafk_dir=pyafk_dir,
            timeout=cfg.timeout_seconds,
            timeout_action=cfg.timeout_action,
            config=cfg,
        )

    with patch.object(ApprovalManager, "__init__", patched_init):
        with patch("pyafk.notifiers.telegram.TelegramNotifier._api_request") as mock_api:
            mock_api.return_value = {"ok": True, "result": {"message_id": 1}}

            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
                "session_id": "integration-test",
            }

            # This should timeout and deny (1 second timeout)
            result = await handle_pretool_use(hook_input, mock_pyafk_dir)

            assert result["decision"] == "deny"
            mock_api.assert_called()


@pytest.mark.asyncio
async def test_rule_based_auto_approve(mock_pyafk_dir):
    """Test that rules auto-approve without Telegram."""
    (mock_pyafk_dir / "mode").write_text("on")

    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
    await manager.initialize()
    await manager.rules.add_rule("Read(*)", "approve")
    await manager.close()

    hook_input = {
        "tool_name": "Read",
        "tool_input": {"file_path": "/etc/passwd"},
        "session_id": "rule-test",
    }

    result = await handle_pretool_use(hook_input, mock_pyafk_dir)
    assert result["decision"] == "approve"


@pytest.mark.asyncio
async def test_session_tracking(mock_pyafk_dir):
    """Test that sessions are tracked across requests."""
    (mock_pyafk_dir / "mode").write_text("on")

    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir)
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
