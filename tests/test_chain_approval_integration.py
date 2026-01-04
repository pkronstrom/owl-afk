"""Integration tests for chain approval flow.

Tests the complete chain approval system from end-to-end, covering:
- Parsing multi-command chains
- Chain UI display and interaction
- Sequential approval workflow
- Rule creation within chains
- Auto-approval via chain rules
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from pyafk.core.manager import ApprovalManager
from pyafk.core.storage import Storage
from pyafk.core.rules import RulesEngine
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.core.poller import Poller
from pyafk.core.command_parser import CommandParser


@pytest.mark.asyncio
async def test_full_chain_approval_flow(mock_pyafk_dir):
    """Test complete chain approval workflow with sequential approvals."""
    # Setup manager with Telegram notifier - longer timeout for test
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=2.0)
    await manager.initialize()

    # Configure Telegram notifier
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Mock Telegram API calls
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        # Mock initial send returning message ID
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        # Create chain command
        chain_cmd = "cd ~/projects && npm test && git commit -m 'test'"
        tool_input = json.dumps({"command": chain_cmd})

        # Start approval request in background
        import asyncio

        async def approve_chain():
            """Simulate user approving each command in sequence."""
            # Very short delay to ensure request is created
            await asyncio.sleep(0.05)

            # Get the request
            pending = await manager.storage.get_pending_requests()
            assert len(pending) == 1
            request_id = pending[0].id

            # Simulate approving each command
            parser = CommandParser()
            commands = parser.split_chain(chain_cmd)
            assert len(commands) == 3

            # Initialize chain state
            chain_state = {
                "commands": commands,
                "approved_indices": [],
            }
            await manager.poller._save_chain_state(request_id, chain_state)

            # Approve each command
            for idx in range(len(commands)):
                chain_state["approved_indices"].append(idx)
                await manager.poller._save_chain_state(request_id, chain_state)

            # Final approval
            await manager.storage.resolve_request(
                request_id=request_id,
                status="approved",
                resolved_by="user",
            )

        # Run both tasks
        approval_task = asyncio.create_task(approve_chain())
        result_task = asyncio.create_task(
            manager.request_approval(
                session_id="session-123",
                tool_name="Bash",
                tool_input=tool_input,
                project_path="/home/user/project",
            )
        )

        result, denial_reason = await result_task
        await approval_task

        # Verify approval succeeded
        assert result == "approve"
        assert denial_reason is None

        # Verify chain approval UI was sent
        send_calls = [
            call for call in mock_api.call_args_list if "sendMessage" in str(call)
        ]
        assert len(send_calls) > 0
        send_data = send_calls[0][1]["data"]
        assert "Command chain approval:" in send_data["text"]

    await manager.close()


@pytest.mark.asyncio
async def test_chain_denial_flow(mock_pyafk_dir):
    """Test chain denial workflow."""
    # Setup manager with Telegram notifier
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=2.0)
    await manager.initialize()

    # Configure Telegram notifier
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Mock Telegram API calls
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        # Create chain command
        chain_cmd = "cd ~/projects && rm -rf node_modules && npm install"
        tool_input = json.dumps({"command": chain_cmd})

        # Start approval request in background
        import asyncio

        async def deny_chain():
            """Simulate user denying the chain."""
            await asyncio.sleep(0.05)

            # Get the request
            pending = await manager.storage.get_pending_requests()
            assert len(pending) == 1
            request_id = pending[0].id

            # Deny the request
            await manager.storage.resolve_request(
                request_id=request_id,
                status="denied",
                resolved_by="user",
            )

        # Run both tasks
        denial_task = asyncio.create_task(deny_chain())
        result_task = asyncio.create_task(
            manager.request_approval(
                session_id="session-123",
                tool_name="Bash",
                tool_input=tool_input,
                project_path="/home/user/project",
            )
        )

        result, denial_reason = await result_task
        await denial_task

        # Verify denial succeeded
        assert result == "deny"
        assert denial_reason is None

        # Verify chain approval UI was sent
        send_calls = [
            call for call in mock_api.call_args_list if "sendMessage" in str(call)
        ]
        assert len(send_calls) > 0
        send_data = send_calls[0][1]["data"]
        assert "Command chain approval:" in send_data["text"]

    await manager.close()


@pytest.mark.asyncio
async def test_chain_rule_creation(mock_pyafk_dir):
    """Test creating a rule for one command in a chain."""
    # Setup manager with Telegram notifier
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=2.0)
    await manager.initialize()

    # Configure Telegram notifier
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Mock Telegram API calls
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        # Create chain command
        chain_cmd = "git status && git diff && git log"
        tool_input = json.dumps({"command": chain_cmd})

        # Start approval request in background
        import asyncio

        async def approve_with_rule():
            """Simulate user creating rule for first command and approving rest."""
            await asyncio.sleep(0.05)

            # Get the request
            pending = await manager.storage.get_pending_requests()
            assert len(pending) == 1
            request_id = pending[0].id

            # Initialize chain state
            parser = CommandParser()
            commands = parser.split_chain(chain_cmd)
            chain_state = {
                "commands": commands,
                "approved_indices": [],
            }
            await manager.poller._save_chain_state(request_id, chain_state)

            # Create rule for first command (git status)
            engine = RulesEngine(manager.storage)
            await engine.add_rule(
                "Bash(git status)", "approve", priority=0, created_via="telegram"
            )

            # Mark first command as approved
            chain_state["approved_indices"].append(0)
            await manager.poller._save_chain_state(request_id, chain_state)

            # Approve remaining commands
            for idx in range(1, len(commands)):
                chain_state["approved_indices"].append(idx)
                await manager.poller._save_chain_state(request_id, chain_state)

            # Final approval
            await manager.storage.resolve_request(
                request_id=request_id,
                status="approved",
                resolved_by="user",
            )

        # Run both tasks
        approval_task = asyncio.create_task(approve_with_rule())
        result_task = asyncio.create_task(
            manager.request_approval(
                session_id="session-123",
                tool_name="Bash",
                tool_input=tool_input,
                project_path="/home/user/project",
            )
        )

        result, denial_reason = await result_task
        await approval_task

        # Verify approval succeeded
        assert result == "approve"
        assert denial_reason is None

        # Verify rule was created
        rules = await manager.rules.list_rules()
        rule_patterns = [r["pattern"] for r in rules]
        assert "Bash(git status)" in rule_patterns

    await manager.close()


@pytest.mark.asyncio
async def test_chain_auto_approval_via_rules(mock_pyafk_dir):
    """Test auto-approval of chain when all commands match rules."""
    # Setup manager
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=0.5)
    await manager.initialize()

    # Configure Telegram notifier (even though we won't need it)
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Create rules for all commands in the chain
    await manager.rules.add_rule("Bash(git status)", "approve", priority=0)
    await manager.rules.add_rule("Bash(git diff)", "approve", priority=0)
    await manager.rules.add_rule("Bash(git log)", "approve", priority=0)

    # Mock Telegram to ensure it's NOT called
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        # Create chain command that matches all rules
        chain_cmd = "git status && git diff && git log"
        tool_input = json.dumps({"command": chain_cmd})

        result, denial_reason = await manager.request_approval(
            session_id="session-123",
            tool_name="Bash",
            tool_input=tool_input,
            project_path="/home/user/project",
        )

        # Verify auto-approval
        assert result == "approve"
        assert denial_reason is None

        # Verify NO Telegram message was sent
        assert mock_api.call_count == 0

    await manager.close()


@pytest.mark.asyncio
async def test_chain_partial_auto_approval(mock_pyafk_dir):
    """Test that chain requires manual approval if any command doesn't match rules."""
    # Setup manager
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=2.0)
    await manager.initialize()

    # Configure Telegram notifier
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Create rules for only SOME commands
    await manager.rules.add_rule("Bash(git status)", "approve", priority=0)
    # No rule for "npm test"
    await manager.rules.add_rule("Bash(git commit *)", "approve", priority=0)

    # Mock Telegram API
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        # Create chain with one unmatched command
        chain_cmd = "git status && npm test && git commit -m 'test'"
        tool_input = json.dumps({"command": chain_cmd})

        import asyncio

        async def approve_manually():
            """Manually approve the request."""
            await asyncio.sleep(0.05)
            pending = await manager.storage.get_pending_requests()
            if pending:
                await manager.storage.resolve_request(
                    request_id=pending[0].id,
                    status="approved",
                    resolved_by="user",
                )

        approval_task = asyncio.create_task(approve_manually())
        result_task = asyncio.create_task(
            manager.request_approval(
                session_id="session-123",
                tool_name="Bash",
                tool_input=tool_input,
                project_path="/home/user/project",
            )
        )

        result, denial_reason = await result_task
        await approval_task

        # Verify manual approval was required
        assert result == "approve"

        # Verify Telegram UI WAS shown (because not all commands matched)
        send_calls = [
            call for call in mock_api.call_args_list if "sendMessage" in str(call)
        ]
        assert len(send_calls) > 0
        send_data = send_calls[0][1]["data"]
        assert "Command chain approval:" in send_data["text"]

    await manager.close()


