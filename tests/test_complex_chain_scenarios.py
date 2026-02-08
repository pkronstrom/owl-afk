"""Tests for complex command chain scenarios.

Tests edge cases and real-world complex commands.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from owl.core.command_parser import CommandParser, CommandType
from owl.core.manager import ApprovalManager
from owl.core.poller import Poller
from owl.notifiers.telegram import TelegramNotifier


class TestSSHWithNestedChains:
    """Test SSH wrapper commands with nested command chains."""

    def test_ssh_with_nested_chain_followed_by_local(self):
        """ssh aarni "cd /home && git fetch" && git status -> 2 nodes."""
        parser = CommandParser()
        cmd = 'ssh aarni "cd /home && git fetch" && git status'
        nodes = parser.parse(cmd)

        assert len(nodes) == 2

        # First node is SSH wrapper
        assert nodes[0].type == CommandType.WRAPPER
        assert nodes[0].name == "ssh"
        assert nodes[0].params.get("host") == "aarni"
        # SSH nested command should be first command in the quoted chain
        assert nodes[0].nested is not None
        assert nodes[0].nested.name == "cd"

        # Second node is local git status
        assert nodes[1].type == CommandType.VCS
        assert nodes[1].name == "git"
        assert nodes[1].args == ["status"]

    def test_ssh_with_complex_nested_chain(self):
        """Real-world example: git worktree cleanup via SSH."""
        parser = CommandParser()
        cmd = (
            "ssh aarni 'cd /home/user/project && "
            "git worktree remove .worktrees/foo --force 2>/dev/null || "
            "rm -rf .worktrees/foo'"
        )
        nodes = parser.parse(cmd)

        # Should be just 1 node - the ssh wrapper
        # The chain inside quotes is treated as nested command
        assert len(nodes) == 1
        assert nodes[0].type == CommandType.WRAPPER
        assert nodes[0].name == "ssh"
        assert nodes[0].params.get("host") == "aarni"

    def test_ssh_with_pipe_inside_quotes(self):
        """ssh aarni "cat file | grep pattern" -> pipe inside SSH."""
        parser = CommandParser()
        cmd = 'ssh aarni "cat file | grep pattern"'
        nodes = parser.parse(cmd)

        # Just 1 node - pipe is inside the quoted nested command
        assert len(nodes) == 1
        assert nodes[0].type == CommandType.WRAPPER
        assert nodes[0].name == "ssh"
        assert nodes[0].nested is not None
        assert nodes[0].nested.name == "cat"


class TestDockerExecScenarios:
    """Test Docker exec wrapper scenarios."""

    def test_docker_exec_with_bash_c(self):
        """docker exec app bash -c "npm install && npm test" -> docker wrapper."""
        parser = CommandParser()
        cmd = 'docker exec myapp bash -c "npm install && npm test"'
        nodes = parser.parse(cmd)

        assert len(nodes) == 1
        assert nodes[0].type == CommandType.WRAPPER
        assert nodes[0].name == "docker"
        assert nodes[0].params.get("action") == "exec"
        assert nodes[0].params.get("container") == "myapp"
        # Nested is bash command
        assert nodes[0].nested is not None
        assert nodes[0].nested.name == "bash"

    def test_docker_run_with_command(self):
        """docker exec myapp npm test && echo done -> 2 nodes."""
        parser = CommandParser()
        cmd = "docker exec myapp npm test && echo done"
        nodes = parser.parse(cmd)

        assert len(nodes) == 2
        assert nodes[0].type == CommandType.WRAPPER
        assert nodes[0].name == "docker"
        assert nodes[1].name == "echo"


class TestNestedWrappers:
    """Test deeply nested wrapper scenarios."""

    def test_ssh_with_sudo(self):
        """ssh host "sudo apt-get update" -> ssh wrapping sudo."""
        parser = CommandParser()
        cmd = 'ssh server "sudo apt-get update"'
        nodes = parser.parse(cmd)

        assert len(nodes) == 1
        assert nodes[0].type == CommandType.WRAPPER
        assert nodes[0].name == "ssh"
        # Nested command is sudo (also a wrapper)
        assert nodes[0].nested is not None
        assert nodes[0].nested.name == "sudo"
        assert nodes[0].nested.type == CommandType.WRAPPER
        # sudo wraps apt-get
        assert nodes[0].nested.nested is not None
        assert nodes[0].nested.nested.name == "apt-get"

    def test_ssh_with_docker(self):
        """ssh host "docker exec app npm test" -> ssh wrapping docker."""
        parser = CommandParser()
        cmd = 'ssh server "docker exec myapp npm test"'
        nodes = parser.parse(cmd)

        assert len(nodes) == 1
        assert nodes[0].type == CommandType.WRAPPER
        assert nodes[0].name == "ssh"
        # Nested is docker
        assert nodes[0].nested is not None
        assert nodes[0].nested.name == "docker"
        assert nodes[0].nested.type == CommandType.WRAPPER


class TestSimplifiedPatternMatching:
    """Test simplified pattern generation (max 3 patterns)."""

    def test_git_branch_progressive_patterns(self):
        """git branch -a --no-merged generates progressive patterns."""
        parser = CommandParser()
        node = parser.parse_single_command("git branch -a --no-merged")
        patterns = parser.generate_patterns(node)

        assert patterns[0] == "git branch -a --no-merged"
        assert "git branch -a --no-merged *" in patterns
        assert "git branch -a *" in patterns
        assert "git branch *" in patterns
        assert patterns[-1] == "git *"

    def test_npm_run_progressive_patterns(self):
        """npm run build --verbose generates progressive patterns."""
        parser = CommandParser()
        node = parser.parse_single_command("npm run build --verbose")
        patterns = parser.generate_patterns(node)

        assert patterns[0] == "npm run build --verbose"
        assert "npm run build --verbose *" in patterns
        assert "npm run build *" in patterns
        assert "npm run *" in patterns
        assert patterns[-1] == "npm *"

    def test_single_arg_command_patterns(self):
        """git status generates exact, first arg + *, and wildcard."""
        parser = CommandParser()
        node = parser.parse_single_command("git status")
        patterns = parser.generate_patterns(node)

        # With one arg, we get: exact, "git status *", "git *"
        assert len(patterns) == 3
        assert patterns[0] == "git status"
        assert patterns[1] == "git status *"
        assert patterns[2] == "git *"

    def test_ssh_wrapper_simplified_patterns(self):
        """ssh aarni git branch -a generates wrapper patterns at multiple levels."""
        parser = CommandParser()
        node = parser.parse_single_command("ssh aarni git branch -a")
        patterns = parser.generate_patterns(node)

        # Wrapper patterns at multiple specificity levels
        assert len(patterns) == 4
        assert patterns[0] == "ssh aarni git branch -a"
        assert patterns[1] == "ssh aarni git branch *"
        assert patterns[2] == "ssh aarni git *"
        assert patterns[3] == "ssh aarni *"


class TestMixedOperators:
    """Test chains with mixed shell operators."""

    def test_and_or_combination(self):
        """cmd1 && cmd2 || cmd3 -> 3 nodes."""
        parser = CommandParser()
        nodes = parser.parse("git fetch && git merge || echo 'failed'")

        assert len(nodes) == 3
        assert nodes[0].name == "git"
        assert nodes[0].args == ["fetch"]
        assert nodes[1].name == "git"
        assert nodes[1].args == ["merge"]
        assert nodes[2].name == "echo"

    def test_semicolon_and_ampersand(self):
        """cmd1 ; cmd2 && cmd3 -> 3 nodes."""
        parser = CommandParser()
        nodes = parser.parse("cd /tmp ; ls && pwd")

        assert len(nodes) == 3
        assert nodes[0].name == "cd"
        assert nodes[1].name == "ls"
        assert nodes[2].name == "pwd"

    def test_pipe_and_chain(self):
        """cmd1 | cmd2 && cmd3 -> 3 nodes."""
        parser = CommandParser()
        nodes = parser.parse("git log | head -10 && echo done")

        assert len(nodes) == 3
        assert nodes[0].name == "git"
        assert nodes[1].name == "head"
        assert nodes[2].name == "echo"


class TestQuoteEdgeCases:
    """Test various quoting edge cases."""

    def test_nested_quotes(self):
        """Command with nested quotes."""
        parser = CommandParser()
        # Single quotes inside double quotes
        cmd = "echo \"hello 'world'\" && ls"
        nodes = parser.parse(cmd)
        assert len(nodes) == 2

    def test_escaped_operators_in_string(self):
        """Operators in strings should not split."""
        parser = CommandParser()
        cmd = 'git commit -m "fix: && and || handling" && git push'
        nodes = parser.parse(cmd)

        assert len(nodes) == 2
        assert nodes[0].name == "git"
        assert "fix: && and || handling" in nodes[0].full_cmd
        assert nodes[1].name == "git"
        assert nodes[1].args == ["push"]


class TestRuleMatchingIntegration:
    """Test that patterns generated match commands correctly."""

    @pytest.mark.asyncio
    async def test_partial_pattern_matches(self, mock_owl_dir):
        """Test that git branch * matches git branch -a --no-merged."""
        manager = ApprovalManager(owl_dir=mock_owl_dir, timeout=0.5)
        await manager.initialize()

        notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
        manager.notifier = notifier
        manager.poller = Poller(manager.storage, notifier, mock_owl_dir)

        # Add rule for partial pattern
        await manager.rules.add_rule("Bash(git branch *)", "approve", priority=0)

        with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
            # Command that should match
            cmd = "git branch -a --no-merged"
            tool_input = json.dumps({"command": cmd})

            result, denial_reason = await manager.request_approval(
                session_id="session-123",
                tool_name="Bash",
                tool_input=tool_input,
                project_path="/home/user/project",
            )

            # Should auto-approve due to matching rule
            assert result == "approve"
            assert denial_reason is None
            # No Telegram message should be sent
            assert mock_api.call_count == 0

        await manager.close()

    @pytest.mark.asyncio
    async def test_ssh_wrapper_pattern_matches(self, mock_owl_dir):
        """Test that ssh aarni git * matches ssh aarni git log."""
        manager = ApprovalManager(owl_dir=mock_owl_dir, timeout=0.5)
        await manager.initialize()

        notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
        manager.notifier = notifier
        manager.poller = Poller(manager.storage, notifier, mock_owl_dir)

        # Add rule for ssh wrapper pattern
        await manager.rules.add_rule("Bash(ssh aarni git *)", "approve", priority=0)

        with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
            cmd = "ssh aarni git log --oneline"
            tool_input = json.dumps({"command": cmd})

            result, denial_reason = await manager.request_approval(
                session_id="session-123",
                tool_name="Bash",
                tool_input=tool_input,
                project_path="/home/user/project",
            )

            assert result == "approve"
            assert mock_api.call_count == 0

        await manager.close()

    @pytest.mark.asyncio
    async def test_chain_with_mixed_rule_coverage(self, mock_owl_dir):
        """Test chain where some commands have rules and some don't."""
        manager = ApprovalManager(owl_dir=mock_owl_dir, timeout=2.0)
        await manager.initialize()

        notifier = TelegramNotifier(bot_token="test-token", chat_id="12345")
        manager.notifier = notifier
        manager.poller = Poller(manager.storage, notifier, mock_owl_dir)

        # Add rules for ls and pwd, but NOT rm
        await manager.rules.add_rule("Bash(ls *)", "approve", priority=0)
        await manager.rules.add_rule("Bash(pwd)", "approve", priority=0)

        with patch.object(notifier, "_api_request", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"ok": True, "result": {"message_id": 42}}

            # rm has no rule, so this chain needs manual approval
            cmd = "ls -la && rm temp.txt && pwd"
            tool_input = json.dumps({"command": cmd})

            import asyncio

            async def approve_manually():
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

            # Manual approval was required because npm test has no rule
            assert result == "approve"
            # Telegram UI was shown
            assert mock_api.call_count > 0

        await manager.close()


class TestLongAndComplexChains:
    """Test very long or complex command chains."""

    def test_ten_command_chain(self):
        """Chain with 10 commands."""
        parser = CommandParser()
        commands = [f"cmd{i}" for i in range(10)]
        chain = " && ".join(commands)
        nodes = parser.parse(chain)

        assert len(nodes) == 10
        for i, node in enumerate(nodes):
            assert node.name == f"cmd{i}"

    def test_complex_deployment_script(self):
        """Real-world deployment-like chain."""
        parser = CommandParser()
        cmd = (
            "cd /app && "
            "git fetch origin && "
            "git checkout main && "
            "git pull && "
            "npm ci && "
            "npm run build && "
            "npm run test && "
            "pm2 restart app"
        )
        nodes = parser.parse(cmd)

        assert len(nodes) == 8
        assert nodes[0].name == "cd"
        assert nodes[1].name == "git"
        assert nodes[2].name == "git"
        assert nodes[3].name == "git"
        assert nodes[4].name == "npm"
        assert nodes[5].name == "npm"
        assert nodes[6].name == "npm"
        assert nodes[7].name == "pm2"
