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
    ) -> str:
        """Request approval for a tool call.

        Returns:
            "approve" or "deny"
        """
        if not self._initialized:
            await self.initialize()

        await self.storage.upsert_session(
            session_id=session_id,
            project_path=project_path,
        )

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
            return rule_result

        request_id = await self.storage.create_request(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
            description=description,
        )

        msg_id = await self.notifier.send_approval_request(
            request_id=request_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
            description=description,
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

    async def _wait_for_response(self, request_id: str) -> str:
        """Wait for approval response with polling."""
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
                return self.timeout_action

            if self.poller:
                try:
                    await self.poller.process_updates_once()
                except Exception:
                    pass  # Continue polling even if one iteration fails

            request = await self.storage.get_request(request_id)
            if request and request.status != "pending":
                if request.status == "approved":
                    return "approve"
                else:
                    return "deny"

            await asyncio.sleep(0.5)