@pytest.mark.asyncio
async def test_chain_deny_rule_blocks_entire_chain(mock_pyafk_dir):
    """Test that a deny rule for any command denies the entire chain."""
    # Setup manager
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=0.5)
    await manager.initialize()

    # Configure Telegram notifier
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Create allow rules for some commands, deny rule for one
    await manager.rules.add_rule("Bash(cd *)", "approve", priority=0)
    await manager.rules.add_rule("Bash(rm -rf *)", "deny", priority=0)  # DENY
    await manager.rules.add_rule("Bash(npm install)", "approve", priority=0)

    # Mock Telegram to ensure it's NOT called
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        # Create chain with one denied command
        chain_cmd = "cd ~/projects && rm -rf node_modules && npm install"
        tool_input = json.dumps({"command": chain_cmd})

        result, denial_reason = await manager.request_approval(
            session_id="session-123",
            tool_name="Bash",
            tool_input=tool_input,
            project_path="/home/user/project",
        )

        # Verify auto-denial
        assert result == "deny"

        # Verify NO Telegram message was sent
        assert mock_api.call_count == 0

    await manager.close()


@pytest.mark.asyncio
async def test_parser_integration_with_chains(mock_pyafk_dir):
    """Test that complex commands are properly parsed into chains."""
    # Setup parser
    parser = CommandParser()

    # Test various chain formats
    test_cases = [
        ("cmd1 && cmd2", ["cmd1", "cmd2"]),
        ("cmd1 || cmd2", ["cmd1", "cmd2"]),
        ("cmd1 ; cmd2", ["cmd1", "cmd2"]),
        ("cmd1 | cmd2", ["cmd1", "cmd2"]),
        ("cmd1 && cmd2 || cmd3", ["cmd1", "cmd2", "cmd3"]),
        (
            'echo "test && skip" && real_cmd',
            ['echo "test && skip"', "real_cmd"],
        ),  # Quote handling
        ("cmd1 && cmd2 && cmd3 && cmd4", ["cmd1", "cmd2", "cmd3", "cmd4"]),
    ]

    for cmd, expected_commands in test_cases:
        result = parser.split_chain(cmd)
        assert result == expected_commands, f"Failed for: {cmd}"


