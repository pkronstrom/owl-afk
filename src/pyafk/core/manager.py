"""Approval Manager - the core API."""

import asyncio
import time
from pathlib import Path
from typing import Optional

from pyafk.core.poller import Poller
from pyafk.core.rules import RulesEngine
from pyafk.core.storage import Storage
from pyafk.notifiers.base import Notifier
from pyafk.notifiers.console import ConsoleNotifier
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.config import Config, get_pyafk_dir
from pyafk.utils.debug import debug_chain, debug_rule


class ApprovalManager:
    """Main API for requesting approvals."""

    def __init__(
        self,
        pyafk_dir: Optional[Path] = None,
        timeout: int = 3600,
        timeout_action: str = "deny",
        config: Optional[Config] = None,
    ):
        self.pyafk_dir = pyafk_dir or get_pyafk_dir()
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
            self.pyafk_dir.mkdir(parents=True, exist_ok=True)

            if not self._config:
                self._config = Config(self.pyafk_dir)

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
                self.poller = Poller(self.storage, self.notifier, self.pyafk_dir)
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

        # For Bash commands with chains, use chain rule checking
        rule_result = None
        is_chain = False
        chain_commands = []

        debug_chain(f"Processing approval request", tool_name=tool_name)
        if tool_name == "Bash" and tool_input:
            import json
            try:
                data = json.loads(tool_input)
                if "command" in data:
                    cmd = data["command"]
                    debug_chain(f"Bash command", cmd=cmd[:100])
                    # Use chain rule checking if poller is available
                    if self.poller:
                        rule_result = await self.poller._check_chain_rules(cmd)
                        debug_chain(f"Chain rule check result", rule_result=rule_result)

                        # Check if this is actually a chain (multiple commands)
                        from pyafk.core.command_parser import CommandParser
                        parser = CommandParser()
                        # Use split_chain to get the individual command strings
                        chain_commands = parser.split_chain(cmd)
                        debug_chain(f"Split chain result", count=len(chain_commands), commands=chain_commands[:3])
                        if len(chain_commands) > 1:
                            is_chain = True
                            debug_chain(f"Detected as chain")
            except (json.JSONDecodeError, TypeError) as e:
                debug_chain(f"Failed to parse tool_input", error=str(e))
                pass

        # If no chain result, use regular rule checking
        # But NOT for chains - chain rules must match all commands individually
        if rule_result is None and not is_chain:
            rule_result = await self.rules.check(tool_name, tool_input)

        if rule_result:
            await self.storage.log_audit(
                event_type="auto_response",
                session_id=session_id,
                details={
                    "tool_name": tool_name,
                    "action": rule_result,
                    "reason": "rule_match",
                },
            )
            return (rule_result, None)

        request_id = await self.storage.create_request(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
            description=description,
        )

        # Use chain approval UI for multi-command chains
        if is_chain and chain_commands and isinstance(self.notifier, TelegramNotifier):
            debug_chain(f"Using chain approval UI", command_count=len(chain_commands))
            msg_id = await self.notifier.send_chain_approval_request(
                request_id=request_id,
                session_id=session_id,
                commands=chain_commands,
                project_path=project_path,
                description=description,
            )
        else:
            debug_chain(f"Using regular approval UI", is_chain=is_chain, has_commands=bool(chain_commands), is_telegram=isinstance(self.notifier, TelegramNotifier))
            # Use regular approval UI
            msg_id = await self.notifier.send_approval_request(
                request_id=request_id,
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                context=context,
                description=description,
                project_path=project_path,
            )

        if msg_id:
            await self.storage.set_telegram_msg_id(request_id, msg_id)

        await self.storage.log_audit(
            event_type="request",
            session_id=session_id,
            details={"request_id": request_id, "tool_name": tool_name},
        )

        result = await self._wait_for_response(request_id)
        return result

    async def _wait_for_response(self, request_id: str) -> tuple[str, Optional[str]]:
        """Wait for approval response with polling.

        Returns:
            Tuple of (decision, denial_reason)
        """
        start = time.monotonic()

        while True:
            elapsed = time.monotonic() - start
            if elapsed >= self.timeout:
                status = "approved" if self.timeout_action == "approve" else "denied"
                await self.storage.resolve_request(
                    request_id=request_id,
                    status=status,
                    resolved_by="timeout",
                )
                await self.storage.log_audit(
                    event_type="timeout",
                    details={"request_id": request_id, "action": self.timeout_action},
                )
                return (self.timeout_action, None)

            if self.poller:
                try:
                    await self.poller.process_updates_once()
                except Exception:
                    pass  # Continue polling even if one iteration fails

            request = await self.storage.get_request(request_id)
            if request and request.status != "pending":
                if request.status == "approved":
                    return ("approve", None)
                elif request.status == "fallback":
                    return ("fallback", None)
                else:
                    return ("deny", request.denial_reason)

            await asyncio.sleep(0.5)
