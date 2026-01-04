"""Telegram poller with file-based locking."""

import asyncio
import fcntl
import os
import time
from pathlib import Path
from typing import Optional

from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier


class PollLock:
    """File-based lock for single poller."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fd: Optional[int] = None

    async def acquire(self, timeout: float = 5.0) -> bool:
        """Try to acquire the lock.

        Returns True if acquired, False if timeout.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        start = time.monotonic()
        while True:
            try:
                self._fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_RDWR,
                )
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.ftruncate(self._fd, 0)
                os.write(self._fd, str(os.getpid()).encode())
                return True
            except (BlockingIOError, OSError):
                if self._fd is not None:
                    try:
                        os.close(self._fd)
                    except OSError:
                        pass
                    self._fd = None

                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    return False

                await asyncio.sleep(0.1)

    async def release(self):
        """Release the lock."""
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

            try:
                self.lock_path.unlink()
            except OSError:
                pass


class Poller:
    """Poll Telegram for callback responses."""

    def __init__(
        self,
        storage: Storage,
        notifier: TelegramNotifier,
        pyafk_dir: Path,
    ):
        self.storage = storage
        self.notifier = notifier
        self.lock = PollLock(pyafk_dir / "poll.lock")
        self._offset: Optional[int] = None
        self._running = False

    async def process_updates_once(self) -> int:
        """Process one batch of updates.

        Returns number of updates processed.
        """
        updates = await self.notifier.get_updates(
            offset=self._offset,
            timeout=1,
        )

        processed = 0
        for update in updates:
            self._offset = update["update_id"] + 1

            if "callback_query" in update:
                await self._handle_callback(update["callback_query"])
                processed += 1

        return processed

    async def _handle_callback(self, callback: dict):
        """Handle a callback query from inline button."""
        callback_id = callback["id"]
        data = callback.get("data", "")
        # Get message_id from callback for editing
        message_id = callback.get("message", {}).get("message_id")

        if ":" not in data:
            return

        action, target_id = data.split(":", 1)

        if action in ("approve", "deny"):
            await self._handle_approval(target_id, action, callback_id, message_id)
        elif action == "approve_all":
            # Format: approve_all:session_id:tool_name
            parts = target_id.split(":", 1)
            session_id = parts[0]
            tool_name = parts[1] if len(parts) > 1 else None
            await self._handle_approve_all(session_id, tool_name, callback_id)
        elif action == "add_rule":
            await self._handle_add_rule(target_id, callback_id, message_id)

    async def _handle_approval(
        self,
        request_id: str,
        action: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle approve/deny callback."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        status = "approved" if action == "approve" else "denied"

        await self.storage.resolve_request(
            request_id=request_id,
            status=status,
            resolved_by="user",
        )

        await self.notifier.answer_callback(
            callback_id,
            f"{'Approved' if action == 'approve' else 'Denied'}",
        )

        if request.telegram_msg_id:
            await self.notifier.edit_message(
                request.telegram_msg_id,
                f"{'Approved' if action == 'approve' else 'Denied'} {request.tool_name} - {status.upper()}",
            )

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": action,
                "resolved_by": "user",
            },
        )

    async def _handle_approve_all(self, session_id: str, tool_name: Optional[str], callback_id: str):
        """Approve all pending requests for a session and tool type."""
        pending = await self.storage.get_pending_requests()

        # Filter by session and tool type
        to_approve = [
            r for r in pending
            if r.session_id == session_id and (tool_name is None or r.tool_name == tool_name)
        ]

        for request in to_approve:
            await self.storage.resolve_request(
                request_id=request.id,
                status="approved",
                resolved_by="user:approve_all",
            )
            # Update the Telegram message
            if request.telegram_msg_id:
                await self.notifier.edit_message(
                    request.telegram_msg_id,
                    f"✅ APPROVED (all) - {request.tool_name}",
                )

        tool_label = tool_name or "all"
        await self.notifier.answer_callback(
            callback_id,
            f"Approved {len(to_approve)} {tool_label}",
        )

    async def _handle_add_rule(self, request_id: str, callback_id: str, message_id: Optional[int] = None):
        """Handle add rule button - creates auto-approve rule and approves request."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Create smart pattern from tool name and input
        pattern = self._create_rule_pattern(request.tool_name, request.tool_input)

        # Add the rule
        from pyafk.core.rules import RulesEngine
        engine = RulesEngine(self.storage)
        await engine.add_rule(pattern, "approve", priority=0, created_via="telegram")

        # Also approve this request
        await self.storage.resolve_request(
            request_id=request_id,
            status="approved",
            resolved_by="user:add_rule",
        )

        # Update the message
        if request.telegram_msg_id:
            await self.notifier.edit_message(
                request.telegram_msg_id,
                f"✅ APPROVED + Rule: {pattern}",
            )

        await self.notifier.answer_callback(
            callback_id,
            f"Rule: {pattern}",
        )

    def _create_rule_pattern(self, tool_name: str, tool_input: Optional[str]) -> str:
        """Create a smart rule pattern from tool and input."""
        import json

        if not tool_input:
            return f"{tool_name}(*)"

        try:
            data = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            return f"{tool_name}(*)"

        # For Bash, extract command prefix (first word)
        if tool_name == "Bash" and "command" in data:
            cmd = data["command"].strip()
            first_word = cmd.split()[0] if cmd.split() else ""
            if first_word:
                return f"Bash({first_word} *)"

        # For Edit/Write, use file extension pattern
        if tool_name in ("Edit", "Write") and "file_path" in data:
            path = data["file_path"]
            if "." in path:
                ext = path.rsplit(".", 1)[-1]
                return f"{tool_name}(*.{ext})"

        # For Read, use directory pattern
        if tool_name == "Read" and "file_path" in data:
            path = data["file_path"]
            if "/" in path:
                dir_path = path.rsplit("/", 1)[0]
                return f"Read({dir_path}/*)"

        return f"{tool_name}(*)"

    async def poll_loop(self, timeout: float = 30.0):
        """Main polling loop. Acquires lock first."""
        acquired = await self.lock.acquire(timeout=0.1)
        if not acquired:
            return

        try:
            self._running = True
            start = time.monotonic()

            while self._running:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    break

                await self.process_updates_once()
                await asyncio.sleep(0.5)
        finally:
            self._running = False
            await self.lock.release()

    def stop(self):
        """Signal the poll loop to stop."""
        self._running = False