@pytest.mark.asyncio
async def test_wrapper_command_in_chain(mock_pyafk_dir):
    """Test that wrapper commands within chains are handled correctly."""
    # Setup manager
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=0.5)
    await manager.initialize()

    # Configure Telegram notifier
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Create rule for wrapper command
    await manager.rules.add_rule("Bash(sudo apt-get update)", "approve", priority=0)
    await manager.rules.add_rule("Bash(sudo apt-get install *)", "approve", priority=0)

    # Mock Telegram
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        # Chain with wrapper commands
        chain_cmd = "sudo apt-get update && sudo apt-get install vim"
        tool_input = json.dumps({"command": chain_cmd})

        result, denial_reason = await manager.request_approval(
            session_id="session-123",
            tool_name="Bash",
            tool_input=tool_input,
            project_path="/home/user/project",
        )

        # Verify auto-approval (both wrapper commands matched rules)
        assert result == "approve"
        assert denial_reason is None

        # Verify NO Telegram message
        assert mock_api.call_count == 0

    await manager.close()


@pytest.mark.asyncio
async def test_single_command_not_treated_as_chain(mock_pyafk_dir):
    """Test that single commands are NOT treated as chains."""
    # Setup manager
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=2.0)
    await manager.initialize()

    # Configure Telegram notifier
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Mock Telegram API
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        # Single command (no chain operators)
        single_cmd = "git status"
        tool_input = json.dumps({"command": single_cmd})

        import asyncio

        async def approve_manually():
            """Manually approve the request."""
            await asyncio.sleep(0.05)
            pending = await manager.storage.get_pending_requests()
            if pending:
                await manager.storage.resolve_request(
                    request_id=pending[0].id,
                    status="approved",
                    resolved_by="user",
                )

        approval_task = asyncio.create_task(approve_manually())
        result_task = asyncio.create_task(
            manager.request_approval(
                session_id="session-123",
                tool_name="Bash",
                tool_input=tool_input,
                project_path="/home/user/project",
            )
        )

        result, denial_reason = await result_task
        await approval_task

        assert result == "approve"

        # Verify REGULAR approval UI was sent (not chain UI)
        send_calls = [
            call for call in mock_api.call_args_list if "sendMessage" in str(call)
        ]
        assert len(send_calls) > 0
        send_data = send_calls[0][1]["data"]
        # Should NOT have chain UI
        assert "Command chain approval:" not in send_data["text"]
        # Should have regular UI
        assert "[Bash]" in send_data["text"]

    await manager.close()


