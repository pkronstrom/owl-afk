"""Approval Manager - the core API."""

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from owl.core.poller import Poller
from owl.core.rules import RulesEngine
from owl.core.storage import Storage
from owl.notifiers.base import Notifier
from owl.notifiers.console import ConsoleNotifier
from owl.notifiers.telegram import TelegramNotifier
from owl.utils.config import Config, get_owl_dir
from owl.utils.debug import debug_chain


@dataclass
class RuleCheckResult:
    """Result of checking rules for a tool call."""

    rule_result: Optional[str]  # "approve", "deny", or None
    is_chain: bool
    chain_commands: list[str]
    chain_title: Optional[str] = None  # Custom title for compound commands


class ApprovalManager:
    """Main API for requesting approvals."""

    def __init__(
        self,
        owl_dir: Optional[Path] = None,
        timeout: int = 3600,
        timeout_action: str = "deny",
        config: Optional[Config] = None,
    ):
        self.owl_dir = owl_dir or get_owl_dir()
        self.timeout = timeout
        self.timeout_action = timeout_action
        self._config = config

        self.storage: Optional[Storage] = None
        self.rules: Optional[RulesEngine] = None
        self.notifier: Optional[Notifier] = None
        self.poller: Optional[Poller] = None
        self._initialized = False

    async def initialize(self):
        """Initialize storage and components."""
        if self._initialized:
            return

        try:
            self.owl_dir.mkdir(parents=True, exist_ok=True)

            if not self._config:
                self._config = Config(self.owl_dir)

            self.storage = Storage(self._config.db_path)
            await self.storage.connect()

            self.rules = RulesEngine(self.storage)

            if self._config.telegram_bot_token and self._config.telegram_chat_id:
                self.notifier = TelegramNotifier(
                    bot_token=self._config.telegram_bot_token,
                    chat_id=self._config.telegram_chat_id,
                    timeout=self.timeout,
                    timeout_action=self.timeout_action,
                )
                self.poller = Poller(self.storage, self.notifier, self.owl_dir)
            else:
                self.notifier = ConsoleNotifier()
                self.poller = None

            self._initialized = True
        except Exception:
            await self.close()
            raise

    async def close(self):
        """Close connections."""
        if self.storage:
            await self.storage.close()
            self.storage = None
        self._initialized = False

    async def _check_rules(
        self, tool_name: str, tool_input: Optional[str]
    ) -> RuleCheckResult:
        """Check rules for a tool call.

        For Bash commands, uses chain rule checking which validates
        each command in a chain individually. Also detects compound commands
        (for/while/if) and treats their inner commands like chains.

        Returns:
            RuleCheckResult with rule_result, is_chain flag, chain_commands, and chain_title
        """
        rule_result = None
        is_chain = False
        chain_commands: list[str] = []
        chain_title: Optional[str] = None

        debug_chain("Processing approval request", tool_name=tool_name)

        if tool_name == "Bash" and tool_input:
            from owl.core.command_parser import CommandParser, CommandType
            from owl.core.handlers.chain import check_chain_rules

            try:
                data = json.loads(tool_input)
                if "command" in data:
                    cmd = data["command"]
                    debug_chain("Bash command", cmd=cmd[:100])

                    # Use chain rule checking
                    rule_result = await check_chain_rules(self.storage, cmd)
                    debug_chain("Chain rule check result", rule_result=rule_result)

                    # Check if this is actually a chain (multiple commands)
                    parser = CommandParser()
                    chain_commands = parser.split_chain(cmd)
                    debug_chain(
                        "Split chain result",
                        count=len(chain_commands),
                        commands=chain_commands[:3],
                    )

                    # Check for compound commands (for/while/if) - treat as chain
                    if len(chain_commands) == 1:
                        node = parser.parse_single_command(chain_commands[0])
                        if node.type == CommandType.COMPOUND and node.compound:
                            # Extract inner commands for chain-style approval
                            inner_cmds = [c.full_cmd for c in node.compound.body_commands]
                            if node.compound.else_commands:
                                inner_cmds.extend([c.full_cmd for c in node.compound.else_commands])

                            if inner_cmds:
                                chain_commands = inner_cmds
                                is_chain = True
                                # Set custom title based on compound type
                                info = parser.get_compound_display_info(node)
                                if info:
                                    chain_title = f"{info['type'].capitalize()}: {info['description']}"
                                debug_chain(
                                    "Detected compound command",
                                    type=node.compound.compound_type.value,
                                    inner_count=len(inner_cmds),
                                )

                    if len(chain_commands) > 1 and not is_chain:
                        is_chain = True
                        debug_chain("Detected as chain")
            except (json.JSONDecodeError, TypeError) as e:
                debug_chain("Failed to parse tool_input", error=str(e))

        # If no chain result, use regular rule checking
        # But NOT for chains - chain rules must match all commands individually
        if rule_result is None and not is_chain:
            rule_result = await self.rules.check(tool_name, tool_input)

        return RuleCheckResult(
            rule_result=rule_result,
            is_chain=is_chain,
            chain_commands=chain_commands,
            chain_title=chain_title,
        )

    async def _get_chain_approved_indices(self, commands: list[str]) -> list[int]:
        """Check which chain commands are pre-approved by existing rules.

        Returns list of indices for commands that match approval rules.
        """
        if not self.rules:
            return []

        approved_indices: list[int] = []
        for idx, cmd in enumerate(commands):
            cmd_input = json.dumps({"command": cmd})
            rule_result = await self.rules.check("Bash", cmd_input)
            if rule_result == "approve":
                approved_indices.append(idx)

        return approved_indices

    async def _send_notification(
        self,
        request_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str],
        context: Optional[str],
        description: Optional[str],
        project_path: Optional[str],
        is_chain: bool,
        chain_commands: list[str],
        chain_title: Optional[str] = None,
    ) -> Optional[int]:
        """Send approval notification via the configured notifier.

        Uses chain approval UI for multi-command Bash chains when using
        Telegram, otherwise uses the regular approval UI.

        Returns:
            Message ID from notifier, or None
        """
        if is_chain and chain_commands and isinstance(self.notifier, TelegramNotifier):
            # Pre-check which commands are already approved by rules
            approved_indices = await self._get_chain_approved_indices(chain_commands)
            debug_chain(
                "Using chain approval UI",
                command_count=len(chain_commands),
                pre_approved=len(approved_indices),
                chain_title=chain_title,
            )
            return await self.notifier.send_chain_approval_request(
                request_id=request_id,
                session_id=session_id,
                commands=chain_commands,
                project_path=project_path,
                description=description,
                approved_indices=approved_indices,
                chain_title=chain_title,
            )
        else:
            debug_chain(
                "Using regular approval UI",
                is_chain=is_chain,
                has_commands=bool(chain_commands),
                is_telegram=isinstance(self.notifier, TelegramNotifier),
            )
            return await self.notifier.send_approval_request(
                request_id=request_id,
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                context=context,
                description=description,
                project_path=project_path,
            )

    async def request_approval(
        self,
        session_id: str,
        tool_name: str,
        tool_input: Optional[str] = None,
        context: Optional[str] = None,
        description: Optional[str] = None,
        project_path: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        """Request approval for a tool call.

        Returns:
            Tuple of (decision, denial_reason) where decision is "approve" or "deny"
        """
        if not self._initialized:
            await self.initialize()

        await self.storage.upsert_session(
            session_id=session_id,
            project_path=project_path,
        )

        # Check rules (handles both chain and regular commands)
        check_result = await self._check_rules(tool_name, tool_input)

        if check_result.rule_result:
            # Send auto-approval notification if enabled
            if (
                check_result.rule_result == "approve"
                and self._config.auto_approve_notify
            ):
                from owl.utils.formatting import format_auto_approval_message

                msg = format_auto_approval_message(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    project_path=project_path,
                    session_id=session_id,
                )
                await self.notifier.send_info_message(msg)

            await self.storage.log_audit(
                event_type="auto_response",
                session_id=session_id,
                details={
                    "tool_name": tool_name,
                    "action": check_result.rule_result,
                    "reason": "rule_match",
                },
            )
            return (check_result.rule_result, None)

        # Check for duplicate pending request (handles multiple hooks calling owl)
        existing = await self.storage.find_duplicate_pending_request(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
        )
        if existing:
            debug_chain(
                "Found duplicate pending request, waiting for existing",
                existing_id=existing.id[:8],
            )
            return await self._wait_for_response(existing.id)

        # Create request and send notification
        request_id = await self.storage.create_request(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
            description=description,
        )

        msg_id = await self._send_notification(
            request_id=request_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
            description=description,
            project_path=project_path,
            is_chain=check_result.is_chain,
            chain_commands=check_result.chain_commands,
            chain_title=check_result.chain_title,
        )

        if msg_id:
            await self.storage.set_telegram_msg_id(request_id, msg_id)

        await self.storage.log_audit(
            event_type="request",
            session_id=session_id,
            details={"request_id": request_id, "tool_name": tool_name},
        )

        return await self._wait_for_response(request_id)

    async def _wait_for_response(self, request_id: str) -> tuple[str, Optional[str]]:
        """Wait for approval response with polling.

        One hook becomes the "polling leader" and polls Telegram for ALL pending
        requests. Other hooks just check the database.

        Returns:
            Tuple of (decision, denial_reason)
        """
        start = time.monotonic()
        poll_task: Optional[asyncio.Task[bool]] = None

        # Start leader polling in background
        grace_period = self._config.polling_grace_period if self._config else 900.0
        if self.poller:
            poll_task = asyncio.create_task(
                self.poller.poll_as_leader(request_id, grace_period=grace_period)
            )

        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= self.timeout:
                    status = (
                        "approved" if self.timeout_action == "approve" else "denied"
                    )
                    await self.storage.resolve_request(
                        request_id=request_id,
                        status=status,
                        resolved_by="timeout",
                    )
                    await self.storage.log_audit(
                        event_type="timeout",
                        details={
                            "request_id": request_id,
                            "action": self.timeout_action,
                        },
                    )
                    return (self.timeout_action, None)

                # If poll task finished (either we were leader and done, or couldn't
                # become leader), try to become leader again
                if poll_task is not None and poll_task.done():
                    poll_task = asyncio.create_task(
                        self.poller.poll_as_leader(
                            request_id, grace_period=grace_period
                        )
                    )

                # Check our request status in database
                # (The leader poll task updates DB for ALL requests)
                request = await self.storage.get_request(request_id)
                if request and request.status != "pending":
                    if request.status == "approved":
                        return ("approve", None)
                    elif request.status == "fallback":
                        return ("fallback", None)
                    else:
                        return ("deny", request.denial_reason)

                await asyncio.sleep(0.5)
        finally:
            # Cancel poll task if still running
            # Another waiting hook will become the new leader
            if poll_task and not poll_task.done():
                poll_task.cancel()
                try:
                    await poll_task
                except asyncio.CancelledError:
                    pass
