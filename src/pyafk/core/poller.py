"""Telegram poller with file-based locking."""

import asyncio
import fcntl
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from pyafk.core.handlers import HandlerDispatcher
from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.debug import debug_callback
from pyafk.utils.formatting import format_project_id


def _safe_int(value: str, default: int = 0) -> int:
    """Safely parse an integer from callback data."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


class PollLock:
    """File-based lock for single poller."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fd: Optional[int] = None

    async def acquire(self, timeout: float = 5.0) -> bool:
        """Try to acquire the lock.

        Returns True if acquired, False if timeout.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        start = time.monotonic()
        while True:
            fd = None
            try:
                fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_RDWR,
                )
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.ftruncate(fd, 0)
                os.write(fd, str(os.getpid()).encode())
                self._fd = fd  # Only store after successful lock
                return True
            except (BlockingIOError, OSError):
                pass  # Lock held by another process, retry
            except Exception as e:
                # Log unexpected errors but continue retrying
                from pyafk.utils.debug import debug

                debug("lock", f"Unexpected error acquiring lock: {e}")
            finally:
                # Clean up fd if we didn't successfully acquire the lock
                if fd is not None and self._fd != fd:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                return False

            await asyncio.sleep(0.1)

    async def release(self) -> None:
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
    ) -> None:
        self.storage = storage
        self.notifier = notifier
        self.pyafk_dir = pyafk_dir
        self.lock = PollLock(pyafk_dir / "poll.lock")
        self._offset_file = pyafk_dir / "telegram_offset"
        self._offset: Optional[int] = self._load_offset()
        self._running = False
        self._debug_log = pyafk_dir / "subagent_debug.log"

        # Handler dispatcher for callback routing
        self._dispatcher = HandlerDispatcher(storage, notifier)

    def _log_debug(self, msg: str) -> None:
        """Log debug message to file and stderr."""
        import time as time_module

        with open(self._debug_log, "a") as f:
            f.write(f"{time_module.strftime('%H:%M:%S')} [poller] {msg}\n")
        print(f"[pyafk] {msg}", file=sys.stderr, flush=True)

    def _load_offset(self) -> Optional[int]:
        """Load persisted Telegram update offset."""
        try:
            if self._offset_file.exists():
                return int(self._offset_file.read_text().strip())
        except (ValueError, OSError) as e:
            debug_callback("Ignored error loading offset", error=str(e)[:50])
        return None

    def _save_offset(self, offset: int) -> None:
        """Persist Telegram update offset."""
        try:
            self._offset_file.write_text(str(offset))
        except OSError as e:
            debug_callback("Ignored error saving offset", error=str(e)[:50])

    async def try_poll_once(self) -> bool:
        """Try to poll Telegram with cooperative locking.

        Only one process can poll at a time. If another process holds the lock,
        this returns immediately without polling.

        Returns True if polling was performed, False if skipped (lock held by another).
        """
        # Try to acquire lock without waiting (timeout=0)
        acquired = await self.lock.acquire(timeout=0)
        if not acquired:
            # Another process is polling, just skip
            return False

        try:
            await self.process_updates_once()
            return True
        finally:
            await self.lock.release()

    async def poll_as_leader(
        self,
        own_request_id: str,
        grace_period: float = 60.0,
        poll_interval: float = 0.5,
    ) -> bool:
        """Become polling leader and poll until done.

        The leader polls Telegram continuously, processing ALL callbacks.
        Keeps polling until:
        - Own request is resolved AND grace period expired
        - If other pending requests exist, continues polling indefinitely
        - Returns True if we were leader, False if another process is leader.

        Args:
            own_request_id: The request ID we're waiting for
            grace_period: How long to keep polling after own request resolves
                          (continues indefinitely if other requests are pending)
            poll_interval: Time between poll cycles
        """
        # Try to acquire lock without waiting
        acquired = await self.lock.acquire(timeout=0)
        if not acquired:
            return False  # Another hook is leader

        try:
            own_resolved_at: Optional[float] = None

            while True:
                # Poll Telegram for updates
                await self.process_updates_once()

                # Check if our own request is resolved
                if own_resolved_at is None:
                    request = await self.storage.get_request(own_request_id)
                    if request and request.status != "pending":
                        own_resolved_at = time.monotonic()
                        debug_callback(
                            "Leader: own request resolved, entering grace period",
                            request_id=own_request_id[:8],
                        )

                # If our request is resolved, check if we should stop
                if own_resolved_at is not None:
                    # Check if there are other pending requests - keep polling for them
                    pending = await self.storage.get_pending_requests()
                    if pending:
                        # Reset grace period timer while other requests are pending
                        own_resolved_at = time.monotonic()
                        debug_callback(
                            "Leader: other requests pending, continuing",
                            pending_count=len(pending),
                        )
                    else:
                        # No other pending requests - check grace period
                        elapsed = time.monotonic() - own_resolved_at
                        if elapsed >= grace_period:
                            debug_callback("Leader: grace period expired, stopping")
                            break

                await asyncio.sleep(poll_interval)

            return True
        finally:
            await self.lock.release()

    async def process_updates_once(self) -> int:
        """Process one batch of updates.

        Returns number of updates processed.
        """
        try:
            # If no saved offset, skip all old updates to avoid processing stale callbacks
            if self._offset is None:
                updates = await self.notifier.get_updates(offset=None, timeout=0)
                if updates:
                    # Set offset to skip all old updates
                    self._offset = updates[-1]["update_id"] + 1
                    self._save_offset(self._offset)
                return 0

            updates = await self.notifier.get_updates(
                offset=self._offset,
                timeout=1,
            )

            processed = 0
            for update in updates:
                self._offset = update["update_id"] + 1
                self._save_offset(self._offset)

                if "callback_query" in update:
                    await self._handle_callback(update["callback_query"])
                    processed += 1
                elif "message" in update:
                    # Check if this is a reply to a feedback prompt
                    await self._handle_message(update["message"])
                    processed += 1

            return processed
        except Exception as e:
            import traceback

            debug_callback("Error in process_updates_once", error=str(e)[:200])
            debug_callback("Traceback", tb=traceback.format_exc()[:500])
            return 0

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle a text message - check for commands, feedback, or subagent replies."""
        text = message.get("text", "")
        debug_callback(
            "_handle_message called",
            text=text[:50] if text else "",
            has_text=bool(text),
        )

        # Handle /msg command
        if text.startswith("/msg"):
            await self._handle_msg_command(text, message)
            return

        # Handle /afk command
        if text.startswith("/afk"):
            await self._handle_afk_command(text)
            return

        # Handle /start command
        if text.startswith("/start"):
            await self._handle_start_command()
            return

        reply_to = message.get("reply_to_message", {})
        reply_msg_id = reply_to.get("message_id")
        if not reply_msg_id:
            debug_callback("No reply_to_message, ignoring")
            return

        # Check if this is a reply to a feedback prompt we sent
        request_id = await self.storage.get_pending_feedback(reply_msg_id)
        self._log_debug(
            f"pending_feedback lookup: msg_id={reply_msg_id} -> {request_id}"
        )
        debug_callback(
            "Looked up pending_feedback",
            reply_msg_id=reply_msg_id,
            request_id=request_id,
        )

        if not request_id:
            # Check if it's a reply to a subagent finish message
            subagent = await self.storage.get_subagent_by_telegram_msg(reply_msg_id)
            self._log_debug(
                f"get_subagent_by_telegram_msg({reply_msg_id}) = {subagent}"
            )
            if subagent:
                instructions = message.get("text", "")
                subagent_id = subagent["subagent_id"]
                self._log_debug(
                    f"Resolving subagent {subagent_id[:16]} with: {instructions[:50]}"
                )
                await self.storage.resolve_subagent(
                    subagent_id, "continue", instructions
                )
                await self.notifier.send_message("📨 Instructions sent to agent")
                # Update the original message to show it's been handled
                await self.notifier.edit_message(
                    reply_msg_id,
                    "✅ Subagent continued with instructions",
                    parse_mode=None,
                )
                debug_callback(
                    "Sent instructions to subagent", subagent_id=subagent_id[:8]
                )
                return

            # Check if it's a reply to an approval message (for followup instructions)
            request = await self.storage.get_request_by_telegram_msg(reply_msg_id)
            if request:
                followup = message.get("text", "")
                await self.storage.add_pending_message(request.session_id, followup)
                await self.notifier.send_message(
                    "📝 Followup queued for next tool call"
                )
                debug_callback(
                    "Queued followup message", session_id=request.session_id[:8]
                )
            return

        feedback = message.get("text", "")

        # Check if this is for a subagent, chain denial, stop, or /msg
        if request_id.startswith("subagent:"):
            subagent_id = request_id[9:]  # Strip "subagent:" prefix
            await self._handle_subagent_feedback(subagent_id, feedback, reply_msg_id)
        elif request_id.startswith("chain:"):
            chain_request_id = request_id[6:]  # Strip "chain:" prefix
            await self._handle_chain_deny_with_feedback(
                chain_request_id, feedback, reply_msg_id
            )
        elif request_id.startswith("stop:"):
            session_id = request_id[5:]  # Strip "stop:" prefix
            await self._handle_stop_feedback(session_id, feedback, reply_msg_id)
        elif request_id.startswith("msg:"):
            session_id = request_id[4:]  # Strip "msg:" prefix
            await self._handle_msg_feedback(session_id, feedback, reply_msg_id)
        else:
            await self._handle_deny_with_feedback(request_id, feedback, reply_msg_id)

    async def _handle_subagent_feedback(
        self,
        subagent_id: str,
        instructions: str,
        prompt_msg_id: int,
    ) -> None:
        """Handle subagent continue instructions."""
        self._log_debug(
            f"_handle_subagent_feedback: id={subagent_id[:16]}, instr={instructions[:30]}"
        )
        debug_callback(
            "_handle_subagent_feedback called",
            subagent_id=subagent_id,
            instructions=instructions[:50],
        )

        # Clear the pending feedback entry
        await self.storage.clear_pending_feedback(prompt_msg_id)

        # Resolve the subagent with continue status and instructions
        await self.storage.resolve_subagent(subagent_id, "continue", instructions)
        self._log_debug("Resolved subagent with continue status")
        debug_callback("Resolved subagent with continue", subagent_id=subagent_id)

        # Delete the prompt message and send confirmation
        await self.notifier.delete_message(prompt_msg_id)
        await self.notifier.send_message("📨 Instructions sent to agent")

    async def _handle_msg_feedback(
        self,
        session_id: str,
        message_text: str,
        prompt_msg_id: int,
    ) -> None:
        """Handle message input for /msg command."""
        self._log_debug(
            f"_handle_msg_feedback: session={session_id[:16]}, msg={message_text[:30]}"
        )

        # Clear the pending feedback entry
        await self.storage.clear_pending_feedback(prompt_msg_id)

        # Store the message
        await self.storage.add_pending_message(session_id, message_text)
        self._log_debug("Message stored in pending_messages")

        # Get session info for confirmation
        session = await self.storage.get_session(session_id)
        if session:
            short_id = session.session_id[:8]
            project = (
                session.project_path.split("/")[-1]
                if session.project_path
                else "unknown"
            )
            await self.notifier.send_message(
                f"📨 Message queued for <code>{short_id}</code> ({project})"
            )
        else:
            await self.notifier.send_message("📨 Message queued")

        # Delete the prompt
        await self.notifier.delete_message(prompt_msg_id)

    async def _handle_msg_command(self, text: str, message: dict[str, Any]) -> None:
        """Handle /msg command to send message to a Claude session.

        Usage:
            /msg - Show inline keyboard with session buttons
            /msg <session_id> <message> - Send message to session directly
        """
        self._log_debug(f"_handle_msg_command: {text[:50]}")
        parts = text.split(None, 2)  # Split: /msg, session_id, message

        if len(parts) == 1:
            # Just /msg - show inline keyboard with sessions
            sessions = await self.storage.get_active_sessions()
            self._log_debug(f"Found {len(sessions)} active sessions")
            if not sessions:
                await self.notifier.send_message("No active sessions")
                return

            # Build inline keyboard with session buttons
            buttons = []
            for s in sessions[-6:]:  # Last 6 sessions (Telegram limit)
                short_id = s.session_id[:8]
                project = s.project_path.split("/")[-1] if s.project_path else "unknown"
                buttons.append(
                    [
                        {
                            "text": f"{project} ({short_id})",
                            "callback_data": f"msg_select:{s.session_id[:16]}",
                        }
                    ]
                )
                self._log_debug(f"  Session: {short_id} - {project}")

            keyboard = {"inline_keyboard": buttons}
            await self.notifier._api_request(
                "sendMessage",
                data={
                    "chat_id": self.notifier.chat_id,
                    "text": "📨 <b>Send message to session:</b>",
                    "parse_mode": "HTML",
                    "reply_markup": json.dumps(keyboard),
                },
            )
            return

        if len(parts) < 3:
            await self.notifier.send_message("Usage: /msg <session_id> <message>")
            return

        session_prefix = parts[1]
        msg_text = parts[2]

        # Find session by prefix
        sessions = await self.storage.get_active_sessions()
        matching = [s for s in sessions if s.session_id.startswith(session_prefix)]

        if not matching:
            await self.notifier.send_message(
                f"No session found matching '{session_prefix}'"
            )
            return

        if len(matching) > 1:
            await self.notifier.send_message(
                f"Multiple sessions match '{session_prefix}'. Be more specific."
            )
            return

        session = matching[0]
        await self.storage.add_pending_message(session.session_id, msg_text)

        short_id = session.session_id[:8]
        project = (
            session.project_path.split("/")[-1] if session.project_path else "unknown"
        )
        await self.notifier.send_message(
            f"📨 Message queued for <code>{short_id}</code> ({project})"
        )

    async def _handle_msg_select(
        self,
        session_prefix: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle session selection for /msg command."""
        self._log_debug(f"_handle_msg_select: prefix={session_prefix}")

        # Find session by prefix
        sessions = await self.storage.get_active_sessions()
        matching = [s for s in sessions if s.session_id.startswith(session_prefix)]

        if not matching:
            self._log_debug(f"No session found for prefix {session_prefix}")
            await self.notifier.answer_callback(callback_id, "Session not found")
            return

        session = matching[0]
        short_id = session.session_id[:8]
        project = (
            session.project_path.split("/")[-1] if session.project_path else "unknown"
        )
        self._log_debug(f"Selected session: {session.session_id[:16]} ({project})")

        await self.notifier.answer_callback(callback_id, f"Selected {project}")

        # Send force_reply prompt
        result = await self.notifier._api_request(
            "sendMessage",
            data={
                "chat_id": self.notifier.chat_id,
                "text": f"💬 Type message for <b>{project}</b> ({short_id}):",
                "parse_mode": "HTML",
                "reply_markup": json.dumps({"force_reply": True, "selective": True}),
            },
        )

        if result.get("ok") and result.get("result"):
            prompt_msg_id = result["result"].get("message_id")
            if prompt_msg_id:
                # Store in pending_feedback with special prefix
                await self.storage.set_pending_feedback(
                    prompt_msg_id, f"msg:{session.session_id}"
                )
                self._log_debug(
                    f"Stored pending_feedback: msg_id={prompt_msg_id}, session={session.session_id[:16]}"
                )
        else:
            self._log_debug(f"Failed to send force_reply prompt: {result}")

        # Update the original message
        if message_id:
            await self.notifier.edit_message(
                message_id,
                f"📨 Sending to <b>{project}</b> ({short_id})...",
                remove_keyboard=True,
            )

    async def _handle_start_command(self) -> None:
        """Handle /start command - show welcome message and status."""
        from pyafk.utils.config import Config

        config = Config(self.pyafk_dir)
        mode = config.get_mode()
        pending = await self.storage.get_pending_requests()
        sessions = await self.storage.get_active_sessions()

        status_emoji = "🟢" if mode == "on" else "🔴"
        status_text = "ON" if mode == "on" else "OFF"

        await self.notifier.send_message(
            f"<b>🤖 pyafk - Remote Approval for Claude Code</b>\n\n"
            f"<b>Status:</b> {status_emoji} {status_text}\n"
            f"<b>Active sessions:</b> {len(sessions)}\n"
            f"<b>Pending requests:</b> {len(pending)}\n\n"
            f"<b>Commands:</b>\n"
            f"/afk - Toggle remote approval mode\n"
            f"/msg - Send message to a Claude session\n"
            f"/start - Show this message"
        )

    async def _handle_afk_command(self, text: str) -> None:
        """Handle /afk command to control AFK mode.

        Usage:
            /afk - Show current mode
            /afk on - Enable remote approval (AFK mode)
            /afk off - Disable remote approval (pending requests fall back to CLI)
        """
        from pyafk.utils.config import Config

        config = Config(self.pyafk_dir)
        parts = text.split()

        if len(parts) == 1:
            # Just /afk - show current mode
            mode = config.get_mode()
            pending = await self.storage.get_pending_requests()
            pending_count = len(pending)
            status = (
                "🟢 ON (remote approval)" if mode == "on" else "🔴 OFF (auto-approve)"
            )
            await self.notifier.send_message(
                f"<b>AFK Status:</b> {status}\n"
                f"<b>Pending requests:</b> {pending_count}\n\n"
                f"<i>Use /afk on or /afk off to change</i>"
            )
            return

        action = parts[1].lower()

        if action == "on":
            config.set_mode("on")
            await self.notifier.send_message(
                "🟢 AFK mode <b>enabled</b>\n\nRemote approval active via Telegram"
            )
        elif action == "off":
            # Get pending requests count before changing mode
            pending = await self.storage.get_pending_requests()
            pending_count = len(pending)

            # Resolve all pending requests with "fallback" status
            # This tells the hook to return empty response, triggering CLI prompt
            for request in pending:
                await self.storage.resolve_request(
                    request_id=request.id,
                    status="fallback",
                    resolved_by="afk_off",
                )
                # Update the Telegram message if exists
                if request.telegram_msg_id:
                    await self.notifier.edit_message(
                        request.telegram_msg_id,
                        "⏸️ Deferred to CLI prompt",
                        parse_mode=None,
                    )

            config.set_mode("off")

            if pending_count > 0:
                await self.notifier.send_message(
                    f"🔴 AFK mode <b>disabled</b>\n\n"
                    f"{pending_count} pending request(s) deferred to CLI prompt"
                )
            else:
                await self.notifier.send_message(
                    "🔴 AFK mode <b>disabled</b>\n\nAll tools will auto-approve"
                )
        else:
            await self.notifier.send_message(
                "Usage:\n"
                "/afk - Show status\n"
                "/afk on - Enable remote approval\n"
                "/afk off - Disable (defer to CLI)"
            )

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
        """Handle a callback query from inline button."""
        callback_id = callback["id"]
        data = callback.get("data", "")
        # Get message_id from callback for editing
        message_id = callback.get("message", {}).get("message_id")

        debug_callback("Received callback", data=data, message_id=message_id)

        # Answer callback immediately to prevent Telegram's 10-second timeout
        # The actual result will be shown by editing the message
        # Ignore errors (callback may already be expired or answered)
        try:
            await self.notifier.answer_callback(callback_id, "")
        except Exception as e:
            # Callback expired or already answered - continue processing anyway
            debug_callback(
                "Failed to answer callback (may be expired)",
                callback_id=callback_id,
                error=str(e)[:50],
            )

        if ":" not in data:
            return

        action, target_id = data.split(":", 1)
        debug_callback("Parsed callback", action=action, target_id=target_id)

        # Use dispatcher for all extracted handlers
        if action in (
            "approve",
            "deny",
            "deny_msg",
            "subagent_ok",
            "subagent_continue",
            "stop_ok",
            "stop_comment",
            "add_rule",
            "add_rule_pattern",
            "cancel_rule",
            "approve_all",
            # Chain handlers
            "chain_approve",
            "chain_deny",
            "chain_deny_msg",
            "chain_approve_all",
            "chain_approve_entire",
            "chain_cancel_rule",
            "chain_rule",
            "chain_rule_pattern",
        ):
            original_text = callback.get("message", {}).get("text", "")
            await self._dispatcher.dispatch(
                data, callback_id, message_id, original_text
            )
        elif action == "msg_select":
            await self._handle_msg_select(target_id, callback_id, message_id)

    async def _handle_deny_with_feedback(
        self,
        request_id: str,
        feedback: str,
        prompt_msg_id: int,
    ) -> None:
        """Handle denial with user feedback."""
        request = await self.storage.get_request(request_id)
        if not request:
            return

        # Clear the pending feedback entry
        await self.storage.clear_pending_feedback(prompt_msg_id)

        # Resolve the request with denial reason
        await self.storage.resolve_request(
            request_id=request_id,
            status="denied",
            resolved_by="user:feedback",
            denial_reason=feedback,
        )

        # Update the original message
        if request.telegram_msg_id:
            await self.notifier.edit_message(
                request.telegram_msg_id,
                f"❌ DENIED - {request.tool_name}\n💬 {feedback}",
            )

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": "deny",
                "resolved_by": "user:feedback",
                "feedback": feedback,
            },
        )

    async def _handle_stop_feedback(
        self,
        session_id: str,
        message: str,
        prompt_msg_id: int,
    ) -> None:
        """Handle reply to stop comment prompt."""
        # Resolve the stop with the comment
        await self.storage.resolve_stop(session_id, "comment", message)
        await self.notifier.send_message("📨 Message will be delivered to Claude")
        await self.notifier.edit_message(
            prompt_msg_id, "✅ Message queued", parse_mode=None
        )

    async def _handle_chain_deny_with_feedback(
        self,
        request_id: str,
        feedback: str,
        prompt_msg_id: int,
    ) -> None:
        """Handle chain denial with user feedback."""
        from pyafk.core.handlers.chain import ChainStateManager
        from pyafk.utils.formatting import format_tool_summary

        debug_callback(
            "_handle_chain_deny_with_feedback called",
            request_id=request_id,
            feedback=feedback[:50],
        )
        request = await self.storage.get_request(request_id)
        if not request:
            debug_callback("Request not found", request_id=request_id)
            return

        # Clear the pending feedback entry
        await self.storage.clear_pending_feedback(prompt_msg_id)

        # Resolve the request with denial reason
        await self.storage.resolve_request(
            request_id=request_id,
            status="denied",
            resolved_by="user:feedback",
            denial_reason=feedback,
        )

        # Clear chain state
        chain_mgr = ChainStateManager(self.storage)
        await chain_mgr.clear_state(request_id)

        # Delete the feedback prompt message
        debug_callback("Deleting feedback prompt", prompt_msg_id=prompt_msg_id)
        await self.notifier.delete_message(prompt_msg_id)

        # Update the original approval message
        debug_callback(
            "Updating original message", telegram_msg_id=request.telegram_msg_id
        )
        if request.telegram_msg_id:
            session = await self.storage.get_session(request.session_id)
            project_id = format_project_id(
                session.project_path if session else None, request.session_id
            )
            tool_summary = format_tool_summary(request.tool_name, request.tool_input)
            await self.notifier.edit_message(
                request.telegram_msg_id,
                f"<i>{project_id}</i>\n❌ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>\n\n💬 {feedback}",
            )
            debug_callback("Message updated for chain denial")

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": "deny",
                "resolved_by": "user",
                "feedback": feedback,
                "chain": True,
            },
        )

    async def poll_loop(self, timeout: float = 30.0) -> None:
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

    def stop(self) -> None:
        """Signal the poll loop to stop."""
        self._running = False
