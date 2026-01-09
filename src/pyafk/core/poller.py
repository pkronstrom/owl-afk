"""Telegram poller with file-based locking."""

import asyncio
import fcntl
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from pyafk.core.command_parser import CommandParser
from pyafk.core.handlers import HandlerDispatcher
from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.debug import debug_callback, debug_chain, debug_rule
from pyafk.utils.formatting import escape_html, format_project_id, truncate_command


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
            except Exception:
                pass  # Unexpected error, retry
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
        except Exception:
            pass  # Callback expired or already answered - continue processing anyway

        if ":" not in data:
            return

        action, target_id = data.split(":", 1)
        debug_callback("Parsed callback", action=action, target_id=target_id)

        # Use dispatcher for handlers that have been extracted
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
        ):
            original_text = callback.get("message", {}).get("text", "")
            await self._dispatcher.dispatch(data, callback_id, message_id, original_text)
        elif action == "chain_rule_pattern":
            # Format: chain_rule_pattern:request_id:command_idx:pattern_index
            parts = target_id.split(":")
            if len(parts) >= 3:
                request_id = parts[0]
                command_idx = _safe_int(parts[1])
                pattern_idx = _safe_int(parts[2])
                await self._handle_chain_rule_pattern(
                    request_id, command_idx, pattern_idx, callback_id, message_id
                )
        elif action == "msg_select":
            await self._handle_msg_select(target_id, callback_id, message_id)
        elif action == "chain_approve":
            # Format: chain_approve:request_id:command_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            command_idx = _safe_int(parts[1]) if len(parts) > 1 else 0
            await self._handle_chain_approve(
                request_id, command_idx, callback_id, message_id
            )
        elif action == "chain_deny":
            await self._handle_chain_deny(target_id, callback_id, message_id)
        elif action == "chain_deny_msg":
            await self._handle_chain_deny_msg(target_id, callback_id, message_id)
        elif action == "chain_rule":
            # Format: chain_rule:request_id:command_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            command_idx = _safe_int(parts[1]) if len(parts) > 1 else 0
            await self._handle_chain_rule(
                request_id, command_idx, callback_id, message_id
            )
        elif action == "chain_approve_all":
            await self._handle_chain_approve_all(target_id, callback_id, message_id)
        elif action == "chain_approve_entire":
            await self._handle_chain_approve_entire(target_id, callback_id, message_id)
        elif action == "chain_cancel_rule":
            # Format: chain_cancel_rule:request_id:command_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            command_idx = _safe_int(parts[1]) if len(parts) > 1 else 0
            await self._handle_chain_cancel_rule(
                request_id, command_idx, callback_id, message_id
            )

    async def _handle_approval(
        self,
        request_id: str,
        action: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle approve/deny callback."""
        try:
            debug_callback(
                "_handle_approval called", request_id=request_id, action=action
            )
            request = await self.storage.get_request(request_id)
            if not request:
                debug_callback("Request not found", request_id=request_id)
                await self.notifier.answer_callback(callback_id, "Request not found")
                if message_id:
                    await self.notifier.edit_message(message_id, "⚠️ Request expired")
                return
            debug_callback("Found request", id=request.id, status=request.status)

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

            # Use message_id from callback (the message user clicked) or fall back to stored id
            msg_id = message_id or request.telegram_msg_id
            if msg_id:
                # Format: [project] tool_summary ✅/❌
                session = await self.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                tool_summary = self._format_tool_summary(
                    request.tool_name, request.tool_input
                )
                emoji = "✅" if action == "approve" else "❌"
                await self.notifier.edit_message(
                    msg_id,
                    f"<i>{project_id}</i>\n{emoji} <b>[{request.tool_name}]</b> <code>{tool_summary}</code>",
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
        except Exception as e:
            debug_callback(
                "Error in _handle_approval", error=str(e)[:100], request_id=request_id
            )
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_deny_msg(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle deny with message button - prompt for feedback."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Send feedback prompt
        prompt_msg_id = await self.notifier.send_feedback_prompt(request.tool_name)
        if prompt_msg_id:
            await self.storage.set_pending_feedback(prompt_msg_id, request_id)

        await self.notifier.answer_callback(callback_id, "Reply with feedback")

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

    async def _handle_approve_all(
        self, session_id: str, tool_name: Optional[str], callback_id: str
    ) -> None:
        """Approve all pending requests for a session and tool type, and add a rule for future requests."""
        try:
            from pyafk.core.rules import RulesEngine

            debug_callback(
                "_handle_approve_all called",
                session_id=session_id,
                tool_name=tool_name,
            )
            pending = await self.storage.get_pending_requests()
            debug_callback(
                "Found pending requests",
                count=len(pending),
                pending_session_ids=[r.session_id for r in pending],
            )

            # Filter by session and tool type
            to_approve = [
                r
                for r in pending
                if r.session_id == session_id
                and (tool_name is None or r.tool_name == tool_name)
            ]
            debug_callback("Filtered to_approve", count=len(to_approve))

            for request in to_approve:
                debug_callback(
                    "Approving request", request_id=request.id, tool=request.tool_name
                )
                await self.storage.resolve_request(
                    request_id=request.id,
                    status="approved",
                    resolved_by="user:approve_all",
                )
                # Update the Telegram message
                if request.telegram_msg_id:
                    session = await self.storage.get_session(request.session_id)
                    project_id = format_project_id(
                        session.project_path if session else None, request.session_id
                    )
                    tool_summary = self._format_tool_summary(
                        request.tool_name, request.tool_input
                    )
                    await self.notifier.edit_message(
                        request.telegram_msg_id,
                        f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>",
                    )
                debug_callback("Request approved", request_id=request.id)

            # Add a rule to auto-approve future requests of this tool type
            rule_added = False
            if tool_name:
                pattern = f"{tool_name}(*)"
                engine = RulesEngine(self.storage)
                await engine.add_rule(
                    pattern, "approve", priority=0, created_via="telegram:approve_all"
                )
                debug_callback("Added rule for future requests", pattern=pattern)
                rule_added = True

            tool_label = tool_name or "all"
            debug_callback(
                "Approve all complete",
                approved=len(to_approve),
                tool=tool_label,
                rule_added=rule_added,
            )

            if rule_added:
                await self.notifier.answer_callback(
                    callback_id,
                    f"Approved {len(to_approve)} + added rule for all {tool_name}",
                )
            else:
                await self.notifier.answer_callback(
                    callback_id,
                    f"Approved {len(to_approve)} {tool_label}",
                )
        except Exception as e:
            debug_callback(
                "Error in _handle_approve_all",
                error=str(e)[:100],
                session_id=session_id,
            )
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_cancel_rule(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Cancel rule selection and restore original keyboard."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        await self.notifier.answer_callback(callback_id, "Cancelled")

        # Restore original message with approval keyboard
        if message_id:
            await self.notifier.restore_approval_keyboard(
                message_id,
                request_id,
                request.session_id,
                request.tool_name,
                request.tool_input,
            )

    async def _handle_add_rule_menu(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
        original_text: str = "",
    ) -> None:
        """Show rule pattern options menu inline."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get session for project_path
        session = await self.storage.get_session(request.session_id)
        project_path = session.project_path if session else None

        # Generate pattern options
        patterns = self._generate_rule_patterns(
            request.tool_name, request.tool_input, project_path
        )
        if not patterns:
            await self.notifier.answer_callback(callback_id, "No patterns available")
            return

        await self.notifier.answer_callback(callback_id, "Choose pattern")

        # Edit message inline with pattern options
        if message_id:
            # Strip any previous rule prompt text for clean display
            base_text = (
                original_text.split("\n\n📝")[0]
                if "\n\n📝" in original_text
                else original_text
            )
            await self.notifier.edit_message_with_rule_keyboard(
                message_id, base_text, request_id, patterns
            )

    async def _handle_add_rule(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
        pattern_idx: int = 0,
    ) -> None:
        """Handle add rule selection - creates auto-approve rule and approves request."""
        try:
            request = await self.storage.get_request(request_id)
            if not request:
                await self.notifier.answer_callback(callback_id, "Request not found")
                if message_id:
                    await self.notifier.edit_message(message_id, "⚠️ Request expired")
                return

            # Get session for project_path
            session = await self.storage.get_session(request.session_id)
            project_path = session.project_path if session else None

            # Get the selected pattern (tuple of pattern, label)
            patterns = self._generate_rule_patterns(
                request.tool_name, request.tool_input, project_path
            )
            if not patterns:
                await self.notifier.answer_callback(
                    callback_id, "No patterns available"
                )
                return
            pattern, label = (
                patterns[pattern_idx] if pattern_idx < len(patterns) else patterns[0]
            )

            # Add the rule
            from pyafk.core.rules import RulesEngine

            engine = RulesEngine(self.storage)
            await engine.add_rule(
                pattern, "approve", priority=0, created_via="telegram"
            )

            # Also approve this request
            await self.storage.resolve_request(
                request_id=request_id,
                status="approved",
                resolved_by="user:add_rule",
            )

            # Update the message (same as original since we're inline now)
            if message_id:
                session = await self.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                tool_summary = self._format_tool_summary(
                    request.tool_name, request.tool_input
                )
                await self.notifier.edit_message(
                    message_id,
                    f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>\n📝 Always: {label}",
                )

            await self.notifier.answer_callback(
                callback_id,
                "Always rule added",
            )
        except Exception as e:
            debug_callback(
                "Error in _handle_add_rule", error=str(e)[:100], request_id=request_id
            )
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_subagent_ok(
        self,
        subagent_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle subagent OK button - let subagent stop normally."""
        debug_callback(
            "_handle_subagent_ok called",
            subagent_id=subagent_id,
            message_id=message_id,
        )
        await self.storage.resolve_subagent(subagent_id, "ok")
        debug_callback("Resolved subagent", status="ok")

        await self.notifier.answer_callback(callback_id, "OK")

        if message_id:
            debug_callback("Editing message", message_id=message_id)
            await self.notifier.edit_message(
                message_id,
                "✅ Subagent finished",
            )
            debug_callback("Message edited")

    async def _handle_subagent_continue(
        self,
        subagent_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle subagent Continue button - prompt for instructions."""
        self._log_debug(
            f"_handle_subagent_continue: id={subagent_id[:16]}, msg_id={message_id}"
        )
        debug_callback(
            "_handle_subagent_continue called",
            subagent_id=subagent_id,
            message_id=message_id,
        )
        await self.notifier.answer_callback(callback_id, "Reply with instructions")

        # Send continue prompt
        prompt_msg_id = await self.notifier.send_continue_prompt()
        self._log_debug(f"Sent continue prompt, prompt_msg_id={prompt_msg_id}")
        debug_callback("Sent continue prompt", prompt_msg_id=prompt_msg_id)
        if prompt_msg_id:
            await self.storage.set_subagent_continue_prompt(subagent_id, prompt_msg_id)
            self._log_debug(f"Stored continue prompt for id={subagent_id[:16]}")
            debug_callback("Stored continue prompt", subagent_id=subagent_id)
        else:
            self._log_debug("ERROR: Failed to send continue prompt!")

        # Update the original message to show waiting for instructions
        if message_id:
            await self.notifier.edit_message(
                message_id,
                "⏳ Waiting for instructions...",
                parse_mode=None,
            )

    async def _handle_stop_ok(
        self,
        session_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle stop OK button - let Claude stop normally."""
        await self.storage.resolve_stop(session_id, "ok")
        await self.notifier.answer_callback(callback_id, "OK")

        if message_id:
            await self.notifier.edit_message(
                message_id,
                "✅ Session ended",
            )

    async def _handle_stop_comment(
        self,
        session_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle stop Comment button - prompt for message to Claude."""
        await self.notifier.answer_callback(callback_id, "Reply with your message")

        # Send continue prompt
        prompt_msg_id = await self.notifier.send_continue_prompt()
        if prompt_msg_id:
            await self.storage.set_stop_comment_prompt(session_id, prompt_msg_id)

        # Update the original message
        if message_id:
            await self.notifier.edit_message(
                message_id,
                "⏳ Waiting for your message...",
                parse_mode=None,
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

    async def _handle_chain_approve(
        self,
        request_id: str,
        command_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle chain approval for one command."""
        try:
            debug_chain(
                "chain_approve called", request_id=request_id, command_idx=command_idx
            )
            request = await self.storage.get_request(request_id)
            if not request:
                debug_chain("Request not found", request_id=request_id)
                await self.notifier.answer_callback(callback_id, "Request not found")
                if message_id:
                    await self.notifier.edit_message(message_id, "⚠️ Request expired")
                return

            # Get chain state from pending_feedback (stored as JSON)
            result = await self._get_chain_state(request_id)
            debug_chain("Got chain state", result=result)
            if result:
                chain_state, version = result
            else:
                # Initialize chain state from tool_input
                try:
                    if not request.tool_input:
                        await self.notifier.answer_callback(
                            callback_id, "Missing tool input"
                        )
                        return
                    data = json.loads(request.tool_input)
                    cmd = data.get("command", "")
                    # Parse commands from the bash chain using split_chain
                    parser = CommandParser()
                    commands = parser.split_chain(cmd)
                    chain_state = {
                        "commands": commands,
                        "approved_indices": [],
                    }
                    version = 0
                except Exception:
                    await self.notifier.answer_callback(
                        callback_id, "Failed to parse chain"
                    )
                    return

            # Mark this command as approved
            if command_idx not in chain_state["approved_indices"]:
                chain_state["approved_indices"].append(command_idx)
                debug_chain(
                    "Added command to approved",
                    command_idx=command_idx,
                    approved=chain_state["approved_indices"],
                )

            # Save updated state with optimistic locking
            if not await self._save_chain_state(request_id, chain_state, version):
                # Conflict - re-read and retry once
                debug_chain("Save conflict, retrying", request_id=request_id)
                result = await self._get_chain_state(request_id)
                if result:
                    chain_state, version = result
                    if command_idx not in chain_state["approved_indices"]:
                        chain_state["approved_indices"].append(command_idx)
                    await self._save_chain_state(request_id, chain_state, version)
            debug_chain(
                "Saved chain state",
                approved_count=len(chain_state["approved_indices"]),
                total=len(chain_state["commands"]),
            )

            await self.notifier.answer_callback(callback_id, "Approved")

            # Check if all commands are approved
            if len(chain_state["approved_indices"]) >= len(chain_state["commands"]):
                debug_chain("All commands approved, auto-approving chain")
                # All approved - auto-approve the entire chain (no extra button click needed)
                await self.storage.resolve_request(
                    request_id=request_id,
                    status="approved",
                    resolved_by="user:chain_all_approved",
                )
                await self._clear_chain_state(request_id)

                if message_id:
                    session = await self.storage.get_session(request.session_id)
                    project_id = format_project_id(
                        session.project_path if session else None, request.session_id
                    )
                    msg = self._format_chain_approved_message(
                        chain_state["commands"], project_id
                    )
                    await self.notifier.edit_message(message_id, msg)

                await self.storage.log_audit(
                    event_type="response",
                    session_id=request.session_id,
                    details={
                        "request_id": request_id,
                        "action": "approve",
                        "resolved_by": "user:chain_all_approved",
                        "chain": True,
                        "command_count": len(chain_state["commands"]),
                    },
                )
            else:
                # Find first unapproved command (start from 0, not command_idx + 1)
                next_idx = 0
                while (
                    next_idx < len(chain_state["commands"])
                    and next_idx in chain_state["approved_indices"]
                ):
                    next_idx += 1

                debug_chain(
                    "Moving to next command",
                    next_idx=next_idx,
                    approved_indices=chain_state["approved_indices"],
                )

                if message_id and next_idx < len(chain_state["commands"]):
                    session = await self.storage.get_session(request.session_id)
                    await self.notifier.update_chain_progress(
                        message_id=message_id,
                        request_id=request_id,
                        session_id=request.session_id,
                        commands=chain_state["commands"],
                        current_idx=next_idx,
                        approved_indices=chain_state["approved_indices"],
                        project_path=session.project_path if session else None,
                    )
        except Exception as e:
            debug_callback(
                "Error in _handle_chain_approve",
                error=str(e)[:100],
                request_id=request_id,
            )
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_chain_deny(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle chain denial."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Resolve the request as denied
        await self.storage.resolve_request(
            request_id=request_id,
            status="denied",
            resolved_by="user",
        )

        # Clear chain state
        await self._clear_chain_state(request_id)

        await self.notifier.answer_callback(callback_id, "Denied")

        # Update message to show denial
        if message_id:
            result = await self._get_chain_state(request_id)
            if result:
                chain_state, _version = result
                session = await self.storage.get_session(request.session_id)
                await self.notifier.update_chain_progress(
                    message_id=message_id,
                    request_id=request_id,
                    session_id=request.session_id,
                    commands=chain_state["commands"],
                    current_idx=0,
                    approved_indices=chain_state["approved_indices"],
                    project_path=session.project_path if session else None,
                    denied=True,
                )
            else:
                await self.notifier.edit_message(message_id, "❌ Chain denied")

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": "deny",
                "resolved_by": "user",
                "chain": True,
            },
        )

    async def _handle_chain_deny_msg(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle chain deny with message - prompt for feedback."""
        print(f"[pyafk] _handle_chain_deny_msg called: {request_id}", file=sys.stderr)
        debug_callback("_handle_chain_deny_msg called", request_id=request_id)
        request = await self.storage.get_request(request_id)
        if not request:
            debug_callback("Request not found", request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Store the chain context for when feedback arrives
        prompt_msg_id = await self.notifier.send_feedback_prompt(request.tool_name)
        debug_callback("Sent feedback prompt", prompt_msg_id=prompt_msg_id)
        if prompt_msg_id:
            # Store with chain prefix so feedback handler knows it's a chain denial
            await self.storage.set_pending_feedback(
                prompt_msg_id, f"chain:{request_id}"
            )
            debug_callback(
                "Stored pending_feedback",
                prompt_msg_id=prompt_msg_id,
                value=f"chain:{request_id}",
            )

        await self.notifier.answer_callback(callback_id, "Reply with feedback")

    async def _handle_chain_deny_with_feedback(
        self,
        request_id: str,
        feedback: str,
        prompt_msg_id: int,
    ) -> None:
        """Handle chain denial with user feedback."""
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
        await self._clear_chain_state(request_id)

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
            tool_summary = self._format_tool_summary(
                request.tool_name, request.tool_input
            )
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

    async def _handle_chain_rule(
        self,
        request_id: str,
        command_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle chain rule creation for one command."""
        debug_rule("chain_rule called", request_id=request_id, command_idx=command_idx)
        request = await self.storage.get_request(request_id)
        if not request:
            debug_rule("Request not found", request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get chain state - initialize if not present
        result = await self._get_chain_state(request_id)
        debug_rule("Got chain state", result=result)
        if result:
            chain_state, _version = result
        else:
            # Initialize chain state from tool_input
            try:
                if not request.tool_input:
                    await self.notifier.answer_callback(
                        callback_id, "Missing tool input"
                    )
                    return
                data = json.loads(request.tool_input)
                cmd = data.get("command", "")
                # Parse commands from the bash chain using split_chain
                parser = CommandParser()
                commands = parser.split_chain(cmd)
                chain_state = {
                    "commands": commands,
                    "approved_indices": [],
                }
                await self._save_chain_state(request_id, chain_state, version=0)
            except Exception:
                await self.notifier.answer_callback(
                    callback_id, "Failed to parse chain"
                )
                return

        if command_idx >= len(chain_state["commands"]):
            await self.notifier.answer_callback(callback_id, "Invalid command index")
            return

        # Get the specific command
        cmd = chain_state["commands"][command_idx]

        # Generate patterns for this command
        tool_input = json.dumps({"command": cmd})
        patterns = self._generate_rule_patterns("Bash", tool_input)

        await self.notifier.answer_callback(callback_id, "Choose pattern")

        # Show rule pattern keyboard for this command
        # Note: We encode command_idx in the callback data for the rule pattern
        if message_id:
            await self.notifier.edit_message_with_rule_keyboard(
                message_id,
                f"Command {command_idx + 1}: <code>{escape_html(truncate_command(cmd))}</code>",
                request_id,
                patterns,
                callback_prefix=f"chain_rule_pattern:{request_id}:{command_idx}",
                cancel_callback=f"chain_cancel_rule:{request_id}:{command_idx}",
            )

    async def _handle_chain_cancel_rule(
        self,
        request_id: str,
        command_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle cancel from chain rule menu - go back to chain progress."""
        debug_rule(
            "chain_cancel_rule called", request_id=request_id, command_idx=command_idx
        )
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get chain state
        result = await self._get_chain_state(request_id)
        if not result:
            await self.notifier.answer_callback(callback_id, "Chain state not found")
            return
        chain_state, _version = result

        await self.notifier.answer_callback(callback_id, "Cancelled")

        # Restore the chain progress view
        if message_id:
            session = await self.storage.get_session(request.session_id)
            await self.notifier.update_chain_progress(
                message_id=message_id,
                request_id=request_id,
                session_id=request.session_id,
                commands=chain_state["commands"],
                current_idx=command_idx,
                approved_indices=chain_state["approved_indices"],
                project_path=session.project_path if session else None,
            )

    async def _handle_chain_rule_pattern(
        self,
        request_id: str,
        command_idx: int,
        pattern_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle rule pattern selection for a chain command."""
        try:
            debug_rule(
                "chain_rule_pattern called",
                request_id=request_id,
                command_idx=command_idx,
                pattern_idx=pattern_idx,
            )
            request = await self.storage.get_request(request_id)
            if not request:
                debug_rule("Request not found", request_id=request_id)
                await self.notifier.answer_callback(callback_id, "Request not found")
                if message_id:
                    await self.notifier.edit_message(message_id, "⚠️ Request expired")
                return

            # Get chain state
            result = await self._get_chain_state(request_id)
            debug_rule("Got chain state", result=result)
            if not result:
                debug_rule("Chain state not found", request_id=request_id)
                await self.notifier.answer_callback(
                    callback_id, "Chain state not found"
                )
                return
            chain_state, version = result
            if command_idx >= len(chain_state["commands"]):
                debug_rule(
                    "Invalid command", command_idx=command_idx, chain_state=chain_state
                )
                await self.notifier.answer_callback(callback_id, "Invalid command")
                return

            # Get the specific command and generate patterns
            cmd = chain_state["commands"][command_idx]
            tool_input = json.dumps({"command": cmd})
            patterns = self._generate_rule_patterns("Bash", tool_input)
            debug_rule("Generated patterns", cmd=cmd[:50], pattern_count=len(patterns))

            if pattern_idx >= len(patterns):
                await self.notifier.answer_callback(callback_id, "Invalid pattern")
                return

            pattern, label = patterns[pattern_idx]
            debug_rule("Selected pattern", pattern=pattern, label=label)

            # Add the rule
            from pyafk.core.rules import RulesEngine

            engine = RulesEngine(self.storage)
            await engine.add_rule(
                pattern, "approve", priority=0, created_via="telegram"
            )

            # Also mark this command as approved in the chain
            if command_idx not in chain_state["approved_indices"]:
                chain_state["approved_indices"].append(command_idx)
                debug_rule(
                    "Marked command approved",
                    command_idx=command_idx,
                    approved=chain_state["approved_indices"],
                )

            # Check if the new rule also matches other commands in the chain
            auto_approved = []
            for idx, other_cmd in enumerate(chain_state["commands"]):
                if idx in chain_state["approved_indices"]:
                    continue  # Already approved

                # Check if this command matches the new rule
                other_input = json.dumps({"command": other_cmd})
                rule_result = await engine.check("Bash", other_input)
                if rule_result == "approve":
                    chain_state["approved_indices"].append(idx)
                    auto_approved.append(idx)
                    debug_rule("Auto-approved by new rule", idx=idx, cmd=other_cmd[:50])

            # Save with optimistic locking
            if not await self._save_chain_state(request_id, chain_state, version):
                # Conflict - re-read and retry once
                debug_rule("Save conflict, retrying", request_id=request_id)
                result = await self._get_chain_state(request_id)
                if result:
                    chain_state, version = result
                    # Re-apply changes
                    if command_idx not in chain_state["approved_indices"]:
                        chain_state["approved_indices"].append(command_idx)
                    # Re-check auto-approvals
                    auto_approved = []
                    for idx, other_cmd in enumerate(chain_state["commands"]):
                        if idx in chain_state["approved_indices"]:
                            continue
                        other_input = json.dumps({"command": other_cmd})
                        rule_result = await engine.check("Bash", other_input)
                        if rule_result == "approve":
                            chain_state["approved_indices"].append(idx)
                            auto_approved.append(idx)
                    await self._save_chain_state(request_id, chain_state, version)

            if auto_approved:
                await self.notifier.answer_callback(
                    callback_id,
                    f"Always rule added (+{len(auto_approved)} auto-approved)",
                )
            else:
                await self.notifier.answer_callback(callback_id, "Always rule added")

            # Update UI to show progress
            if message_id:
                session = await self.storage.get_session(request.session_id)

                # Check if all commands are approved
                if len(chain_state["approved_indices"]) >= len(chain_state["commands"]):
                    # All approved - auto-approve the entire chain instead of showing button
                    await self.storage.resolve_request(
                        request_id=request_id,
                        status="approved",
                        resolved_by="chain_all_approved",
                    )
                    await self._clear_chain_state(request_id)

                    await self.storage.log_audit(
                        event_type="chain_approved",
                        session_id=request.session_id,
                        details={
                            "request_id": request_id,
                            "commands": chain_state["commands"],
                            "method": "all_commands_approved",
                        },
                    )

                    # Update message to show all approved
                    project_id = format_project_id(
                        session.project_path if session else None, request.session_id
                    )
                    msg = self._format_chain_approved_message(
                        chain_state["commands"], project_id
                    )
                    await self.notifier.edit_message(message_id, msg)
                else:
                    # Find first unapproved command (start from 0, not command_idx + 1)
                    next_idx = 0
                    while (
                        next_idx < len(chain_state["commands"])
                        and next_idx in chain_state["approved_indices"]
                    ):
                        next_idx += 1

                    if next_idx < len(chain_state["commands"]):
                        await self.notifier.update_chain_progress(
                            message_id=message_id,
                            request_id=request_id,
                            session_id=request.session_id,
                            commands=chain_state["commands"],
                            current_idx=next_idx,
                            approved_indices=chain_state["approved_indices"],
                            project_path=session.project_path if session else None,
                        )
        except Exception as e:
            debug_callback(
                "Error in _handle_chain_rule_pattern",
                error=str(e)[:100],
                request_id=request_id,
            )
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_chain_approve_all(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle final approval of entire chain."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Verify all commands are approved
        result = await self._get_chain_state(request_id)
        if not result:
            await self.notifier.answer_callback(callback_id, "Chain state not found")
            return
        chain_state, _version = result

        if len(chain_state["approved_indices"]) < len(chain_state["commands"]):
            await self.notifier.answer_callback(
                callback_id, "Not all commands approved"
            )
            return

        # Approve the request
        await self.storage.resolve_request(
            request_id=request_id,
            status="approved",
            resolved_by="user",
        )

        # Clear chain state
        await self._clear_chain_state(request_id)

        await self.notifier.answer_callback(callback_id, "Approved")

        # Update message
        if message_id:
            session = await self.storage.get_session(request.session_id)
            project_id = format_project_id(
                session.project_path if session else None, request.session_id
            )
            msg = self._format_chain_approved_message(
                chain_state["commands"], project_id
            )
            await self.notifier.edit_message(message_id, msg)

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": "approve",
                "resolved_by": "user",
                "chain": True,
                "command_count": len(chain_state["commands"]),
            },
        )

    async def _handle_chain_approve_entire(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle upfront approval of entire chain (without individual command approval)."""
        try:
            debug_chain("chain_approve_entire called", request_id=request_id)
            request = await self.storage.get_request(request_id)
            if not request:
                debug_chain("Request not found", request_id=request_id)
                await self.notifier.answer_callback(callback_id, "Request not found")
                if message_id:
                    await self.notifier.edit_message(message_id, "⚠️ Request expired")
                return

            # Parse commands from tool_input
            try:
                if request.tool_input:
                    data = json.loads(request.tool_input)
                    cmd = data.get("command", "")
                    parser = CommandParser()
                    commands = parser.split_chain(cmd)
                else:
                    commands = []
            except Exception:
                commands = []

            # Approve the request directly
            await self.storage.resolve_request(
                request_id=request_id,
                status="approved",
                resolved_by="user:chain_entire",
            )

            await self.notifier.answer_callback(callback_id, "Chain approved")

            # Update message
            if message_id:
                session = await self.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                if commands:
                    msg = self._format_chain_approved_message(commands, project_id)
                else:
                    msg = f"<i>{project_id}</i>\n✅ <b>Chain approved</b>"
                await self.notifier.edit_message(message_id, msg)

            await self.storage.log_audit(
                event_type="response",
                session_id=request.session_id,
                details={
                    "request_id": request_id,
                    "action": "approve",
                    "resolved_by": "user:chain_entire",
                    "chain": True,
                    "command_count": len(commands) if commands else 0,
                },
            )
        except Exception as e:
            debug_callback(
                "Error in _handle_chain_approve_entire",
                error=str(e)[:100],
                request_id=request_id,
            )
            await self.notifier.answer_callback(callback_id, "Error occurred")

    def _chain_state_key(self, request_id: str) -> int:
        """Generate stable key for chain state storage.

        Uses hashlib for stable hashing across process restarts
        (Python's hash() is randomized by PYTHONHASHSEED).
        Uses 15 hex chars (60 bits) to stay within SQLite signed INTEGER max.
        """
        import hashlib

        return int(hashlib.md5(f"chain:{request_id}".encode()).hexdigest()[:15], 16)

    async def _get_chain_state(
        self, request_id: str
    ) -> Optional[tuple[dict[str, Any], int]]:
        """Get chain approval state and version from storage.

        Uses pending_feedback table with a hash of request_id as the message_id.
        The state is stored in the request_id field as JSON.

        Returns (state_dict, version) or None.
        """
        msg_id = self._chain_state_key(request_id)
        result = await self.storage.get_chain_state(msg_id)
        if result:
            state_json, version = result
            try:
                return (json.loads(state_json), version)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    async def _save_chain_state(
        self, request_id: str, state: dict[str, Any], version: int
    ) -> bool:
        """Save chain approval state atomically.

        Uses pending_feedback table with a stable hash of request_id as the message_id.
        The state is stored in the request_id field as JSON.

        Args:
            request_id: The request identifier
            state: The chain state dict to save
            version: Expected version for optimistic locking (0 for new state)

        Returns:
            True if saved successfully, False on version conflict.
        """
        state_json = json.dumps(state)
        msg_id = self._chain_state_key(request_id)
        # Always use atomic save to handle concurrent access
        # For version==0, save_chain_state_atomic will try UPDATE (fail), then INSERT
        return await self.storage.save_chain_state_atomic(msg_id, state_json, version)

    async def _clear_chain_state(self, request_id: str) -> None:
        """Clear chain approval state from storage."""
        msg_id = self._chain_state_key(request_id)
        await self.storage.clear_chain_state(msg_id)

    def _generate_rule_patterns(
        self,
        tool_name: str,
        tool_input: Optional[str],
        project_path: Optional[str] = None,
    ) -> list[tuple[str, str]]:
        """Generate rule pattern options with labels.

        Args:
            tool_name: Name of the tool (Bash, Edit, Read, etc.)
            tool_input: JSON string of tool input
            project_path: Optional project path for directory-scoped patterns

        Returns list of (pattern, label) tuples.
        """
        import json

        patterns = []

        if not tool_input:
            return [(f"{tool_name}(*)", f"Any {tool_name}")]

        try:
            data = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            return [(f"{tool_name}(*)", f"Any {tool_name}")]

        # For Bash commands - use CommandParser for rich pattern generation
        if tool_name == "Bash" and "command" in data:
            cmd = data["command"].strip()

            try:
                # Parse the command using CommandParser
                parser = CommandParser()
                nodes = parser.parse(cmd)

                # Generate patterns from all parsed nodes
                all_patterns = []
                for node in nodes:
                    node_patterns = parser.generate_patterns(node)
                    all_patterns.extend(node_patterns)

                # Convert raw patterns to (pattern, label) tuples with Bash() wrapping
                for pattern in all_patterns:
                    if pattern:  # Skip empty patterns
                        # Create a label based on whether it's an exact command or wildcard
                        if pattern.endswith("*"):
                            label = f"🔧 {pattern}"
                        elif " " in pattern:
                            label = (
                                f"📌 {pattern[:50]}"  # Truncate long commands for label
                            )
                        else:
                            label = f"📌 {pattern}"

                        patterns.append((f"Bash({pattern})", label))

                if patterns:
                    # Remove duplicates while preserving order
                    seen = set()
                    unique = []
                    for pattern, label in patterns:
                        if pattern not in seen:
                            seen.add(pattern)
                            unique.append((pattern, label))
                    return unique
            except Exception:
                # Fallback to basic pattern if parsing fails
                pass

            # Fallback if parsing fails or no patterns generated
            return [
                (f"Bash({cmd})", "📌 This exact command"),
                ("Bash(*)", "🔧 Any Bash"),
            ]

        # For Edit/Write - file patterns
        if tool_name in ("Edit", "Write") and "file_path" in data:
            path = data["file_path"]
            filename = path.rsplit("/", 1)[-1] if "/" in path else path

            patterns.append((f"{tool_name}({path})", f"📌 {filename}"))

            if "." in path:
                ext = path.rsplit(".", 1)[-1]
                patterns.append((f"{tool_name}(*.{ext})", f"📄 Any *.{ext}"))

            if "/" in path:
                dir_path = path.rsplit("/", 1)[0]
                short_dir = dir_path.split("/")[-1] or dir_path
                patterns.append(
                    (f"{tool_name}({dir_path}/*)", f"📁 Any in .../{short_dir}/")
                )

            # Add project-scoped pattern if project_path is available
            if project_path and path.startswith(project_path):
                project_name = project_path.rstrip("/").split("/")[-1]
                if "." in path:
                    ext = path.rsplit(".", 1)[-1]
                    patterns.append(
                        (
                            f"{tool_name}({project_path}/*.{ext})",
                            f"📂 Any *.{ext} in {project_name}/",
                        )
                    )
                patterns.append(
                    (f"{tool_name}({project_path}/*)", f"📂 Any in {project_name}/")
                )

            patterns.append((f"{tool_name}(*)", f"⚡ Any {tool_name}"))

        # For Read - directory patterns
        elif tool_name == "Read" and "file_path" in data:
            path = data["file_path"]
            filename = path.rsplit("/", 1)[-1] if "/" in path else path

            patterns.append((f"Read({path})", f"📌 {filename}"))

            if "/" in path:
                dir_path = path.rsplit("/", 1)[0]
                short_dir = dir_path.split("/")[-1] or dir_path
                patterns.append((f"Read({dir_path}/*)", f"📁 Any in .../{short_dir}/"))

            # Add project-scoped pattern if project_path is available
            if project_path and path.startswith(project_path):
                project_name = project_path.rstrip("/").split("/")[-1]
                patterns.append(
                    (f"Read({project_path}/*)", f"📂 Any in {project_name}/")
                )

            patterns.append(("Read(*)", "⚡ Any Read"))

        # For other tools
        else:
            patterns.append((f"{tool_name}(*)", f"⚡ Any {tool_name}"))

        # Remove duplicates while preserving order (by pattern)
        seen = set()
        unique = []
        for pattern, label in patterns:
            if pattern not in seen:
                seen.add(pattern)
                unique.append((pattern, label))

        return unique

    async def _check_chain_rules(self, cmd: str) -> Optional[str]:
        """Check if a bash command chain matches any rules.

        Returns:
            "approve" if ALL commands match allow rules
            "deny" if ANY command matches deny rule
            None if manual approval needed
        """
        from pyafk.core.rules import RulesEngine

        # Parse the command into chain nodes
        parser = CommandParser()
        nodes = parser.parse(cmd)

        # Check each command in the chain
        engine = RulesEngine(self.storage)
        has_unmatched = False

        for node in nodes:
            # Generate patterns for this command
            patterns = parser.generate_patterns(node)

            # Check if any pattern matches a rule
            matched = False
            for pattern in patterns:
                # Check the pattern as a Bash command
                rule_result = await engine.check(
                    "Bash", json.dumps({"command": pattern})
                )

                if rule_result == "deny":
                    # Any deny rule in the chain means deny the whole chain
                    return "deny"
                elif rule_result == "approve":
                    # This command matched an allow rule
                    matched = True
                    break

            if not matched:
                # This command didn't match any rule
                has_unmatched = True

        # If all commands matched allow rules, approve the whole chain
        if not has_unmatched:
            return "approve"

        # Some commands didn't match any rule - need manual approval
        return None

    def _format_chain_approved_message(
        self,
        commands: list[str],
        project_id: str,
    ) -> str:
        """Format chain approved message with list of commands."""
        cmd_lines = []
        for cmd in commands:
            # Escape HTML entities in command to prevent parse errors
            cmd_escaped = escape_html(truncate_command(cmd))
            cmd_lines.append(f"  • <code>{cmd_escaped}</code>")

        return (
            f"<i>{escape_html(project_id)}</i>\n✅ <b>Chain approved</b>\n"
            + "\n".join(cmd_lines)
        )

    def _format_tool_summary(self, tool_name: str, tool_input: Optional[str]) -> str:
        """Format tool input for display."""
        import json

        if not tool_input:
            return ""

        try:
            data = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            return str(tool_input)[:100]

        # Extract the most relevant field
        summary: str
        if "command" in data:
            summary = str(data["command"])
        elif "file_path" in data:
            summary = str(data["file_path"])
        elif "path" in data:
            summary = str(data["path"])
        elif "url" in data:
            summary = str(data["url"])
        else:
            summary = json.dumps(data)

        # Truncate if too long
        if len(summary) > 100:
            summary = summary[:100] + "..."

        # Escape HTML
        return summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

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
