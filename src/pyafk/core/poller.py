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
        self._offset_file = pyafk_dir / "telegram_offset"
        self._offset: Optional[int] = self._load_offset()
        self._running = False

    def _load_offset(self) -> Optional[int]:
        """Load persisted Telegram update offset."""
        try:
            if self._offset_file.exists():
                return int(self._offset_file.read_text().strip())
        except (ValueError, OSError):
            pass
        return None

    def _save_offset(self, offset: int):
        """Persist Telegram update offset."""
        try:
            self._offset_file.write_text(str(offset))
        except OSError:
            pass

    async def process_updates_once(self) -> int:
        """Process one batch of updates.

        Returns number of updates processed.
        """
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

    async def _handle_message(self, message: dict):
        """Handle a text message - check if it's feedback for a denial or subagent."""
        reply_to = message.get("reply_to_message", {})
        reply_msg_id = reply_to.get("message_id")
        if not reply_msg_id:
            return

        # Check if this is a reply to a feedback prompt we sent
        request_id = await self.storage.get_pending_feedback(reply_msg_id)
        if not request_id:
            return

        feedback = message.get("text", "")

        # Check if this is for a subagent
        if request_id.startswith("subagent:"):
            subagent_id = request_id[9:]  # Strip "subagent:" prefix
            await self._handle_subagent_feedback(subagent_id, feedback, reply_msg_id)
        else:
            await self._handle_deny_with_feedback(request_id, feedback, reply_msg_id)

    async def _handle_subagent_feedback(
        self,
        subagent_id: str,
        instructions: str,
        prompt_msg_id: int,
    ):
        """Handle subagent continue instructions."""
        # Clear the pending feedback entry
        await self.storage.clear_pending_feedback(prompt_msg_id)

        # Resolve the subagent with continue status and instructions
        await self.storage.resolve_subagent(subagent_id, "continue", instructions)

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
        elif action == "deny_msg":
            await self._handle_deny_msg(target_id, callback_id, message_id)
        elif action == "approve_all":
            # Format: approve_all:session_id:tool_name
            parts = target_id.split(":", 1)
            session_id = parts[0]
            tool_name = parts[1] if len(parts) > 1 else None
            await self._handle_approve_all(session_id, tool_name, callback_id)
        elif action == "add_rule":
            # Get original message text for inline edit
            original_text = callback.get("message", {}).get("text", "")
            await self._handle_add_rule_menu(target_id, callback_id, message_id, original_text)
        elif action == "cancel_rule":
            await self._handle_cancel_rule(target_id, callback_id, message_id)
        elif action == "add_rule_pattern":
            # Format: add_rule_pattern:request_id:pattern_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            pattern_idx = int(parts[1]) if len(parts) > 1 else 0
            await self._handle_add_rule(request_id, callback_id, message_id, pattern_idx)
        elif action == "subagent_ok":
            await self._handle_subagent_ok(target_id, callback_id, message_id)
        elif action == "subagent_continue":
            await self._handle_subagent_continue(target_id, callback_id, message_id)

    async def _handle_approval(
        self,
        request_id: str,
        action: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle approve/deny callback."""
        import sys
        print(f"[pyafk] Looking up request: {request_id}", file=sys.stderr)
        request = await self.storage.get_request(request_id)
        if not request:
            print(f"[pyafk] Request not found: {request_id}", file=sys.stderr)
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return
        print(f"[pyafk] Found request: {request.id} status={request.status}", file=sys.stderr)

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
            project_id = self._format_project_id(session.project_path if session else None, request.session_id)
            tool_summary = self._format_tool_summary(request.tool_name, request.tool_input)
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

    async def _handle_deny_msg(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
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
    ):
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

    async def _handle_cancel_rule(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
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
                message_id, request_id, request.session_id, request.tool_name, request.tool_input
            )

    async def _handle_add_rule_menu(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
        original_text: str = "",
    ):
        """Show rule pattern options menu inline."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Generate pattern options
        patterns = self._generate_rule_patterns(request.tool_name, request.tool_input)

        await self.notifier.answer_callback(callback_id, "Choose pattern")

        # Edit message inline with pattern options
        if message_id:
            # Strip any previous rule prompt text for clean display
            base_text = original_text.split("\n\n📝")[0] if "\n\n📝" in original_text else original_text
            await self.notifier.edit_message_with_rule_keyboard(
                message_id, base_text, request_id, patterns
            )

    async def _handle_add_rule(self, request_id: str, callback_id: str, message_id: Optional[int] = None, pattern_idx: int = 0):
        """Handle add rule selection - creates auto-approve rule and approves request."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get the selected pattern (tuple of pattern, label)
        patterns = self._generate_rule_patterns(request.tool_name, request.tool_input)
        pattern, label = patterns[pattern_idx] if pattern_idx < len(patterns) else patterns[0]

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

        # Update the message (same as original since we're inline now)
        if message_id:
            session = await self.storage.get_session(request.session_id)
            project_id = self._format_project_id(session.project_path if session else None, request.session_id)
            tool_summary = self._format_tool_summary(request.tool_name, request.tool_input)
            await self.notifier.edit_message(
                message_id,
                f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>\n📝 Rule: {label}",
            )

        await self.notifier.answer_callback(
            callback_id,
            f"Rule added",
        )

    async def _handle_subagent_ok(
        self,
        subagent_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle subagent OK button - let subagent stop normally."""
        await self.storage.resolve_subagent(subagent_id, "ok")

        await self.notifier.answer_callback(callback_id, "OK")

        if message_id:
            await self.notifier.edit_message(
                message_id,
                "✅ Subagent finished",
            )

    async def _handle_subagent_continue(
        self,
        subagent_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle subagent Continue button - prompt for instructions."""
        await self.notifier.answer_callback(callback_id, "Reply with instructions")

        # Send continue prompt
        prompt_msg_id = await self.notifier.send_continue_prompt()
        if prompt_msg_id:
            await self.storage.set_subagent_continue_prompt(subagent_id, prompt_msg_id)

    def _generate_rule_patterns(self, tool_name: str, tool_input: Optional[str]) -> list[tuple[str, str]]:
        """Generate rule pattern options with labels.

        Returns list of (pattern, label) tuples.
        """
        import json
        import re

        patterns = []

        if not tool_input:
            return [(f"{tool_name}(*)", f"Any {tool_name}")]

        try:
            data = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            return [(f"{tool_name}(*)", f"Any {tool_name}")]

        # For Bash commands
        if tool_name == "Bash" and "command" in data:
            cmd = data["command"].strip()

            # Extract the first simple command (before &&, ||, ;, |)
            first_cmd = re.split(r'\s*(?:&&|\|\||;|\|)\s*', cmd)[0].strip()

            # Parse the first command
            parts = first_cmd.split()
            if not parts:
                return [("Bash(*)", "Any Bash")]

            base_cmd = parts[0]

            # File operation commands - generate directory-based patterns
            file_cmds = {"rm", "mv", "cp", "cat", "touch", "mkdir", "rmdir", "chmod", "chown", "ls"}
            if base_cmd in file_cmds and len(parts) > 1:
                # Extract paths (skip flags that start with -)
                paths = [p for p in parts[1:] if not p.startswith("-")]

                if paths:
                    # Get unique directories from all paths
                    dirs = set()
                    for p in paths:
                        if "/" in p:
                            dirs.add(p.rsplit("/", 1)[0])

                    # Exact command
                    patterns.append((f"Bash({cmd})", "📌 This exact command"))

                    # Add pattern for each unique directory
                    for dir_path in sorted(dirs):
                        short_dir = dir_path.split("/")[-1] or dir_path
                        patterns.append((f"Bash({base_cmd} {dir_path}/*)", f"📁 {base_cmd} .../{short_dir}/*"))

                    # Base command pattern
                    patterns.append((f"Bash({base_cmd} *)", f"🔧 {base_cmd} *"))
                else:
                    patterns.append((f"Bash({cmd})", "📌 This exact command"))
                    patterns.append((f"Bash({base_cmd} *)", f"🔧 {base_cmd} *"))
            else:
                # Non-file commands (git, npm, etc.) - use word-based patterns
                patterns.append((f"Bash({cmd})", "📌 This exact command"))

                if len(parts) >= 2:
                    patterns.append((f"Bash({parts[0]} {parts[1]} *)", f"🔧 {parts[0]} {parts[1]} *"))

                patterns.append((f"Bash({parts[0]} *)", f"🔧 {parts[0]} *"))

        # For Edit/Write - file patterns
        elif tool_name in ("Edit", "Write") and "file_path" in data:
            path = data["file_path"]
            filename = path.rsplit("/", 1)[-1] if "/" in path else path

            patterns.append((f"{tool_name}({path})", f"📌 {filename}"))

            if "." in path:
                ext = path.rsplit(".", 1)[-1]
                patterns.append((f"{tool_name}(*.{ext})", f"📄 Any *.{ext}"))

            if "/" in path:
                dir_path = path.rsplit("/", 1)[0]
                short_dir = dir_path.split("/")[-1] or dir_path
                patterns.append((f"{tool_name}({dir_path}/*)", f"📁 Any in .../{short_dir}/"))

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

    def _format_project_id(self, project_path: Optional[str], session_id: str) -> str:
        """Format project path for display."""
        if project_path:
            parts = project_path.rstrip("/").split("/")
            return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        return session_id[:8]

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
        if "command" in data:
            summary = data["command"]
        elif "file_path" in data:
            summary = data["file_path"]
        elif "path" in data:
            summary = data["path"]
        elif "url" in data:
            summary = data["url"]
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