@pytest.mark.asyncio
async def test_empty_chain_handling(mock_pyafk_dir):
    """Test handling of edge case: empty or whitespace-only commands."""
    # Setup parser
    parser = CommandParser()

    # Empty command
    result = parser.split_chain("")
    assert result == []

    # Only whitespace
    result = parser.split_chain("   ")
    assert result == []

    # Chain with empty parts (multiple semicolons)
    result = parser.split_chain("cmd1 ;; cmd2")
    assert result == ["cmd1", "cmd2"]


@pytest.mark.asyncio
async def test_chain_state_persistence(mock_pyafk_dir):
    """Test that chain approval state persists across poller interactions."""
    # Setup storage and poller
    storage = Storage(mock_pyafk_dir / "test.db")
    await storage.connect()

    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    poller = Poller(storage, notifier, mock_pyafk_dir)

    # Create chain state
    request_id = "req-123"
    chain_state = {
        "commands": ["cmd1", "cmd2", "cmd3"],
        "approved_indices": [0, 1],
    }

    # Save state
    await poller._save_chain_state(request_id, chain_state)

    # Retrieve state
    retrieved_state = await poller._get_chain_state(request_id)
    assert retrieved_state == chain_state

    # Clear state
    await poller._clear_chain_state(request_id)
    cleared_state = await poller._get_chain_state(request_id)
    assert cleared_state is None

    await storage.close()


@pytest.mark.asyncio
async def test_pattern_generation_for_chain_commands(mock_pyafk_dir):
    """Test that pattern generation works correctly for chain commands."""
    parser = CommandParser()

    # Parse a complex chain
    chain_cmd = "cd ~/projects && npm test && git commit -m 'test'"
    nodes = parser.parse(chain_cmd)

    assert len(nodes) == 3

    # Test pattern generation for each node
    for node in nodes:
        patterns = parser.generate_patterns(node)
        assert len(patterns) >= 2  # At least full command and wildcard
        assert node.full_cmd in patterns  # Exact command should be included
        assert any("*" in p for p in patterns)  # Wildcard pattern should be included


@pytest.mark.asyncio
async def test_chain_with_quoted_arguments(mock_pyafk_dir):
    """Test chain handling with complex quoted arguments."""
    # Setup manager
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=0.5)
    await manager.initialize()

    # Configure Telegram notifier
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Create rule for git commit with wildcard
    await manager.rules.add_rule("Bash(git commit *)", "approve", priority=0)
    await manager.rules.add_rule("Bash(git push)", "approve", priority=0)

    # Mock Telegram
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        # Chain with quoted arguments
        chain_cmd = 'git commit -m "feat: add new feature" && git push'
        tool_input = json.dumps({"command": chain_cmd})

        result, denial_reason = await manager.request_approval(
            session_id="session-123",
            tool_name="Bash",
            tool_input=tool_input,
            project_path="/home/user/project",
        )

        # Verify auto-approval
        assert result == "approve"
        assert denial_reason is None

        # Verify NO Telegram message
        assert mock_api.call_count == 0

    await manager.close()


@pytest.mark.asyncio
async def test_long_chain_truncation_in_ui(mock_pyafk_dir):
    """Test that very long chains are properly truncated in Telegram UI."""
    # Setup manager
    manager = ApprovalManager(pyafk_dir=mock_pyafk_dir, timeout=2.0)
    await manager.initialize()

    # Configure Telegram notifier
    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
    manager.notifier = notifier
    manager.poller = Poller(manager.storage, notifier, mock_pyafk_dir)

    # Mock Telegram API
    with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

        # Create a very long chain (50 commands)
        commands = [f"echo 'step {i}'" for i in range(50)]
        chain_cmd = " && ".join(commands)
        tool_input = json.dumps({"command": chain_cmd})

        import asyncio

        async def approve_manually():
            """Manually approve the request."""
            await asyncio.sleep(0.05)
            pending = await manager.storage.get_pending_requests()
            if pending:
                await manager.storage.resolve_request(
                    request_id=pending[0].id,
                    status="approved",
                    resolved_by="user",
                )

        approval_task = asyncio.create_task(approve_manually())
        result_task = asyncio.create_task(
            manager.request_approval(
                session_id="session-123",
                tool_name="Bash",
                tool_input=tool_input,
                project_path="/home/user/project",
            )
        )

        result, denial_reason = await result_task
        await approval_task

        assert result == "approve"

        # Verify message was sent and check length
        send_calls = [
            call for call in mock_api.call_args_list if "sendMessage" in str(call)
        ]
        assert len(send_calls) > 0
        send_data = send_calls[0][1]["data"]
        text = send_data["text"]

        # Telegram limit is 4096 chars
        assert len(text) < 4096

    await manager.close()
