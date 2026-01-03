"""Telegram poller with file-based locking."""

import asyncio
import fcntl
import os
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

        start = asyncio.get_event_loop().time()
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
                    os.close(self._fd)
                    self._fd = None

                elapsed = asyncio.get_event_loop().time() - start
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

        if ":" not in data:
            return

        action, target_id = data.split(":", 1)

        if action in ("approve", "deny"):
            await self._handle_approval(target_id, action, callback_id)
        elif action == "approve_all":
            await self._handle_approve_all(target_id, callback_id)
        elif action == "add_rule":
            await self._handle_add_rule(target_id, callback_id)

    async def _handle_approval(
        self,
        request_id: str,
        action: str,
        callback_id: str,
    ):
        """Handle approve/deny callback."""
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

        request = await self.storage.get_request(request_id)
        if request and request.telegram_msg_id:
            await self.notifier.edit_message(
                request.telegram_msg_id,
                f"{'Approved' if action == 'approve' else 'Denied'} {request.tool_name} - {status.upper()}",
            )

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id if request else None,
            details={
                "request_id": request_id,
                "action": action,
                "resolved_by": "user",
            },
        )

    async def _handle_approve_all(self, session_id: str, callback_id: str):
        """Approve all pending requests for a session."""
        pending = await self.storage.get_pending_requests()
        session_pending = [r for r in pending if r.session_id == session_id]

        for request in session_pending:
            await self.storage.resolve_request(
                request_id=request.id,
                status="approved",
                resolved_by="user:approve_all",
            )

        await self.notifier.answer_callback(
            callback_id,
            f"Approved {len(session_pending)} requests",
        )

    async def _handle_add_rule(self, request_id: str, callback_id: str):
        """Handle add rule button."""
        await self.notifier.answer_callback(
            callback_id,
            "Rule creation coming soon",
        )

    async def poll_loop(self, timeout: float = 30.0):
        """Main polling loop. Acquires lock first."""
        acquired = await self.lock.acquire(timeout=0.1)
        if not acquired:
            return

        try:
            self._running = True
            start = asyncio.get_event_loop().time()

            while self._running:
                elapsed = asyncio.get_event_loop().time() - start
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
